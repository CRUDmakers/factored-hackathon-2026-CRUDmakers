"""FastAPI app. This module is the composition root: it loads config and wires the bank, the model,
the stores and the agent graph."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ai_backend import storage
from ai_backend.agent import messages as text
from ai_backend.agent.graph import build_graph
from ai_backend.agent.service import (
    ChatService,
    ConversationNotFound,
    FileNotFound,
    HandoffNotFound,
    LoginRequired,
)
from ai_backend.api.schemas import (
    ChatRequest,
    ChatResponse,
    Check,
    ErrorResponse,
    FilesRequest,
    FilesResponse,
    HealthResponse,
    LoginRequiredResponse,
    ReportCatalogItem,
    ReportCatalogResponse,
    ReportRequest,
    TraceResponse,
)
from ai_backend.bank.client import BankClient, BankError, BankRejected, BankUnavailable, NotFound
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
from ai_backend.files.models import GenerateFilesArgs
from ai_backend.files.store import FileStore, MemoryFileStore, SqliteFileStore
from ai_backend.handoff.models import Handoff
from ai_backend.handoff.store import HandoffStore, MemoryHandoffStore, SqliteHandoffStore
from ai_backend.llm.registry import ModelNotConfigured, build_chat_model
from ai_backend.observability.store import MemoryTraceStore, SqliteTraceStore, TraceStore
from ai_backend.reports.models import CATALOG, ReportArgs, ReportType, ReportUnavailable
from ai_backend.settings import Settings, get_settings
from ai_backend.storage import ConversationLock, InProcessLock
from ai_backend.tools.registry import REGISTRY, tool_schemas


@dataclass(frozen=True)
class AppState:
    settings: Settings
    models: ModelRegistry
    policy: PolicyConfig
    bank: BankClient
    service: ChatService | None  # None when the agent model has no credentials
    service_problem: str | None = None
    storage_check: Callable[[], Awaitable[None]] | None = None
    classifier_status: tuple[bool, str] = (True, "disabled")


def make_clock(settings: Settings) -> Callable[[], datetime]:
    pinned = settings.clock_override
    return (lambda: pinned) if pinned else (lambda: datetime.now(UTC))


async def build_state(
    settings: Settings,
    stack: AsyncExitStack,
    llm: BaseChatModel | None = None,
    clock: Callable[[], datetime] | None = None,
    classifier: Any | None = None,
) -> AppState:
    """Load everything the app needs. Invalid config fails here, so the app never starts broken.

    `llm`, `clock` and `classifier` replace the configured ones (tests).
    """
    models = load_model_registry(settings.models_config_path)
    policy = load_policy_config(settings.policy_config_path)
    clock = clock or make_clock(settings)

    bank: BankClient
    if settings.bank_mode == "fake":
        bank = FakeBankClient.from_dir(settings.bank_fixture_dir, clock)
    else:
        if not settings.bank_base_url:
            raise ConfigError("BANK_BASE_URL is required when BANK_MODE=http")
        http = HttpBankClient(settings.bank_base_url, policy.timeouts_seconds.bank, policy.retries)
        stack.push_async_callback(http.aclose)
        bank = http

    stores = await _storage(settings, stack)
    classifier, classifier_status = _load_classifier(settings, classifier)

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
            graph=build_graph(stores.checkpointer),
            bank=bank,
            llm=llm.bind_tools(tool_schemas()),
            model_key=settings.agent_model,
            model_spec=spec,
            tools=REGISTRY,
            policy=policy,
            conversations=stores.conversations,
            traces=stores.traces,
            handoffs=stores.handoffs,
            locks=stores.lock,
            classifier=classifier,
            clock=clock,
            history_end=settings.history_end,
            files=stores.files,
            file_ttl=timedelta(hours=settings.file_ttl_hours),
        )
    return AppState(
        settings, models, policy, bank, service, problem, stores.check, classifier_status
    )


def _load_classifier(
    settings: Settings, injected: Any | None
) -> tuple[Any | None, tuple[bool, str]]:
    if injected is not None:
        return injected, (True, "loaded (injected)")
    path = settings.classifier_path
    if path is None:
        return None, (True, "disabled: the agent routes alone")
    if not path.exists():
        return None, (False, f"not trained: run `python -m ai_backend.classifier.train` ({path})")
    from ai_backend.classifier.predict import RouteClassifier

    classifier = RouteClassifier.load(path)
    return classifier, (
        True,
        f"loaded ({classifier.meta.get('features')}, trained {classifier.meta.get('trained_at')})",
    )


@dataclass(frozen=True)
class Storage:
    checkpointer: BaseCheckpointSaver
    conversations: ConversationStore
    traces: TraceStore
    handoffs: HandoffStore
    lock: ConversationLock
    files: FileStore
    check: Callable[[], Awaitable[None]] | None = None


async def _storage(settings: Settings, stack: AsyncExitStack) -> Storage:
    url = settings.db_url
    if url == "memory://":
        return Storage(
            InMemorySaver(),
            MemoryConversationStore(),
            MemoryTraceStore(),
            MemoryHandoffStore(),
            InProcessLock(),
            MemoryFileStore(),
        )
    if url.startswith("sqlite:///"):
        path = Path(url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(str(path)))
        trace_store = SqliteTraceStore(path)
        await trace_store.purge_older_than(settings.trace_retention_days)
        file_store = SqliteFileStore(path)
        await file_store.purge_expired(datetime.now(UTC))
        return Storage(
            checkpointer,
            SqliteConversationStore(path),
            trace_store,
            SqliteHandoffStore(path),
            InProcessLock(),
            file_store,
        )
    if url.startswith(("postgresql://", "postgres://")):
        await storage.ensure_database(url)
        pool = await storage.open_pool(url)
        stack.push_async_callback(pool.close)
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        conversations = storage.PostgresConversationStore(pool)
        traces = storage.PostgresTraceStore(pool)
        handoffs = storage.PostgresHandoffStore(pool)
        files = storage.PostgresFileStore(pool)
        for store in (conversations, traces, handoffs, files):
            await store.setup()
        await traces.purge_older_than(settings.trace_retention_days)
        await files.purge_expired(datetime.now(UTC))
        return Storage(
            saver,
            conversations,
            traces,
            handoffs,
            storage.PostgresAdvisoryLock(pool),
            files,
            check=lambda: storage.ping(pool),
        )
    raise ConfigError(
        f"unsupported DB_URL {url!r} (use postgresql://…, sqlite:///<path> or memory://)"
    )


def create_app(
    settings: Settings | None = None,
    llm: BaseChatModel | None = None,
    clock: Callable[[], datetime] | None = None,
    classifier: Any | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            app.state.ai = await build_state(settings, stack, llm, clock, classifier)
            yield

    app = FastAPI(title="Banco LATAM AI backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        # The browser reads the download's name from it (GET /v1/files/{file_id}).
        expose_headers=["Content-Disposition"],
    )

    @app.get("/v1/health", response_model=HealthResponse)
    async def health(request: Request, response: Response) -> HealthResponse:
        state: AppState = request.app.state.ai
        checks = {
            "models": _check_models(state),
            "bank": await _check_bank(state),
            "storage": await _check_storage(state),
            "classifier": Check(ok=state.classifier_status[0], detail=state.classifier_status[1]),
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
        confirmation = body.confirmation.model_dump() if body.confirmation else None
        try:
            result = await state.service.turn(
                _bearer(authorization), body.message, body.conversation_id, confirmation
            )
        except LoginRequired:
            return _login_required()
        except ConversationNotFound:
            return _error(404, "conversation_not_found", "No such conversation.")
        except BankUnavailable:
            return _error(503, "bank_unavailable", "The bank could not answer right now.")
        if result.status == "login_required":
            return _login_required()
        return ChatResponse(
            conversation_id=result.conversation_id,
            turn_id=result.turn_id,
            status=result.status,
            message=result.message,
            language=result.language,
            pending_action=result.pending_action,
            handoff={"handoff_id": result.handoff_id} if result.handoff_id else None,
            files=result.files,
            trace_id=result.trace_id,
        )

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

    @app.get(
        "/v1/handoffs/{handoff_id}",
        response_model=Handoff,
        responses={401: {"model": LoginRequiredResponse}, 404: {"model": ErrorResponse}},
    )
    async def get_handoff(
        handoff_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """The handoff record, for the human-agent panel (the customer's own, until agent roles
        exist)."""
        state: AppState = request.app.state.ai
        if state.service is None:
            return _error(503, "model_unavailable", "The assistant model is not configured.")
        try:
            return await state.service.handoff(_bearer(authorization), handoff_id)
        except LoginRequired:
            return _login_required()
        except HandoffNotFound:
            return _error(404, "handoff_not_found", "No such handoff.")

    @app.post(
        "/v1/files",
        response_model=FilesResponse,
        status_code=201,
        responses={401: {"model": LoginRequiredResponse}, 404: {"model": ErrorResponse}},
    )
    async def create_files(
        body: FilesRequest, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """Build Excel/CSV files from the same JSON the assistant sends to `generate_files`."""
        state: AppState = request.app.state.ai
        if state.service is None:
            return _error(503, "model_unavailable", "The assistant model is not configured.")
        try:
            stored = await state.service.create_files(
                _bearer(authorization), GenerateFilesArgs(files=body.files), body.conversation_id
            )
        except LoginRequired:
            return _login_required()
        except ConversationNotFound:
            return _error(404, "conversation_not_found", "No such conversation.")
        return FilesResponse(files=[f.ref() for f in stored])

    @app.get("/v1/reports", response_model=ReportCatalogResponse)
    async def list_reports() -> ReportCatalogResponse:
        """The PDF reports that can be generated, with the parameters each one takes."""
        return ReportCatalogResponse(
            reports=[
                ReportCatalogItem(
                    report=r.report,
                    title=dict(r.title),
                    description=r.description,
                    parameters=list(r.parameters),
                    endpoint=f"/v1/reports/{r.report}",
                )
                for r in CATALOG
            ]
        )

    @app.post(
        "/v1/reports/{report}",
        response_model=FilesResponse,
        status_code=201,
        responses={
            401: {"model": LoginRequiredResponse},
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    async def create_report(
        report: ReportType,
        body: ReportRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Any:
        """Build a PDF report from a fixed template, the same one the assistant's
        `generate_report` tool uses; the data comes from the bank, not from the request."""
        state: AppState = request.app.state.ai
        if state.service is None:
            return _error(503, "model_unavailable", "The assistant model is not configured.")
        params = body.model_dump(exclude={"conversation_id", "language"}, exclude_none=True)
        try:
            args = ReportArgs(report=report, **params)
            stored = await state.service.create_report(
                _bearer(authorization), args, body.language, body.conversation_id
            )
        except LoginRequired:
            return _login_required()
        except ConversationNotFound:
            return _error(404, "conversation_not_found", "No such conversation.")
        except NotFound:
            return _error(404, "not_found", "No such account, card or transaction.")
        except ReportUnavailable as exc:
            return _error(422, exc.code, exc.message)
        except BankRejected as exc:
            return _error(422, exc.code, exc.message)
        except BankUnavailable:
            return _error(503, "bank_unavailable", "The bank could not answer right now.")
        except ValueError as exc:  # pydantic's ValidationError included
            return _error(422, "invalid_arguments", str(exc)[:300])
        return FilesResponse(files=[stored.ref()])

    @app.get(
        "/v1/files/{file_id}",
        response_class=Response,
        responses={401: {"model": LoginRequiredResponse}, 404: {"model": ErrorResponse}},
    )
    async def download_file(
        file_id: str, request: Request, authorization: str | None = Header(default=None)
    ) -> Any:
        """A generated file, only for its customer and until it expires."""
        state: AppState = request.app.state.ai
        if state.service is None:
            return _error(503, "model_unavailable", "The assistant model is not configured.")
        try:
            record = await state.service.file(_bearer(authorization), file_id)
        except LoginRequired:
            return _login_required()
        except FileNotFound:
            return _error(404, "file_not_found", "No such file, or it expired.")
        return Response(
            content=record.content,
            media_type=record.media_type,
            headers={
                "Content-Disposition": _attachment(record.filename),
                "Cache-Control": "private, no-store",
            },
        )

    return app


def _attachment(filename: str) -> str:
    """An ASCII fallback plus the UTF-8 name (RFC 6266), so "extracto_año.xlsx" survives."""
    fallback = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


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


async def _check_storage(state: AppState) -> Check:
    mode = state.settings.db_url.split(":", 1)[0]
    if state.storage_check is None:
        return Check(ok=True, detail=f"{mode}: local")
    try:
        await state.storage_check()
    except Exception as exc:  # any driver error means the database can't be used
        return Check(ok=False, detail=f"{mode}: {type(exc).__name__}")
    return Check(ok=True, detail=f"{mode}: reachable")


async def _check_bank(state: AppState) -> Check:
    mode = state.settings.bank_mode
    try:
        await state.bank.ping()
    except BankError as exc:
        return Check(ok=False, detail=f"{mode}: {type(exc).__name__}: {exc}")
    return Check(ok=True, detail=f"{mode}: reachable")


app = create_app()
