"""HTTP request/response schemas (SPEC §9.2)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_backend.files.models import MAX_FILES, FileSpec
from ai_backend.observability.tracing import TraceEvent
from ai_backend.reports.models import ReportLang, ReportType


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


class FileRef(BaseModel):
    file_id: str
    filename: str
    format: Literal["xlsx", "csv", "pdf"]
    media_type: str
    size_bytes: int
    rows: int
    download_url: str  # relative to the AI backend; GET it with the same bearer token
    expires_at: str


class ChatResponse(BaseModel):
    conversation_id: str
    turn_id: str
    status: Literal["answered", "awaiting_confirmation", "handed_off", "refused"]
    message: str
    language: str
    pending_action: PendingAction | None = None
    handoff: HandoffRef | None = None
    files: list[FileRef] = Field(default_factory=list)
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


class FilesRequest(BaseModel):
    """The JSON the assistant sends to `generate_files`, posted directly (same schema)."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    files: list[FileSpec] = Field(min_length=1, max_length=MAX_FILES)


class FilesResponse(BaseModel):
    files: list[FileRef]


class ReportRequest(BaseModel):
    """`POST /v1/reports/{report}`: the `generate_report` tool's parameters, plus the language
    and an optional conversation the customer owns. Each report uses only its own parameters
    (`GET /v1/reports`)."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    language: ReportLang = "es"
    date_from: date | None = None
    date_to: date | None = None
    months: int | None = Field(default=None, ge=1, le=12)
    product_id: str | None = Field(default=None, pattern=r"^PRD-")
    transaction_id: str | None = None


class ReportCatalogItem(BaseModel):
    report: ReportType
    title: dict[str, str]
    description: str
    parameters: list[str]
    endpoint: str


class ReportCatalogResponse(BaseModel):
    reports: list[ReportCatalogItem]
