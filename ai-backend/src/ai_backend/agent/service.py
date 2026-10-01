"""One chat turn, end to end: authenticate, check ownership, run the graph, persist the trace.

Authentication and the ownership check run *before* the graph, so a request with a bad token or
someone else's conversation ID never loads or writes that conversation's state. Turns of one
conversation run one at a time, so a confirmation can't be executed twice by parallel requests.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from langgraph.graph.state import CompiledStateGraph

from ai_backend.agent.state import TURN_RESET, AgentContext
from ai_backend.auth.session import Session
from ai_backend.bank.client import AuthExpired, BankClient
from ai_backend.config import ModelSpec, PolicyConfig
from ai_backend.conversations.store import ConversationStore
from ai_backend.files import service as files_service
from ai_backend.files.models import GenerateFilesArgs, StoredFile
from ai_backend.files.store import FileStore, MemoryFileStore
from ai_backend.handoff.models import Handoff
from ai_backend.handoff.store import HandoffStore
from ai_backend.observability.store import TraceStore
from ai_backend.observability.tracing import TraceEvent, Tracer
from ai_backend.storage import ConversationLock, InProcessLock
from ai_backend.tools.definitions import ToolSpec

CONVERSATION_ID = re.compile(r"^conv_[0-9a-f]{32}$")
Status = Literal["answered", "awaiting_confirmation", "handed_off", "refused", "login_required"]
# What a button confirmation adds to the conversation (the same words work in ES and PT).
CONFIRMATION_TEXT = {"approve": "Confirmo.", "reject": "Cancelo."}


class LoginRequired(Exception):
    """The token is missing, invalid, expired or revoked."""


class ConversationNotFound(Exception):
    """Unknown conversation, or one that belongs to another customer (indistinguishable)."""


class HandoffNotFound(Exception):
    """Unknown handoff, or one that belongs to another customer (indistinguishable)."""


class FileNotFound(Exception):
    """Unknown or expired file, or one that belongs to another customer (indistinguishable)."""


@dataclass(frozen=True)
class TurnResult:
    conversation_id: str
    turn_id: str
    status: Status
    message: str
    language: str
    trace_id: str
    pending_action: dict[str, Any] | None = None
    handoff_id: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)


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
    handoffs: HandoffStore
    clock: Callable[[], datetime]
    history_end: date
    locks: ConversationLock = field(default_factory=InProcessLock)
    classifier: Any | None = None
    files: FileStore = field(default_factory=MemoryFileStore)
    file_ttl: timedelta = timedelta(hours=24)

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
        self,
        token: str | None,
        message: str | None,
        conversation_id: str | None = None,
        confirmation: dict[str, str] | None = None,
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

        async with self.locks.hold(conversation_id):
            return await self._run(
                session, conversation_id, message, confirmation, started_at, auth_ms
            )

    async def _run(
        self,
        session: Session,
        conversation_id: str,
        message: str | None,
        confirmation: dict[str, str] | None,
        started_at: datetime,
        auth_ms: float,
    ) -> TurnResult:
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
            handoffs=self.handoffs,
            clock=self.clock,
            history_end=self.history_end,
            conversations=self.conversations,
            classifier=self.classifier,
            files=self.files,
            file_ttl=self.file_ttl,
        )
        text = message or CONFIRMATION_TEXT[(confirmation or {}).get("decision", "reject")]
        try:
            state = await self.graph.ainvoke(
                {
                    "messages": [HumanMessage(text)],
                    "customer_id": session.customer_id,
                    "confirmation": confirmation,
                    **TURN_RESET,
                },
                {"configurable": {"thread_id": conversation_id}},
                context=context,
                # Every step is saved before the next runs: "executed" is on disk before the
                # bank is called, so a crash can't lead to a second payment.
                durability="sync",
            )
        finally:
            await self.traces.save(tracer.events)

        pending = (
            state.get("pending_action") if state.get("status") == "awaiting_confirmation" else None
        )
        return TurnResult(
            conversation_id=conversation_id,
            turn_id=turn_id,
            status=state.get("status") or "answered",
            message=state.get("reply") or "",
            language=state.get("language", "es"),
            trace_id=tracer.trace_id,
            pending_action=(
                {
                    "action_id": pending["action_id"],
                    "summary": pending["summary"],
                    "preview": pending["preview"],
                    "expires_at": pending["expires_at"],
                }
                if pending
                else None
            ),
            handoff_id=state.get("handoff_id"),
            files=state.get("files") or [],
        )

    async def trace(self, token: str | None, conversation_id: str) -> list[TraceEvent]:
        session = await self.authenticate(token)
        await self.owned_conversation(session, conversation_id)
        return await self.traces.for_conversation(conversation_id)

    async def handoff(self, token: str | None, handoff_id: str) -> Handoff:
        session = await self.authenticate(token)
        record = await self.handoffs.get(handoff_id)
        if record is None or record.customer_id != session.customer_id:
            raise HandoffNotFound()
        return record

    async def create_files(
        self, token: str | None, args: GenerateFilesArgs, conversation_id: str | None = None
    ) -> list[StoredFile]:
        """The same generation the `generate_files` tool runs, for a JSON posted directly."""
        session = await self.authenticate(token)
        if conversation_id is not None:
            await self.owned_conversation(session, conversation_id)
        return await files_service.generate(
            self.files,
            args,
            customer_id=session.customer_id,
            conversation_id=conversation_id,
            now=datetime.now(UTC),
            ttl=self.file_ttl,
        )

    async def file(self, token: str | None, file_id: str) -> StoredFile:
        session = await self.authenticate(token)
        record = await self.files.get(file_id)
        if (
            record is None
            or record.customer_id != session.customer_id
            or record.expires_at <= datetime.now(UTC)
        ):
            raise FileNotFound()
        return record
