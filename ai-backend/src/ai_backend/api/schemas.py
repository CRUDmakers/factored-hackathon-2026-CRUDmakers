"""HTTP request/response schemas (SPEC §9.2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_backend.observability.tracing import TraceEvent


class Check(BaseModel):
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Check]


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(max_length=64)
    decision: Literal["approve", "reject"]


class ChatRequest(BaseModel):
    """A message, a confirmation of a pending payment, or both (SPEC §8.2)."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    message: str | None = Field(default=None, min_length=1, max_length=2000)
    confirmation: Confirmation | None = None

    @model_validator(mode="after")
    def _something(self) -> ChatRequest:
        if self.message is None and self.confirmation is None:
            raise ValueError("send a message, a confirmation, or both")
        return self


class PendingAction(BaseModel):
    action_id: str
    summary: str
    preview: dict[str, Any]
    expires_at: str


class HandoffRef(BaseModel):
    handoff_id: str


class ChatResponse(BaseModel):
    conversation_id: str
    turn_id: str
    status: Literal["answered", "awaiting_confirmation", "handed_off", "refused"]
    message: str
    language: str
    pending_action: PendingAction | None = None
    handoff: HandoffRef | None = None
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
