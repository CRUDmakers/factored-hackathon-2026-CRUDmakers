"""One trace per turn (SPEC §12): what each node did, how long it took, and what it cost.

Events hold redacted arguments only; tokens, keys and anything outside the LLM view never
reach a trace. Every event is also emitted as a JSON log line.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger("trace")

_SECRET_KEYS = ("token", "authorization", "api_key", "apikey", "secret", "password", "key")
_MAX_TEXT = 200
_MAX_ITEMS = 5


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    conversation_id: str
    turn_id: str
    node: str
    started_at: datetime
    duration_ms: float
    model_id: str | None = None
    prompt_version: str | None = None
    tool: str | None = None
    args_redacted: dict[str, Any] | None = None
    bank_call: dict[str, Any] | None = None
    policy_decision: str | None = None
    reason_code: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    cost_usd: Decimal | None = None
    outcome: str | None = None
    error: str | None = None


class Tracer:
    def __init__(
        self,
        conversation_id: str,
        turn_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.trace_id = f"trc_{uuid.uuid4().hex}"
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self.events: list[TraceEvent] = []
        self._clock = clock

    @contextmanager
    def span(self, node: str, **fields: Any) -> Iterator[dict[str, Any]]:
        """Time a block; the caller fills the yielded dict with event fields."""
        started_at = self._clock()
        start = time.perf_counter()
        data: dict[str, Any] = dict(fields)
        try:
            yield data
        except Exception as exc:
            data.setdefault("error", f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self.record(node, started_at, (time.perf_counter() - start) * 1000, **data)

    def record(self, node: str, started_at: datetime, duration_ms: float, **fields: Any) -> None:
        event = TraceEvent(
            trace_id=self.trace_id,
            conversation_id=self.conversation_id,
            turn_id=self.turn_id,
            node=node,
            started_at=started_at,
            duration_ms=round(duration_ms, 2),
            **fields,
        )
        self.events.append(event)
        log.info("trace_event", **event.model_dump(mode="json", exclude_none=True))


def redact(args: dict[str, Any]) -> dict[str, Any]:
    """Drop anything secret-looking and cap long text and long lists."""
    return {
        key: "[redacted]" if any(s in key.lower() for s in _SECRET_KEYS) else _cap(value)
        for key, value in args.items()
    }


def _cap(value: Any) -> Any:
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, list):
        kept = [_cap(v) for v in value[:_MAX_ITEMS]]
        extra = len(value) - _MAX_ITEMS
        return kept + [f"… {extra} more"] if extra > 0 else kept
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + "…"
    return value
