"""FastAPI app. This module is the composition root: it loads config and builds the bank client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from ai_backend.api.schemas import Check, HealthResponse
from ai_backend.bank.client import BankClient, BankError
from ai_backend.bank.fake_client import FakeBankClient
from ai_backend.bank.http_client import HttpBankClient
from ai_backend.config import (
    ConfigError,
    ModelRegistry,
    PolicyConfig,
    load_model_registry,
    load_policy_config,
)
from ai_backend.settings import Settings, get_settings


@dataclass(frozen=True)
class AppState:
    settings: Settings
    models: ModelRegistry
    policy: PolicyConfig
    bank: BankClient


def build_state(settings: Settings) -> AppState:
    """Load everything the app needs. Invalid config fails here, so the app never starts broken."""
    models = load_model_registry(settings.models_config_path)
    policy = load_policy_config(settings.policy_config_path)
    bank: BankClient
    if settings.bank_mode == "fake":
        bank = FakeBankClient.from_dir(settings.bank_fixture_dir)
    else:
        if not settings.bank_base_url:
            raise ConfigError("BANK_BASE_URL is required when BANK_MODE=http")
        bank = HttpBankClient(settings.bank_base_url, policy.timeouts_seconds.bank, policy.retries)
    return AppState(settings=settings, models=models, policy=policy, bank=bank)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = build_state(settings)
        app.state.ai = state
        try:
            yield
        finally:
            if isinstance(state.bank, HttpBankClient):
                await state.bank.aclose()

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

    return app


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
