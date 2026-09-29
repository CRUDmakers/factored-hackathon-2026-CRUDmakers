"""Which customer owns each conversation, and which intents each conversation was about
(for the repeat-contact check).

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

    async def record_intent(
        self, conversation_id: str, customer_id: str, intent: str, at: datetime
    ) -> None:
        """Once per conversation and intent (the first time it comes up)."""
        ...

    async def count_recent(
        self, customer_id: str, intent: str, since: datetime, exclude_conversation: str
    ) -> int:
        """Other conversations of this customer about `intent` since `since`."""
        ...


class MemoryConversationStore:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}
        self._intents: dict[tuple[str, str], tuple[str, datetime]] = {}

    async def owner(self, conversation_id: str) -> str | None:
        return self._owners.get(conversation_id)

    async def create(self, conversation_id: str, customer_id: str) -> None:
        self._owners.setdefault(conversation_id, customer_id)

    async def record_intent(
        self, conversation_id: str, customer_id: str, intent: str, at: datetime
    ) -> None:
        self._intents.setdefault((conversation_id, intent), (customer_id, at))

    async def count_recent(
        self, customer_id: str, intent: str, since: datetime, exclude_conversation: str
    ) -> int:
        return sum(
            1
            for (conversation, kind), (customer, at) in self._intents.items()
            if kind == intent
            and customer == customer_id
            and at >= since
            and conversation != exclude_conversation
        )


class SqliteConversationStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        with sqlite3.connect(self._path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                " conversation_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,"
                " created_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS conversation_intents ("
                " conversation_id TEXT NOT NULL, customer_id TEXT NOT NULL, intent TEXT NOT NULL,"
                " at TEXT NOT NULL, PRIMARY KEY (conversation_id, intent))"
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

    async def record_intent(
        self, conversation_id: str, customer_id: str, intent: str, at: datetime
    ) -> None:
        def write() -> None:
            with sqlite3.connect(self._path) as db:
                db.execute(
                    "INSERT OR IGNORE INTO conversation_intents VALUES (?, ?, ?, ?)",
                    (conversation_id, customer_id, intent, at.isoformat()),
                )

        await asyncio.to_thread(write)

    async def count_recent(
        self, customer_id: str, intent: str, since: datetime, exclude_conversation: str
    ) -> int:
        def read() -> int:
            with sqlite3.connect(self._path) as db:
                row = db.execute(
                    "SELECT COUNT(*) FROM conversation_intents WHERE customer_id = ?"
                    " AND intent = ? AND at >= ? AND conversation_id != ?",
                    (customer_id, intent, since.isoformat(), exclude_conversation),
                ).fetchone()
                return int(row[0])

        return await asyncio.to_thread(read)
