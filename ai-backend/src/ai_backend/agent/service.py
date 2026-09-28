"""One chat turn, end to end: authenticate, check ownership, run the graph, persist the trace.

Authentication and the ownership check run *before* the graph, so a request with a bad token or
someone else's conversation ID never loads or writes that conversation's state.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from langgraph.graph.state import CompiledStateGraph

from ai_backend.agent import messages as text
from ai_backend.agent.state import AgentContext
from ai_backend.auth.session import Session
from ai_backend.bank.client import AuthExpired, BankClient
from ai_backend.config import ModelSpec, PolicyConfig
from ai_backend.conversations.store import ConversationStore
from ai_backend.observability.store import TraceStore
from ai_backend.observability.tracing import TraceEvent, Tracer
from ai_backend.tools.definitions import ToolSpec

CONVERSATION_ID = re.compile(r"^conv_[0-9a-f]{32}$")
Status = Literal["answered", "refused", "login_required"]


class LoginRequired(Exception):
    """The token is missing, invalid, expired or revoked."""


class ConversationNotFound(Exception):
    """Unknown conversation, or one that belongs to another customer (indistinguishable)."""


@dataclass(frozen=True)
class TurnResult:
    conversation_id: str
    turn_id: str
    status: Status
    message: str
    language: str
    trace_id: str


@dataclass
class ChatService:
    graph: CompiledStateGraph
    bank: BankClient
    llm: Runnable[Any, Any]
    model_key: str
    model_spec: ModelSpec
    tools: dict[str, ToolSpec]
    policy: PolicyConfig
    conversations: ConversationStore
    traces: TraceStore
    clock: Callable[[], datetime]
    history_end: date

    async def authenticate(self, token: str | None) -> Session:
        if not token:
            raise LoginRequired()
        try:
            return await self.bank.get_session(token)
        except AuthExpired as exc:
            raise LoginRequired() from exc

    async def owned_conversation(self, session: Session, conversation_id: str) -> str:
        if not CONVERSATION_ID.match(conversation_id):
            raise ConversationNotFound()
        if await self.conversations.owner(conversation_id) != session.customer_id:
            raise ConversationNotFound()
        return conversation_id

    async def turn(
        self, token: str | None, message: str, conversation_id: str | None = None
    ) -> TurnResult:
        # Traces use real time; `self.clock` is the bank's "today" and may be pinned for eval.
        started_at, start = datetime.now(UTC), time.perf_counter()
        session = await self.authenticate(token)
        auth_ms = (time.perf_counter() - start) * 1000

        if conversation_id is None:
            conversation_id = f"conv_{uuid.uuid4().hex}"
            await self.conversations.create(conversation_id, session.customer_id)
        else:
            await self.owned_conversation(session, conversation_id)

        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        tracer = Tracer(conversation_id, turn_id)
        tracer.record("auth_guard", started_at, auth_ms, outcome="ok")
        context = AgentContext(
            session=session,
            bank=self.bank,
            llm=self.llm,
            model_key=self.model_key,
            model_spec=self.model_spec,
            tools=self.tools,
            policy=self.policy,
            tracer=tracer,
            today=self.clock().date(),
            history_end=self.history_end,
        )
        try:
            state = await self.graph.ainvoke(
                {
                    "messages": [HumanMessage(message)],
                    "customer_id": session.customer_id,
                    "tool_steps": 0,
                    "outcome": None,
                    "reply": None,
                },
                {"configurable": {"thread_id": conversation_id}},
                context=context,
            )
        finally:
            await self.traces.save(tracer.events)

        outcome = state.get("outcome") or "answered"
        status: Status = (
            "login_required"
            if outcome == "login_required"
            else "refused"
            if outcome == "refused"
            else "answered"
        )
        return TurnResult(
            conversation_id=conversation_id,
            turn_id=turn_id,
            status=status,
            message=state.get("reply") or text.message("llm_failed", state.get("language")),
            language=state.get("language", "es"),
            trace_id=tracer.trace_id,
        )

    async def trace(self, token: str | None, conversation_id: str) -> list[TraceEvent]:
        session = await self.authenticate(token)
        await self.owned_conversation(session, conversation_id)
        return await self.traces.for_conversation(conversation_id)

