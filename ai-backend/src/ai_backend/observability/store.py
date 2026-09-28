"""Trace persistence: SQLite for the service, memory for tests (Postgres in M3)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from ai_backend.observability.tracing import TraceEvent


class TraceStore(Protocol):
    async def save(self, events: list[TraceEvent]) -> None: ...

    async def for_conversation(self, conversation_id: str) -> list[TraceEvent]: ...


class MemoryTraceStore:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    async def save(self, events: list[TraceEvent]) -> None:
        self._events.extend(events)

    async def for_conversation(self, conversation_id: str) -> list[TraceEvent]:
        return [e for e in self._events if e.conversation_id == conversation_id]


class SqliteTraceStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS trace_events ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " conversation_id TEXT NOT NULL, trace_id TEXT NOT NULL,"
                " started_at TEXT NOT NULL, event TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS trace_events_conversation"
                " ON trace_events (conversation_id, id)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    async def save(self, events: list[TraceEvent]) -> None:
        rows = [
            (e.conversation_id, e.trace_id, e.started_at.isoformat(), e.model_dump_json())
            for e in events
        ]

        def write() -> None:
            with self._connect() as db:
                db.executemany(
                    "INSERT INTO trace_events (conversation_id, trace_id, started_at, event)"
                    " VALUES (?, ?, ?, ?)",
                    rows,
                )

        await asyncio.to_thread(write)

    async def for_conversation(self, conversation_id: str) -> list[TraceEvent]:
        def read() -> list[str]:
            with self._connect() as db:
                cur = db.execute(
                    "SELECT event FROM trace_events WHERE conversation_id = ? ORDER BY id",
                    (conversation_id,),
                )
                return [row[0] for row in cur.fetchall()]

        return [TraceEvent.model_validate_json(e) for e in await asyncio.to_thread(read)]

    async def purge_older_than(self, days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        def delete() -> int:
            with self._connect() as db:
                return db.execute(
                    "DELETE FROM trace_events WHERE started_at < ?", (cutoff,)
                ).rowcount

        return await asyncio.to_thread(delete)
