"""Graph state (persisted by the checkpointer) and per-request context (never persisted)."""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langchain_core.runnables import Runnable
from langgraph.graph.message import add_messages

from ai_backend.auth.session import Session
from ai_backend.bank.client import BankClient
from ai_backend.config import ModelSpec, PolicyConfig
from ai_backend.handoff.store import HandoffStore
from ai_backend.language.detect import Lang
from ai_backend.observability.tracing import Tracer
from ai_backend.tools.definitions import ToolSpec


class AgentState(TypedDict, total=False):
    # ---- conversation (kept across turns) ----
    messages: Annotated[list[AnyMessage], add_messages]
    customer_id: str
    language: Lang
    verified_facts: Annotated[list[dict[str, Any]], operator.add]
    actions: Annotated[list[dict[str, Any]], operator.add]
    policy_decisions: Annotated[list[dict[str, Any]], operator.add]
    handoff_ids: Annotated[list[str], operator.add]
    clarifications: int
    # A payment waiting for the customer's confirmation (ARCHITECTURE §6).
    pending_action: dict[str, Any] | None

    # ---- this turn (reset by every request) ----
    confirmation: dict[str, str] | None  # {action_id, decision} from the request, if any
    next_step: str | None
    tool_steps: int
    allowed_calls: list[str] | None  # read tool-call IDs the policy gate let through
    step_policy_facts: list[dict[str, Any]] | None
    forbidden_seen: bool
    escalation: list[str] | None  # reason codes that send this turn to a human
    handoff_summary: str | None
    handoff_questions: list[str] | None
    handoff_id: str | None
    outcome: str | None
    reply: str | None
    status: str | None  # answered | awaiting_confirmation | handed_off | refused | login_required


# Per-turn fields and their reset values; the service passes them in every request.
TURN_RESET: dict[str, Any] = {
    "next_step": None,
    "tool_steps": 0,
    "allowed_calls": None,
    "step_policy_facts": None,
    "forbidden_seen": False,
    "escalation": None,
    "handoff_summary": None,
    "handoff_questions": None,
    "handoff_id": None,
    "outcome": None,
    "reply": None,
    "status": None,
}


@dataclass(frozen=True)
class AgentContext:
    """Everything a turn needs that must not be checkpointed: the session (it holds the
    customer's token), live clients, stores and the tracer."""

    session: Session
    bank: BankClient
    llm: Runnable[Any, Any]
    model_key: str
    model_spec: ModelSpec
    tools: dict[str, ToolSpec]
    policy: PolicyConfig
    tracer: Tracer
    handoffs: HandoffStore
    clock: Callable[[], datetime]
    history_end: date

    @property
    def today(self) -> date:
        return self.clock().date()
