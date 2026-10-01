"""Generated-file persistence: SQLite for local runs, memory for tests (Postgres: `storage.py`).

Files hold the customer's financial data, so they expire (`FILE_TTL_HOURS`): an expired file
is never served, and expired rows are deleted at startup.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ai_backend.files.models import StoredFile

COLUMNS = (
    "file_id, customer_id, conversation_id, filename, format, media_type, size_bytes, rows,"
    " created_at, expires_at, content"
)
FIELDS = [c.strip() for c in COLUMNS.split(",")]
PLACEHOLDERS = ", ".join("?" * len(FIELDS))


class FileStore(Protocol):
    async def save(self, file: StoredFile) -> None: ...

    async def get(self, file_id: str) -> StoredFile | None: ...

    async def purge_expired(self, now: datetime) -> int: ...


class MemoryFileStore:
    def __init__(self) -> None:
        self._items: dict[str, StoredFile] = {}

    async def save(self, file: StoredFile) -> None:
        self._items[file.file_id] = file

    async def get(self, file_id: str) -> StoredFile | None:
        return self._items.get(file_id)

    async def purge_expired(self, now: datetime) -> int:
        expired = [k for k, f in self._items.items() if f.expires_at <= now]
        for key in expired:
            del self._items[key]
        return len(expired)


class SqliteFileStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS generated_files ("
                " file_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, conversation_id TEXT,"
                " filename TEXT NOT NULL, format TEXT NOT NULL, media_type TEXT NOT NULL,"
                " size_bytes INTEGER NOT NULL, rows INTEGER NOT NULL, created_at TEXT NOT NULL,"
                " expires_at TEXT NOT NULL, content BLOB NOT NULL)"
            )

    async def save(self, file: StoredFile) -> None:
        def write() -> None:
            with sqlite3.connect(self._path) as db:
                db.execute(
                    f"INSERT INTO generated_files ({COLUMNS}) VALUES ({PLACEHOLDERS})",
                    (
                        file.file_id,
                        file.customer_id,
                        file.conversation_id,
                        file.filename,
                        file.format,
                        file.media_type,
                        file.size_bytes,
                        file.rows,
                        file.created_at.isoformat(),
                        file.expires_at.isoformat(),
                        file.content,
                    ),
                )

        await asyncio.to_thread(write)

    async def get(self, file_id: str) -> StoredFile | None:
        def read() -> tuple | None:
            with sqlite3.connect(self._path) as db:
                return db.execute(
                    f"SELECT {COLUMNS} FROM generated_files WHERE file_id = ?", (file_id,)
                ).fetchone()

        row = await asyncio.to_thread(read)
        if row is None:
            return None
        return StoredFile.model_validate(dict(zip(FIELDS, row, strict=True)))

    async def purge_expired(self, now: datetime) -> int:
        def delete() -> int:
            with sqlite3.connect(self._path) as db:
                cur = db.execute(
                    "DELETE FROM generated_files WHERE expires_at <= ?", (now.isoformat(),)
                )
                return cur.rowcount

        return await asyncio.to_thread(delete)
