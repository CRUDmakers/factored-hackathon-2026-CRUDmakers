"""HTTP request/response schemas. Chat schemas arrive in M1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Check(BaseModel):
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Check]
