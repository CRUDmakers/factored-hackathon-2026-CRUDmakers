"""Which customer owns each conversation (and, from M4, its intents for repeat contact).

A conversation ID is only usable by the customer who started it; anyone else gets a 404, the same
as for an unknown ID.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class ConversationStore(Protocol):
    async def owner(self, conversation_id: str) -> str | None: ...

    async def create(self, conversation_id: str, customer_id: str) -> None: ...


class MemoryConversationStore:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    async def owner(self, conversation_id: str) -> str | None:
        return self._owners.get(conversation_id)

    async def create(self, conversation_id: str, customer_id: str) -> None:
        self._owners.setdefault(conversation_id, customer_id)


class SqliteConversationStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        with sqlite3.connect(self._path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                " conversation_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,"
                " created_at TEXT NOT NULL)"
            )

    async def owner(self, conversation_id: str) -> str | None:
        def read() -> str | None:
            with sqlite3.connect(self._path) as db:
                row = db.execute(
                    "SELECT customer_id FROM conversations WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                return row[0] if row else None

        return await asyncio.to_thread(read)

    async def create(self, conversation_id: str, customer_id: str) -> None:
        def write() -> None:
            with sqlite3.connect(self._path) as db:
                db.execute(
                    "INSERT OR IGNORE INTO conversations VALUES (?, ?, ?)",
                    (conversation_id, customer_id, datetime.now(UTC).isoformat()),
                )

        await asyncio.to_thread(write)
