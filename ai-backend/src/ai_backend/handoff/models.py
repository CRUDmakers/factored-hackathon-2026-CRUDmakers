"""The handoff record a human agent receives (ARCHITECTURE §10).

Built by code from the conversation state. Only `request_summary` and `open_questions` may come
from the model, and they say so in `generated_by`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneratedText(_Model):
    text: str
    generated_by: str  # "model:<id>" or "system"


class GeneratedList(_Model):
    items: list[str]
    generated_by: str


class HandoffFact(_Model):
    fact: str
    source: str
    record_id: str | None = None


class HandoffAction(_Model):
    type: str
    status: str
    verified: bool
    record_id: str | None = None


class Evidence(_Model):
    transaction_ids: list[str]
    trace_id: str


class Handoff(_Model):
    handoff_id: str = Field(pattern=r"^HND-[A-F0-9]{12}$")
    conversation_id: str
    customer_id: str
    language: Literal["es", "pt"]
    priority: Literal["high", "normal"]
    reason_codes: list[str] = Field(min_length=1)
    request_summary: GeneratedText
    verified_facts: list[HandoffFact]
    actions_taken: list[HandoffAction]
    evidence: Evidence
    open_questions: GeneratedList
    created_at: datetime
