"""Handoff persistence: SQLite for the service, memory for tests."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Protocol

from ai_backend.handoff.models import Handoff


class HandoffStore(Protocol):
    async def save(self, handoff: Handoff) -> None: ...

    async def get(self, handoff_id: str) -> Handoff | None: ...


class MemoryHandoffStore:
    def __init__(self) -> None:
        self._items: dict[str, Handoff] = {}

    async def save(self, handoff: Handoff) -> None:
        self._items[handoff.handoff_id] = handoff

    async def get(self, handoff_id: str) -> Handoff | None:
        return self._items.get(handoff_id)

    def all(self) -> list[Handoff]:
        return list(self._items.values())


class SqliteHandoffStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS handoffs ("
                " handoff_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,"
                " customer_id TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL)"
            )

    async def save(self, handoff: Handoff) -> None:
        def write() -> None:
            with sqlite3.connect(self._path) as db:
                db.execute(
                    "INSERT INTO handoffs VALUES (?, ?, ?, ?, ?)",
                    (
                        handoff.handoff_id,
                        handoff.conversation_id,
                        handoff.customer_id,
                        handoff.created_at.isoformat(),
                        handoff.model_dump_json(),
                    ),
                )

        await asyncio.to_thread(write)

    async def get(self, handoff_id: str) -> Handoff | None:
        def read() -> str | None:
            with sqlite3.connect(self._path) as db:
                row = db.execute(
                    "SELECT body FROM handoffs WHERE handoff_id = ?", (handoff_id,)
                ).fetchone()
                return row[0] if row else None

        body = await asyncio.to_thread(read)
        return Handoff.model_validate_json(body) if body else None
