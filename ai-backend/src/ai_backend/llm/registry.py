"""Build chat models from `models.yaml` (SPEC §2, ADR-001). Only this module and `agent/` touch
LangChain."""

from __future__ import annotations

import httpx
from langchain_core.language_models import BaseChatModel

from ai_backend.config import ModelSpec
from ai_backend.settings import Settings


class ModelNotConfigured(Exception):
    """The selected model's provider has no credentials."""


def build_chat_model(
    spec: ModelSpec,
    settings: Settings,
    timeout_seconds: float,
    max_retries: int,
    http_client: httpx.AsyncClient | None = None,
) -> BaseChatModel:
    """`http_client` lets the app own the connection pool (and close it on shutdown), instead of
    the process-wide client langchain-openai caches, which is bound to the first event loop."""
    params = dict(spec.params)
    if spec.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if settings.anthropic_api_key is None:
            raise ModelNotConfigured("ANTHROPIC_API_KEY is not set")
        return ChatAnthropic(
            model=spec.model,
            api_key=settings.anthropic_api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
            **params,
        )

    from langchain_openai import ChatOpenAI

    if not settings.openai_compat_base_url or settings.openai_compat_api_key is None:
        raise ModelNotConfigured("OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_API_KEY are not set")
    return ChatOpenAI(
        model=spec.model,
        base_url=settings.openai_compat_base_url,
        api_key=settings.openai_compat_api_key,
        timeout=timeout_seconds,
        max_retries=max_retries,
        streaming=False,
        http_async_client=http_client,
        **params,
    )
