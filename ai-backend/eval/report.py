"""The evaluation report: report.md, metrics.json and cases.csv (SPEC §11.2).

Written by the runner, or rebuilt from one or more saved runs (e.g. one run per agent model):

    python -m eval.report eval/runs/<run> [eval/runs/<run> ...] [--out eval/reports/<name>]
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_backend.config import ModelSpec, load_model_registry
from eval.grading import CaseResult
from eval.metrics import across_repeats, breakdown, by, summarise

HEADLINE = [
    ("safe_automated_resolution", "Safe automated resolution (in-scope)"),
    ("automation_attempted", "Automation attempted (in-scope, not handed off)"),
    ("containment", "Containment (all cases, not a success measure)"),
    ("missed_handoffs", "Missed handoffs (should hand off, didn't)"),
    ("unnecessary_handoffs", "Unnecessary handoffs (did, shouldn't)"),
    ("unsafe", "Unsafe outcomes"),
    ("passed", "All checks passed"),
    ("provider_failures", "Provider failures (handed off as ASSISTANT_FAILURE)"),
]


def _rate(r: dict[str, Any]) -> str:
    if r["rate"] is None:
        return f"– (0/{r['of']})"
    return f"{r['rate']:.1%} ({r['hits']}/{r['of']})"


def _spread(r: dict[str, Any]) -> str:
    if r["mean"] is None:
        return "–"
    return f"{r['mean']:.1%} ± {r['std']:.1%}"


def _agent_spec(system: str, meta: dict[str, Any]) -> ModelSpec | None:
    """The agent model a system ran on, for cost: `S@<key>` names it, the others ran on the
    run's default agent model (matched by the provider's model name). B0 calls no model."""
    models = load_model_registry(Path(__file__).resolve().parents[1] / "config" / "models.yaml")
    if "@" in system:
        return models.models.get(system.split("@", 1)[1])
    return next((m for m in models.models.values() if m.model == meta["agent_model"]), None)


def _cost(summary: dict[str, Any]) -> str:
    def usd(v: float | None) -> str:
        return "not defined" if v is None else f"${v:.4f}"

    return f"{usd(summary['cost_per_case_usd'])} / {usd(summary['cost_per_resolution_usd'])}"


def write_report(
    results: list[CaseResult],
    out_dir: Path,
    meta: dict[str, Any],
    raw: list[dict[str, Any]] | None = None,
    judge: list[dict[str, Any]] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    systems = by(results, lambda c: c.system)
    metrics = {
        name: {
            "summary": summarise(cases, _agent_spec(name, meta)),
            "across_repeats": {k: across_repeats(cases, k) for k, _ in HEADLINE},
            "by_language": breakdown(cases, "language"),
            "by_category": breakdown(cases, "category"),
            "by_segment": breakdown(cases, "segment"),
            "by_family": breakdown(cases, "family"),
        }
        for name, cases in systems.items()
    }
    (out_dir / "metrics.json").write_text(
        json.dumps({"meta": meta, "metrics": metrics}, indent=2, default=str) + "\n"
    )
    with (out_dir / "cases.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "system",
                "repeat",
                "scenario_id",
                "category",
                "family",
                "language",
                "segment",
                "outcome",
                "passed",
                "unsafe",
                "failed_checks",
                "reason_codes",
                "latency_ms",
                "tokens",
            ]
        )
        for c in sorted(results, key=lambda c: (c.system, c.repeat, c.scenario_id)):
            writer.writerow(
                [
                    c.system,
                    c.repeat,
                    c.scenario_id,
                    c.category,
                    c.family,
                    c.language,
                    c.segment,
                    c.outcome,
                    c.passed,
                    ";".join(c.unsafe),
                    ";".join(k for k, v in c.checks.items() if not v),
                    ";".join(c.reason_codes),
                    c.latency_ms,
                    c.tokens_in + c.tokens_out,
                ]
            )
    (out_dir / "report.md").write_text(
        render(metrics, results, meta, raw or [], judge), encoding="utf-8"
    )
    return out_dir / "report.md"


def render(
    metrics: dict[str, Any],
    results: list[CaseResult],
    meta: dict[str, Any],
    raw: list[dict[str, Any]],
    judge: list[dict[str, Any]] | None,
) -> str:
    names = list(metrics)
    lines = [
        f"# Evaluation report: {meta['split']} split",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. "
        f"{meta['scenarios']} scenarios × {len(names)} systems × {meta['repeats']} repeats "
        f"= {len(results)} cases. Default agent model: `{meta['agent_model']}`. "
        f"Raw transcripts: {', '.join(f'`{r}`' for r in meta['runs'])} (not committed)."
        + (
            " Regraded from the saved transcripts with the current grader."
            if meta.get("regraded")
            else ""
        )
        + "".join(
            f" Only repeat(s) {', '.join(map(str, reps))} of {name} are included."
            for name, reps in (meta.get("kept_repeats") or {}).items()
        ),
        "",
        "**Systems.** **S** = the full system (policy engine, classifier triage, confirmation, verification, handoff). "
        "**B1** = the same model, tools and prompt in a plain tool loop, with no policy engine and no classifier (writes run immediately). "
        "**B0** = a keyword FAQ bot on the baseline rules. "
        "**S@model** = the full system with another agent model (model comparison).",
        "",
        "## Headline",
        "",
        "Pooled over all repeats, with the numerator and denominator; the second column of each system is the mean ± standard deviation across repeats.",
        "",
        "| Metric | " + " | ".join(f"{n} (pooled) | {n} (per repeat)" for n in names) + " |",
        "|---|" + "---|---|" * len(names),
    ]
    for key, label in HEADLINE:
        cells = []
        for n in names:
            cells.append(_rate(metrics[n]["summary"][key]))
            cells.append(_spread(metrics[n]["across_repeats"][key]))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += [
        "| Tokens per case (mean) | "
        + " | ".join(f"{metrics[n]['summary']['tokens_per_case']} | " for n in names)
        + " |",
        "| Latency p50 / p95 (ms, see note) | "
        + " | ".join(
            f"{metrics[n]['summary']['latency_ms']['p50']} / {metrics[n]['summary']['latency_ms']['p95']} | "
            for n in names
        )
        + " |",
        "| Cost per case / per resolution (USD, list-price estimate, see note) | "
        + " | ".join(f"{_cost(metrics[n]['summary'])} | " for n in names)
        + " |",
        "",
        "Definitions (SPEC §11.3): *in-scope* = normal, ambiguous and multilingual cases the system should resolve itself; "
        "*safe automated resolution* = an in-scope case that passed every check, without a handoff and without an unsafe outcome; "
        "*unsafe* = a disclosure, a payment that wasn't authorised or confirmed, a claim that a payment was done when the bank has none, "
        "or an answer that contradicts the record.",
    ]
    if meta.get("notes"):
        lines += ["", meta["notes"].strip()]
    lines += [
        "",
        "## Unsafe outcomes by kind",
        "",
        "| Kind | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    kinds = sorted({k for n in names for k in metrics[n]["summary"]["unsafe_by_kind"]})
    for kind in kinds or ["(none)"]:
        lines.append(
            f"| {kind} | "
            + " | ".join(str(metrics[n]["summary"]["unsafe_by_kind"].get(kind, 0)) for n in names)
            + " |"
        )
    for field, title in (
        ("by_language", "language"),
        ("by_category", "category"),
        ("by_segment", "segment"),
    ):
        lines += [
            "",
            f"## By {title}",
            "",
            "Checks passed · safe automated resolution · unsafe",
            "",
            f"| {title} | " + " | ".join(names) + " |",
            "|---|" + "---|" * len(names),
        ]
        for value in sorted({v for n in names for v in metrics[n][field]}):
            cells = []
            for n in names:
                m = metrics[n][field].get(value)
                cells.append(
                    "–"
                    if m is None
                    else f"{_rate(m['passed'])} · {_rate(m['safe_automated_resolution'])} · {_rate(m['unsafe'])}"
                )
            lines.append(f"| {value} | " + " | ".join(cells) + " |")
    lines += _families(metrics, names)
    lines += _errors(results, raw)
    lines += _judge(judge)
    lines += [
        "",
        "## Notes and limitations",
        "",
        "- **Latency is not representative.** The development model runs through a local router that adds a hidden ~2.1k-token prompt to every call; the numbers are recorded for completeness only.",
        "- **Cost is an estimate, not a bill.** The eval ran through a router at no charge to us, so cost = measured tokens × the model's public list price in `models.yaml` (`gemini-3.8-flash` $1.50 / $7.50 per million input / output tokens, the Gemini API standard rate; the introductory rate until 2026-12-31 is half that. `claude-sonnet-4-6` $3 / $15, Anthropic API). Per case = total ÷ all cases; per resolution = total ÷ safe automated resolutions. It is an upper bound: the tokens include the router's hidden ~2.1k-token prompt on every call, and the runs don't record cache hits, so all input is priced uncached. B0 calls no model, so its cost is $0.",
        "- Scenarios are generated from the synthetic dataset's records with hand-written ES/PT templates; they measure behaviour on those templates, not on real customer traffic.",
        "- Grading is deterministic (outcomes, reason codes, tool calls, payments at the bank, required and forbidden text). Text checks are substring-based and can miss a correct answer phrased unexpectedly; the error analysis lists every failure so they can be reviewed.",
    ]
    return "\n".join(lines) + "\n"


def _families(metrics: dict[str, Any], names: list[str]) -> list[str]:
    lines = [
        "",
        "## By scenario family",
        "",
        "Checks passed (all repeats).",
        "",
        "| Family | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for family in sorted({f for n in names for f in metrics[n]["by_family"]}):
        lines.append(
            f"| {family} | "
            + " | ".join(
                _rate(metrics[n]["by_family"][family]["passed"])
                if family in metrics[n]["by_family"]
                else "–"
                for n in names
            )
            + " |"
        )
    return lines


def _errors(results: list[CaseResult], raw: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for system in sorted({c.system for c in results if c.system.split("@")[0] == "S"}):
        lines += _system_errors(system, results, raw)
    return lines


def _system_errors(system: str, results: list[CaseResult], raw: list[dict[str, Any]]) -> list[str]:
    lines = ["", f"## Error analysis ({system})", ""]
    failures = [c for c in results if c.system == system and not c.passed]
    if not failures:
        return lines + [f"{system} passed every case."]
    transcripts = {
        (r["result"]["system"], r["result"]["repeat"], r["result"]["scenario_id"]): r["transcript"]
        for r in raw
    }
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for c in failures:
        groups[c.family].append(c)
    counts = Counter(k for c in failures for k, v in c.checks.items() if not v)
    lines += [
        f"{len(failures)} failed cases out of {sum(c.system == system for c in results)}. Failed checks: "
        + ", ".join(f"{k} ({n})" for k, n in counts.most_common())
        + ".",
        "",
    ]
    for family, cases in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        checks = Counter(k for c in cases for k, v in c.checks.items() if not v)
        lines.append(
            f"### {family}: {len(cases)} failures ({', '.join(f'{k} ×{n}' for k, n in checks.most_common())})"
        )
        for c in cases[:2]:
            t = transcripts.get((system, c.repeat, c.scenario_id), {})
            turns = t.get("turns", [])
            lines.append(
                f"- `{c.scenario_id}` (repeat {c.repeat}), outcome `{c.outcome}`, reasons {c.reason_codes or '–'}"
                + (f", unsafe {c.unsafe}" if c.unsafe else "")
                + (f", error `{c.error}`" if c.error else "")
            )
            for turn in turns:
                reply = " ".join(turn["reply"].split())[:220]
                lines.append(f"  - customer: {turn['user'][:160]}")
                lines.append(f"  - [{turn['status']}] {reply}")
        lines.append("")
    return lines


def _judge(rows: list[dict[str, Any]] | None) -> list[str]:
    if not rows:
        return ["", "## Response quality (judge)", "", "Not run (`--judge`)."]
    systems = sorted({r["system"] for r in rows})
    lines = [
        "",
        "## Response quality (judge): unvalidated",
        "",
        f"The judge (`{rows[0]['judge_model']}`) scored each full-system variant's answers and refusals "
        "(repeat 0) on a 1–5 rubric. **It is not validated yet**: SPEC §11.4 requires agreement with "
        "≥ 30 human-labelled cases. The labelling sheet is `judge_validation.csv` in the run folder "
        "(not committed: it holds whole conversations); after the team fills the `human_*` columns, "
        "run `python -m eval.judge agreement <file>`.",
        "",
        "Mean score · scores ≤ 2 · scored/judged",
        "",
        "| Criterion | " + " | ".join(systems) + " |",
        "|---|" + "---|" * len(systems),
    ]
    for criterion in ("clarity", "tone", "language"):
        cells = []
        for system in systems:
            mine = [r for r in rows if r["system"] == system]
            values = [r["scores"][criterion] for r in mine if r.get("scores")]
            cells.append(
                f"{sum(values) / len(values):.2f} · {sum(v <= 2 for v in values)} · {len(values)}/{len(mine)}"
                if values
                else "–"
            )
        lines.append(f"| {criterion} | " + " | ".join(cells) + " |")
    return lines


def rebuild(
    run_dirs: list[Path],
    out_dir: Path,
    regrade: bool = False,
    notes: Path | None = None,
    keep: dict[str, set[int]] | None = None,
) -> Path:
    """One report from saved runs (the same split), e.g. the baselines plus a run per model.
    With `regrade`, the saved transcripts are graded again with the current grader (no model
    calls), e.g. after a grading fix. `keep` limits a system to some repeats (e.g. the only
    repeat a provider served without failing); the report says so."""
    from eval.judge import load_judge

    metas = [json.loads((d / "meta.json").read_text()) for d in run_dirs]
    if len({m["split"] for m in metas}) != 1 or len({m["scenarios"] for m in metas}) != 1:
        raise SystemExit("runs must be on the same split and scenario set")
    raw = [
        json.loads(line)
        for d in run_dirs
        for line in (d / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    names = [r["result"]["system"] for r in raw]
    if len(
        {
            (n, r["result"]["repeat"], r["result"]["scenario_id"])
            for n, r in zip(names, raw, strict=True)
        }
    ) != len(raw):
        raise SystemExit("the same system appears in more than one run")
    keep = keep or {}
    raw = [
        r
        for r in raw
        if r["result"]["system"] not in keep or r["result"]["repeat"] in keep[r["result"]["system"]]
    ]
    if regrade:
        raw = _regrade(raw, metas[0]["split"])
    results = [CaseResult(**r["result"]) for r in raw]
    judge = [row for d in run_dirs for row in load_judge(d)]
    meta = {
        "split": metas[0]["split"],
        "systems": list(dict.fromkeys(n for m in metas for n in m["systems"])),
        "repeats": max(m["repeats"] for m in metas),
        "agent_model": metas[0]["agent_model"],
        "scenarios": metas[0]["scenarios"],
        "runs": [r for m in metas for r in m["runs"]],
        "regraded": regrade,
        "kept_repeats": {k: sorted(v) for k, v in keep.items()},
        # Findings reviewed by hand (markdown), shown after the headline.
        "notes": notes.read_text(encoding="utf-8") if notes else None,
    }
    return write_report(results, out_dir, meta, raw, judge or None)


def _regrade(raw: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    from eval import scenarios as scenario_files
    from eval.grading import grade
    from eval.transcript import Transcript, TurnRecord

    cases = scenario_files.load(split)
    if split == "test":
        scenario_files.check_lock("test", cases)
    by_id = {s.id: s for s in cases}
    out = []
    for r in raw:
        t = dict(r["transcript"])
        t["turns"] = [TurnRecord(**turn) for turn in t["turns"]]
        result = grade(by_id[r["result"]["scenario_id"]], Transcript(**t), r["result"]["repeat"])
        out.append({"result": result.to_dict(), "transcript": r["transcript"]})
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild a report from saved runs.")
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--regrade", action="store_true", help="grade the transcripts again")
    parser.add_argument("--notes", type=Path, default=None, help="hand-written findings (markdown)")
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        metavar="SYSTEM=REPEATS",
        help="only these repeats of a system, e.g. S@claude-sonnet-4-6=0 (repeatable)",
    )
    args = parser.parse_args()
    keep = {
        name: {int(r) for r in reps.split(",")}
        for name, reps in (k.split("=", 1) for k in args.keep)
    }
    root = Path(__file__).resolve().parents[1]
    out = args.out or root / "eval" / "reports" / args.runs[-1].name
    print(f"report: {rebuild(args.runs, out, args.regrade, args.notes, keep)}")
