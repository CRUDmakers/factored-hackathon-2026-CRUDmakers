"""FastAPI app. This module is the composition root: it loads config and wires the bank, the model,
the stores and the agent graph."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ai_backend.agent import messages as text
from ai_backend.agent.graph import build_graph
from ai_backend.agent.service import ChatService, ConversationNotFound, LoginRequired
from ai_backend.api.schemas import (
    ChatRequest,
    ChatResponse,
    Check,
    ErrorResponse,
    HealthResponse,
    LoginRequiredResponse,
    TraceResponse,
)
from ai_backend.bank.client import BankClient, BankError, BankUnavailable
from ai_backend.bank.fake_client import FakeBankClient
from ai_backend.bank.http_client import HttpBankClient
from ai_backend.config import (
    ConfigError,
    ModelRegistry,
    PolicyConfig,
    load_model_registry,
    load_policy_config,
)
from ai_backend.conversations.store import (
    ConversationStore,
    MemoryConversationStore,
    SqliteConversationStore,
)
from ai_backend.llm.registry import ModelNotConfigured, build_chat_model
from ai_backend.observability.store import MemoryTraceStore, SqliteTraceStore, TraceStore
from ai_backend.settings import Settings, get_settings
from ai_backend.tools.registry import REGISTRY, tool_schemas


@dataclass(frozen=True)
class AppState:
    settings: Settings
    models: ModelRegistry
    policy: PolicyConfig
    bank: BankClient
    service: ChatService | None  # None when the agent model has no credentials
    service_problem: str | None = None


def make_clock(settings: Settings) -> Callable[[], datetime]:
    pinned = settings.clock_override
    return (lambda: pinned) if pinned else (lambda: datetime.now(UTC))


async def build_state(
    settings: Settings, stack: AsyncExitStack, llm: BaseChatModel | None = None
) -> AppState:
    """Load everything the app needs. Invalid config fails here, so the app never starts broken.

    `llm` replaces the configured agent model (tests use a scripted one).
    """
    models = load_model_registry(settings.models_config_path)
    policy = load_policy_config(settings.policy_config_path)
    clock = make_clock(settings)

    bank: BankClient
    if settings.bank_mode == "fake":
        bank = FakeBankClient.from_dir(settings.bank_fixture_dir, clock)
    else:
        if not settings.bank_base_url:
            raise ConfigError("BANK_BASE_URL is required when BANK_MODE=http")
        http = HttpBankClient(settings.bank_base_url, policy.timeouts_seconds.bank, policy.retries)
        stack.push_async_callback(http.aclose)
        bank = http

    checkpointer, conversations, traces = await _storage(settings, stack)

    spec = models.get(settings.agent_model)
    problem = None
    if llm is None:
        http_client = httpx.AsyncClient(timeout=policy.timeouts_seconds.llm)
        stack.push_async_callback(http_client.aclose)
        try:
            llm = build_chat_model(
                spec, settings, policy.timeouts_seconds.llm, policy.retries.max, http_client
            )
        except ModelNotConfigured as exc:
            problem = f"{settings.agent_model}: {exc}"

    service = None
    if llm is not None:
        service = ChatService(
            graph=build_graph(checkpointer),
            bank=bank,
            llm=llm.bind_tools(tool_schemas()),
            model_key=settings.agent_model,
            model_spec=spec,
            tools=REGISTRY,
            policy=policy,
            conversations=conversations,
            traces=traces,
            clock=clock,
            history_end=settings.history_end,
        )
    return AppState(settings, models, policy, bank, service, problem)


async def _storage(
    settings: Settings, stack: AsyncExitStack
) -> tuple[BaseCheckpointSaver, ConversationStore, TraceStore]:
    url = settings.db_url
    if url == "memory://":
        return InMemorySaver(), MemoryConversationStore(), MemoryTraceStore()
    if url.startswith("sqlite:///"):
        path = Path(url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(str(path)))
        trace_store = SqliteTraceStore(path)
        await trace_store.purge_older_than(settings.trace_retention_days)
        return checkpointer, SqliteConversationStore(path), trace_store
    raise ConfigError(f"unsupported DB_URL {url!r} (use sqlite:///<path> or memory://)")


def create_app(settings: Settings | None = None, llm: BaseChatModel | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            app.state.ai = await build_state(settings, stack, llm)
            yield

    app = FastAPI(title="Banco LATAM AI backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/v1/health", response_model=HealthResponse)
    async def health(request: Request, response: Response) -> HealthResponse:
        state: AppState = request.app.state.ai
        checks = {
            "models": _check_models(state),
            "bank": await _check_bank(state),
        }
        ok = all(c.ok for c in checks.values())
        if not ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="ok" if ok else "degraded", checks=checks)

    @app.post(
        "/v1/chat",
        response_model=ChatResponse,
        responses={401: {"model": LoginRequiredResponse}, 404: {"model": ErrorResponse}},
    )
    async def chat(
        body: ChatRequest, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        state: AppState = request.app.state.ai
        if state.service is None:
            return _error(503, "model_unavailable", "The assistant model is not configured.")
        try:
            result = await state.service.turn(
                _bearer(authorization), body.message, body.conversation_id
            )
        except LoginRequired:
            return _login_required()
        except ConversationNotFound:
            return _error(404, "conversation_not_found", "No such conversation.")
        except BankUnavailable:
            return _error(503, "bank_unavailable", "The bank could not answer right now.")
        if result.status == "login_required":
            return _login_required()
        return ChatResponse(**result.__dict__)

    @app.get(
        "/v1/conversations/{conversation_id}/trace",
        response_model=TraceResponse,
        responses={401: {"model": LoginRequiredResponse}, 404: {"model": ErrorResponse}},
    )
    async def trace(
        conversation_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        state: AppState = request.app.state.ai
        if state.service is None:
            return _error(503, "model_unavailable", "The assistant model is not configured.")
        try:
            events = await state.service.trace(_bearer(authorization), conversation_id)
        except LoginRequired:
            return _login_required()
        except ConversationNotFound:
            return _error(404, "conversation_not_found", "No such conversation.")
        return TraceResponse(conversation_id=conversation_id, events=events)

    return app


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def _login_required() -> JSONResponse:
    body = LoginRequiredResponse(message=text.LOGIN_REQUIRED)
    return JSONResponse(status_code=401, content=body.model_dump())


def _error(code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": error, "message": message})


def _check_models(state: AppState) -> Check:
    s = state.settings
    try:
        agent = state.models.get(s.agent_model)
        judge = state.models.get(s.judge_model)
    except ConfigError as exc:
        return Check(ok=False, detail=str(exc))
    if s.agent_model == s.judge_model:
        return Check(ok=False, detail="the judge must be a different model from the agent")
    for key, spec in ((s.agent_model, agent), (s.judge_model, judge)):
        if missing := _missing_credentials(s, spec.provider):
            return Check(ok=False, detail=f"{key} ({spec.provider}): {missing} is not set")
    return Check(ok=True, detail=f"agent={s.agent_model} ({agent.provider}), judge={s.judge_model}")


def _missing_credentials(s: Settings, provider: str) -> str | None:
    """Names of the settings a provider needs that are empty (values are never reported)."""
    if provider == "anthropic":
        needed = {"ANTHROPIC_API_KEY": s.anthropic_api_key}
    else:
        needed = {
            "OPENAI_COMPAT_BASE_URL": s.openai_compat_base_url,
            "OPENAI_COMPAT_API_KEY": s.openai_compat_api_key,
        }
    missing = [name for name, value in needed.items() if not value]
    return ", ".join(missing) or None


async def _check_bank(state: AppState) -> Check:
    mode = state.settings.bank_mode
    try:
        await state.bank.ping()
    except BankError as exc:
        return Check(ok=False, detail=f"{mode}: {type(exc).__name__}: {exc}")
    return Check(ok=True, detail=f"{mode}: reachable")


app = create_app()
