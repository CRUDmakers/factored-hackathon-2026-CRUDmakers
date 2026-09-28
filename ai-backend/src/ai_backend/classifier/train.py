"""Train and evaluate the route classifier (SPEC §10).

    python -m ai_backend.classifier.train

1. Features: multilingual MiniLM sentence embeddings (fastembed), accent-insensitive character
   n-grams (TF-IDF, fit on train), or both.
2. For each feature set and C of LogisticRegression(class_weight="balanced"): τ = the largest
   threshold keeping validation human-route recall ≥ 0.95, then validation macro-F1 at that τ.
3. Keeps the best (features, C, τ) on validation.
4. Evaluates the keyword baseline and the model on the frozen test split, once.
5. Writes classifier_data/report.md + report.json, and the model, with its thresholds, to
   models/route_classifier.joblib (committed: the deployed model is the reported one).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score, recall_score

from ai_backend.classifier import baseline_rules
from ai_backend.classifier.dataset import DATA_DIR, ROUTES, Utterance
from ai_backend.classifier.predict import (
    EMBEDDING_MODEL,
    Embedder,
    FastEmbedEmbedder,
    RouteClassifier,
    decide,
    featurise,
    normalise,
)
from ai_backend.classifier.split import SPLIT_FILE, file_hash, load

MODEL_PATH = Path("models/route_classifier.joblib")
EMBEDDING_CACHE = Path("models/fastembed")
C_GRID = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0)
TAU_GRID = tuple(round(float(t), 2) for t in np.arange(0.05, 0.96, 0.01))
TARGET_HUMAN_RECALL = 0.95


FEATURE_SETS = ("embedding", "tfidf", "both")


class CachedEmbedder:
    """Embeds each text once for the whole grid search."""

    def __init__(self, embedder: Embedder, texts: list[str]) -> None:
        self.model_name = getattr(embedder, "model_name", "custom")
        self._vectors = dict(zip(texts, embedder.embed(texts), strict=True))

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([self._vectors[t] for t in texts])


def make_vectorizer() -> TfidfVectorizer:
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)


def fit(x: Any, y: list[str], c: float) -> LogisticRegression:
    return LogisticRegression(C=c, class_weight="balanced", max_iter=5000).fit(x, y)


def choose_tau(
    probabilities: np.ndarray, labels: list[str], y_val: list[str]
) -> tuple[float, list]:
    curve = []
    for tau in TAU_GRID:
        predicted = [decide(p, labels, tau)[0] for p in probabilities]
        recall = recall_score(y_val, predicted, labels=["human"], average="macro", zero_division=0)
        false_pos = sum(
            p == "human" and y != "human" for p, y in zip(predicted, y_val, strict=True)
        )
        curve.append(
            {"tau": tau, "human_recall": round(float(recall), 4), "false_positives": false_pos}
        )
    passing = [row for row in curve if row["human_recall"] >= TARGET_HUMAN_RECALL]
    tau = max(row["tau"] for row in passing) if passing else min(TAU_GRID)
    return tau, curve


TARGET_PRECISION = 0.90


def precision_threshold(scores: list[float], positive: list[bool]) -> float:
    """The smallest threshold whose precision on validation is ≥ TARGET_PRECISION (1.0 = never)."""
    for t in TAU_GRID:
        chosen = [p for s, p in zip(scores, positive, strict=True) if s >= t]
        if chosen and sum(chosen) / len(chosen) >= TARGET_PRECISION:
            return t
    return 1.0


def triage(probabilities: np.ndarray, labels: list[str], thresholds: dict[str, float]) -> list[str]:
    """How the system uses the classifier: direct handoff, flag to the agent, refuse, or pass."""
    h, o = labels.index("human"), labels.index("out_of_scope")
    out = []
    for p in probabilities:
        if p[h] >= thresholds["human_direct_tau"]:
            out.append("direct_handoff")
        elif p[h] >= thresholds["human_confidence_tau"]:
            out.append("flagged")
        elif (
            decide(p, labels, 1.1)[0] == "out_of_scope"
            and p[o] >= thresholds["out_of_scope_min_confidence"]
        ):
            out.append("refused")
        else:
            out.append("agent")
    return out


def triage_metrics(actions: list[str], y_true: list[str]) -> dict[str, Any]:
    pairs = list(zip(actions, y_true, strict=True))
    human = sum(y == "human" for y in y_true)
    direct = [y for a, y in pairs if a == "direct_handoff"]
    refused = [y for a, y in pairs if a == "refused"]
    return {
        "direct_handoff": {
            "count": len(direct),
            "correct": sum(y == "human" for y in direct),
            "recall_of_human": f"{sum(y == 'human' for y in direct)}/{human}",
        },
        "human_reached_direct_or_flagged": (
            f"{sum(a in ('direct_handoff', 'flagged') and y == 'human' for a, y in pairs)}/{human}"
        ),
        "non_human_flagged_to_agent": sum(a == "flagged" and y != "human" for a, y in pairs),
        "refused": {"count": len(refused), "correct": sum(y == "out_of_scope" for y in refused)},
    }


def select(x_train, y_train, x_val, y_val) -> dict[str, Any]:
    """For each C: τ from the recall constraint, then validation macro-F1 at that τ."""
    best: dict[str, Any] | None = None
    for c in C_GRID:
        model = fit(x_train, y_train, c)
        labels = list(model.classes_)
        tau, curve = choose_tau(model.predict_proba(x_val), labels, y_val)
        predicted = [decide(p, labels, tau)[0] for p in model.predict_proba(x_val)]
        f1 = f1_score(y_val, predicted, labels=list(ROUTES), average="macro", zero_division=0)
        recall_ok = any(
            row["tau"] == tau and row["human_recall"] >= TARGET_HUMAN_RECALL for row in curve
        )
        candidate = {
            "C": c,
            "tau": tau,
            "macro_f1": round(float(f1), 4),
            "recall_ok": recall_ok,
            "curve": curve,
        }
        if best is None or (candidate["recall_ok"], candidate["macro_f1"]) > (
            best["recall_ok"],
            best["macro_f1"],
        ):
            best = candidate
    assert best is not None
    return best


def metrics(y_true: list[str], y_pred: list[str], rows: list[Utterance]) -> dict[str, Any]:
    report = classification_report(
        y_true, y_pred, labels=list(ROUTES), output_dict=True, zero_division=0
    )
    human_true = sum(y == "human" for y in y_true)
    human_hit = sum(p == y == "human" for p, y in zip(y_pred, y_true, strict=True))
    false_pos = sum(p == "human" and y != "human" for p, y in zip(y_pred, y_true, strict=True))
    by_lang = {}
    for lang in ("es", "pt"):
        idx = [i for i, r in enumerate(rows) if r.lang == lang]
        yt, yp = [y_true[i] for i in idx], [y_pred[i] for i in idx]
        by_lang[lang] = {
            "n": len(idx),
            "macro_f1": round(
                f1_score(yt, yp, labels=list(ROUTES), average="macro", zero_division=0), 4
            ),
            "human_recall": round(
                sum(p == y == "human" for p, y in zip(yp, yt, strict=True))
                / max(1, sum(y == "human" for y in yt)),
                4,
            ),
        }
    return {
        "n": len(y_true),
        "macro_f1": round(report["macro avg"]["f1-score"], 4),
        "per_class": {
            r: {k: round(report[r][k], 4) for k in ("precision", "recall", "f1-score", "support")}
            for r in ROUTES
        },
        "human_recall": {
            "hit": human_hit,
            "of": human_true,
            "value": round(human_hit / human_true, 4),
        },
        "human_false_positives": {"count": false_pos, "of_non_human": len(y_true) - human_true},
        "confusion_matrix": {
            "labels": list(ROUTES),
            "rows_true_cols_predicted": confusion_matrix(
                y_true, y_pred, labels=list(ROUTES)
            ).tolist(),
        },
        "by_language": by_lang,
    }


def train(embedder: Embedder, csv_path: Path = DATA_DIR / "utterances.csv") -> dict[str, Any]:
    split = load(csv_path)
    cached = CachedEmbedder(embedder, sorted({r.text for rows in split.values() for r in rows}))
    vectorizer = make_vectorizer().fit([normalise(r.text) for r in split["train"]])  # train only

    def x(rows: list[Utterance], features: str) -> Any:
        return featurise([r.text for r in rows], features, cached, vectorizer)

    def y(rows: list[Utterance], field: str = "route") -> list[str]:
        return [getattr(r, field) for r in rows]

    y_train, y_val, y_test = y(split["train"]), y(split["validation"]), y(split["test"])
    candidates = {
        f: select(x(split["train"], f), y_train, x(split["validation"], f), y_val)
        for f in FEATURE_SETS
    }
    features = max(
        FEATURE_SETS, key=lambda f: (candidates[f]["recall_ok"], candidates[f]["macro_f1"])
    )
    chosen = candidates[features]
    c, tau = chosen["C"], chosen["tau"]

    x_train, x_val, x_test = (x(split[k], features) for k in ("train", "validation", "test"))
    route_model = fit(x_train, y_train, c)
    intent_model = fit(x_train, y(split["train"], "intent"), c)
    labels = list(route_model.classes_)

    val_p = route_model.predict_proba(x_val)
    h, o = labels.index("human"), labels.index("out_of_scope")
    thresholds = {
        "human_confidence_tau": float(tau),
        "human_direct_tau": precision_threshold(
            [float(p[h]) for p in val_p], [yv == "human" for yv in y_val]
        ),
        "out_of_scope_min_confidence": precision_threshold(
            [float(p[o]) if decide(p, labels, 1.1)[0] == "out_of_scope" else 0.0 for p in val_p],
            [yv == "out_of_scope" for yv in y_val],
        ),
    }
    val_pred = [decide(p, labels, tau)[0] for p in val_p]
    test_pred = [decide(p, labels, tau)[0] for p in route_model.predict_proba(x_test)]
    baseline_test = [baseline_rules.route(r.text) for r in split["test"]]
    intent_test, intent_pred = y(split["test"], "intent"), list(intent_model.predict(x_test))

    classifier = RouteClassifier(
        route_model,
        intent_model,
        embedder if features != "tfidf" else None,
        {
            "features": features,
            "embedding_model": cached.model_name,
            "embedding_cache": str(EMBEDDING_CACHE),
            "C": c,
            "tau": tau,
            "thresholds": thresholds,
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "utterances_sha256": file_hash(csv_path),
            "split_sha256": file_hash(SPLIT_FILE),
        },
        vectorizer if features != "embedding" else None,
    )
    return {
        "classifier": classifier,
        "report": {
            "dataset": {
                "rows": {k: len(v) for k, v in split.items()},
                "families": {k: len({r.template_id for r in v}) for k, v in split.items()},
                "author": "model-drafted (claude-opus-5-5); see classifier_data/README.md",
            },
            "features": features,
            "embedding_model": cached.model_name,
            "C": c,
            "tau": tau,
            "selection_validation": {
                f: {k: v for k, v in cand.items() if k != "curve"} for f, cand in candidates.items()
            },
            "tau_curve_validation": chosen["curve"],
            "thresholds": thresholds,
            "triage_test": triage_metrics(
                triage(route_model.predict_proba(x_test), labels, thresholds), y_test
            ),
            "validation": metrics(y_val, val_pred, split["validation"]),
            "test": {
                "baseline": metrics(y_test, baseline_test, split["test"]),
                "model": metrics(y_test, test_pred, split["test"]),
                "intent": {
                    "accuracy": round(
                        float(
                            np.mean([a == b for a, b in zip(intent_pred, intent_test, strict=True)])
                        ),
                        4,
                    ),
                    "macro_f1": round(
                        f1_score(intent_test, intent_pred, average="macro", zero_division=0), 4
                    ),
                },
            },
            "errors_test": [
                {"text": r.text, "lang": r.lang, "true": r.route, "predicted": p}
                for r, p in zip(split["test"], test_pred, strict=True)
                if p != r.route
            ],
        },
    }


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = train(FastEmbedEmbedder(EMBEDDING_MODEL, EMBEDDING_CACHE))
    result["classifier"].save(MODEL_PATH)
    report = result["report"]
    (DATA_DIR / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    from ai_backend.classifier.report import render

    (DATA_DIR / "report.md").write_text(render(report), encoding="utf-8")
    t = report["test"]
    print(
        f"features={report['features']} C={report['C']} thresholds={report['thresholds']} | "
        f"test macro-F1 baseline {t['baseline']['macro_f1']} → model {t['model']['macro_f1']} | "
        f"human recall baseline {t['baseline']['human_recall']['value']} → model "
        f"{t['model']['human_recall']['value']}"
    )


if __name__ == "__main__":
    main()
