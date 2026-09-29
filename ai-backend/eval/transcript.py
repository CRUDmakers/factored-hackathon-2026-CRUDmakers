"""What a system did in one case: framework-free, shared by the systems and the grader."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnRecord:
    user: str
    status: str
    reply: str
    latency_ms: float
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Transcript:
    scenario_id: str
    system: str
    turns: list[TurnRecord] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    # Payments recorded by the bank: {"method", "status", "turn"} (turn = 0-based index)
    payments: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
