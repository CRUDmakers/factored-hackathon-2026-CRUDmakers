"""HTTP request/response schemas (SPEC §9.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_backend.observability.tracing import TraceEvent


class Check(BaseModel):
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Check]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    conversation_id: str
    turn_id: str
    status: Literal["answered", "refused", "login_required"]
    message: str
    language: str
    trace_id: str


class LoginRequiredResponse(BaseModel):
    status: Literal["login_required"] = "login_required"
    message: str


class ErrorResponse(BaseModel):
    error: str
    message: str


class TraceResponse(BaseModel):
    conversation_id: str
    events: list[TraceEvent]
