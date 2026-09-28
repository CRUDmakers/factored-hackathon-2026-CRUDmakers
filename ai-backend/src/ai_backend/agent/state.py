"""Graph state (persisted by the checkpointer) and per-request context (never persisted)."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langchain_core.runnables import Runnable
from langgraph.graph.message import add_messages

from ai_backend.auth.session import Session
from ai_backend.bank.client import BankClient
from ai_backend.config import ModelSpec, PolicyConfig
from ai_backend.language.detect import Lang
from ai_backend.observability.tracing import Tracer
from ai_backend.tools.definitions import ToolSpec


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    customer_id: str
    language: Lang
    verified_facts: Annotated[list[dict[str, Any]], operator.add]
    # Reset by every request (the API passes them in the input):
    tool_steps: int
    outcome: str | None  # answered | refused | llm_failed | limit_reached | login_required
    reply: str | None


@dataclass(frozen=True)
class AgentContext:
    """Everything a turn needs that must not be checkpointed: the session (it holds the
    customer's token), live clients and the tracer."""

    session: Session
    bank: BankClient
    llm: Runnable[Any, Any]
    model_key: str
    model_spec: ModelSpec
    tools: dict[str, ToolSpec]
    policy: PolicyConfig
    tracer: Tracer
    today: date
    history_end: date
