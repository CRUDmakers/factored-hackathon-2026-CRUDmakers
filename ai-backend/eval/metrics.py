"""Evaluation metrics (SPEC §11.3). Pure functions over graded cases; every rate carries its
numerator and denominator."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from eval.grading import CaseResult


def ratio(hits: int, total: int) -> dict[str, Any]:
    return {"hits": hits, "of": total, "rate": round(hits / total, 4) if total else None}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def summarise(cases: list[CaseResult]) -> dict[str, Any]:
    """All §11.3 metrics for one set of cases (one system, one or more repeats)."""
    in_scope = [c for c in cases if c.in_scope]
    human = [c for c in cases if c.needs_human]
    not_human = [c for c in cases if not c.needs_human]
    unsafe = [c for c in cases if c.unsafe]
    kinds: dict[str, int] = defaultdict(int)
    for c in unsafe:
        for kind in c.unsafe:
            kinds[kind] += 1
    latencies = [c.latency_ms for c in cases if c.latency_ms]
    tokens = [c.tokens_in + c.tokens_out for c in cases]
    resolved = [c for c in in_scope if c.passed and not c.handed_off and not c.unsafe]
    return {
        "cases": len(cases),
        "passed": ratio(sum(c.passed for c in cases), len(cases)),
        "safe_automated_resolution": ratio(len(resolved), len(in_scope)),
        "automation_attempted": ratio(sum(not c.handed_off for c in in_scope), len(in_scope)),
        "containment": ratio(sum(not c.handed_off for c in cases), len(cases)),
        "missed_handoffs": ratio(sum(not c.handed_off for c in human), len(human)),
        "unnecessary_handoffs": ratio(sum(c.handed_off for c in not_human), len(not_human)),
        "handoff_reason_ok": ratio(
            sum(c.checks.get("reason_codes", True) for c in human if c.handed_off),
            sum(c.handed_off for c in human),
        ),
        "unsafe": ratio(len(unsafe), len(cases)),
        # The model provider failed and the case was handed off (the safe fallback): an
        # infrastructure problem, reported apart so it isn't read as the model's behaviour.
        "provider_failures": ratio(
            sum("ASSISTANT_FAILURE" in c.reason_codes for c in cases), len(cases)
        ),
        "unsafe_by_kind": dict(sorted(kinds.items())),
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95)},
        "tokens_per_case": round(statistics.mean(tokens), 1) if tokens else None,
        # No price for the development models (models.yaml price_per_mtok: null).
        "cost_per_case_usd": None,
        "cost_per_resolution_usd": None,
    }


def by(
    cases: Iterable[CaseResult], key: Callable[[CaseResult], str]
) -> dict[str, list[CaseResult]]:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for c in cases:
        groups[key(c)].append(c)
    return dict(sorted(groups.items()))


def across_repeats(cases: list[CaseResult], metric: str) -> dict[str, float | None]:
    """Mean and standard deviation of a rate over the repeats."""
    rates = [
        summarise(group)[metric]["rate"] for group in by(cases, lambda c: str(c.repeat)).values()
    ]
    rates = [r for r in rates if r is not None]
    if not rates:
        return {"mean": None, "std": None, "runs": 0}
    return {
        "mean": round(statistics.mean(rates), 4),
        "std": round(statistics.stdev(rates), 4) if len(rates) > 1 else 0.0,
        "runs": len(rates),
    }


def breakdown(cases: list[CaseResult], field: str) -> dict[str, dict[str, Any]]:
    return {
        value: {
            "cases": len(group),
            "passed": ratio(sum(c.passed for c in group), len(group)),
            "safe_automated_resolution": summarise(group)["safe_automated_resolution"],
            "unsafe": ratio(sum(bool(c.unsafe) for c in group), len(group)),
        }
        for value, group in by(cases, lambda c: getattr(c, field)).items()
    }
