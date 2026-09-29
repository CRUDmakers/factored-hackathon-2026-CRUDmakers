"""Eval scenarios (SPEC §11.1): the contract between the generator, the systems and the grader."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCENARIO_DIR = Path(__file__).parent / "scenarios"
LOCK_FILE = Path(__file__).parent / "scenarios.lock.json"

Category = Literal[
    "normal", "ambiguous", "unsupported", "human", "attack", "failure", "multilingual"
]
Outcome = Literal["answered", "refused", "handed_off", "login_required", "awaiting_confirmation"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Turn(_Model):
    user: str | None = None
    confirm: Literal["approve", "reject"] | None = None

    @model_validator(mode="after")
    def _one(self) -> Turn:
        if (self.user is None) == (self.confirm is None):
            raise ValueError("a turn is either a user message or a confirmation")
        return self


class Fault(_Model):
    method: str
    fault: Literal["timeout", "error_500", "malformed", "slow", "lost_response"]
    times: int | None = None


class Patch(_Model):
    """Change a fixture record before the run (e.g. an instruction hidden in a merchant name)."""

    transaction_id: str
    field: Literal["merchant_name", "description"]
    value: str


class ExpectedAction(_Model):
    method: Literal["transfer", "bill_payment"]
    status: Literal["Approved", "Declined"]


class Expected(_Model):
    # The final observed outcome must be one of these.
    outcome: list[Outcome]
    # When handed off: at least one of these reason codes (empty = any).
    reason_codes: list[str] = Field(default_factory=list)
    must_call: list[str] = Field(default_factory=list)  # every one of these
    must_call_any: list[str] = Field(default_factory=list)  # at least one of these
    must_not_call: list[str] = Field(default_factory=list)
    # "none": no payment may be executed; an ExpectedAction: exactly that one, verified.
    action: ExpectedAction | Literal["none"] | None = None
    # Each group: at least one alternative must appear in the answers (case/accent-insensitive).
    facts: list[list[str]] = Field(default_factory=list)
    # A clarifying question is also a pass, instead of the facts (ambiguous requests).
    accept_clarification: bool = False
    clarifying_question: bool = False  # the answer must ask a question
    # Must never appear in any answer: other customers' data, risk fields, the system prompt.
    forbidden: list[str] = Field(default_factory=list)
    # Appearing in an answer means the answer is materially wrong (e.g. the opposite status).
    contradictions: list[str] = Field(default_factory=list)
    answer_language: Literal["es", "pt"] | None = None


class Scenario(_Model):
    id: str
    split: Literal["dev", "test"]
    language: Literal["es", "pt", "en", "mixed"]
    category: Category
    family: str
    segment: str
    customer_id: str
    today: date
    session: Literal["valid", "expired", "revoked", "missing"] = "valid"
    bank_faults: list[Fault] = Field(default_factory=list)
    bank_patches: list[Patch] = Field(default_factory=list)
    turns: list[Turn] = Field(min_length=1)
    expected: Expected
    notes: str | None = None

    @property
    def in_scope(self) -> bool:
        """Cases the system should resolve by itself (the denominator of safe resolution)."""
        return self.category in ("normal", "ambiguous", "multilingual") and (
            "handed_off" not in self.expected.outcome
        )

    @property
    def needs_human(self) -> bool:
        return self.expected.outcome == ["handed_off"]


def save(scenarios: list[Scenario], root: Path = SCENARIO_DIR) -> None:
    for split in ("dev", "test"):
        (root / split).mkdir(parents=True, exist_ok=True)
        for old in (root / split).glob("*.yaml"):
            old.unlink()
    for s in scenarios:
        data = s.model_dump(mode="json", exclude_defaults=True)
        data["expected"] = s.expected.model_dump(mode="json", exclude_defaults=True)
        (root / s.split / f"{s.id}.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )


def load(split: str, root: Path = SCENARIO_DIR) -> list[Scenario]:
    files = sorted((root / split).glob("*.yaml"))
    if not files:
        raise FileNotFoundError(
            f"no scenarios in {root / split}: run `python -m eval.build_scenarios`"
        )
    return [Scenario.model_validate(yaml.safe_load(f.read_text(encoding="utf-8"))) for f in files]


def digest(scenarios: list[Scenario]) -> str:
    payload = json.dumps(
        [s.model_dump(mode="json") for s in sorted(scenarios, key=lambda s: s.id)],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def check_lock(split: str, scenarios: list[Scenario], lock: Path = LOCK_FILE) -> None:
    """The test set must be exactly the one frozen before any run."""
    if not lock.exists():
        raise RuntimeError(f"{lock} missing: build and freeze the scenarios first")
    frozen = json.loads(lock.read_text(encoding="utf-8"))[split]
    if frozen["sha256"] != digest(scenarios):
        raise RuntimeError(
            f"the {split} scenarios differ from the frozen set in {lock.name}; rebuild them "
            "with the same fixture and generator, or re-freeze (and report it)"
        )


def summary(scenarios: list[Scenario]) -> dict[str, Any]:
    from collections import Counter

    return {
        "count": len(scenarios),
        "sha256": digest(scenarios),
        "by_category": dict(sorted(Counter(s.category for s in scenarios).items())),
        "by_language": dict(sorted(Counter(s.language for s in scenarios).items())),
    }
