"""Route classifier at runtime: text → (route, confidence, intent).

Decision rule: `human` if P(human) ≥ τ (policy.yaml routing.human_confidence_tau), otherwise the
most likely of the other routes. τ trades missed handoffs against unnecessary ones; it is set on
the validation split so human recall stays ≥ 0.95.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import joblib
import numpy as np
from scipy import sparse

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedEmbedder:
    """Multilingual sentence embeddings on ONNX Runtime (no PyTorch), unit-normalised."""

    def __init__(self, model_name: str = EMBEDDING_MODEL, cache_dir: Path | None = None) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name, cache_dir=str(cache_dir) if cache_dir else None)

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array(list(self._model.embed(texts)), dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


@dataclass(frozen=True)
class Prediction:
    route: str
    confidence: float  # probability of the chosen route
    p_human: float
    intent: str
    intent_confidence: float


def decide(probabilities: np.ndarray, labels: list[str], tau: float) -> tuple[str, float]:
    human = labels.index("human")
    if probabilities[human] >= tau:
        return "human", float(probabilities[human])
    others = [i for i in range(len(labels)) if i != human]
    best = max(others, key=lambda i: probabilities[i])
    return labels[best], float(probabilities[best])


def normalise(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in plain if not unicodedata.combining(c))


def featurise(
    texts: list[str], features: str, embedder: Embedder | None, vectorizer: Any | None
) -> Any:
    """`embedding`, `tfidf` (accent-insensitive character n-grams) or `both`."""
    parts = []
    if features in ("embedding", "both"):
        assert embedder is not None
        parts.append(sparse.csr_matrix(embedder.embed(texts)))
    if features in ("tfidf", "both"):
        assert vectorizer is not None
        parts.append(vectorizer.transform([normalise(t) for t in texts]))
    return sparse.hstack(parts).tocsr()


class RouteClassifier:
    def __init__(
        self,
        route_model: Any,
        intent_model: Any,
        embedder: Embedder | None,
        meta: dict[str, Any],
        vectorizer: Any | None = None,
    ) -> None:
        self.route_model = route_model
        self.intent_model = intent_model
        self.embedder = embedder
        self.meta = meta
        self.vectorizer = vectorizer

    @property
    def route_labels(self) -> list[str]:
        return list(self.route_model.classes_)

    @classmethod
    def load(cls, path: Path, embedder: Embedder | None = None) -> RouteClassifier:
        artifact = joblib.load(path)
        meta = artifact["meta"]
        if embedder is None and meta["features"] in ("embedding", "both"):
            cache = meta.get("embedding_cache")
            embedder = FastEmbedEmbedder(meta["embedding_model"], Path(cache) if cache else None)
        return cls(
            artifact["route_model"],
            artifact["intent_model"],
            embedder,
            meta,
            artifact["vectorizer"],
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "route_model": self.route_model,
                "intent_model": self.intent_model,
                "vectorizer": self.vectorizer,
                "meta": self.meta,
            },
            path,
        )

    def predict_many(self, texts: list[str], tau: float) -> list[Prediction]:
        x = featurise(texts, self.meta["features"], self.embedder, self.vectorizer)
        route_p = self.route_model.predict_proba(x)
        intent_p = self.intent_model.predict_proba(x)
        labels, intents = self.route_labels, list(self.intent_model.classes_)
        human = labels.index("human")
        out = []
        for rp, ip in zip(route_p, intent_p, strict=True):
            route, confidence = decide(rp, labels, tau)
            best_intent = int(np.argmax(ip))
            out.append(
                Prediction(
                    route,
                    confidence,
                    float(rp[human]),
                    intents[best_intent],
                    float(ip[best_intent]),
                )
            )
        return out

    def predict(self, text: str, tau: float) -> Prediction:
        return self.predict_many([text], tau)[0]
