"""Storage wiring: the database, the per-conversation lock, and the Postgres stores.

- `memory://`        tests: in-memory checkpointer and stores, in-process lock
- `sqlite:///<path>` local runs: one SQLite file, in-process lock (one server process)
- `postgresql://…`   Compose/deploy: one pool shared by the LangGraph checkpointer and the
                     stores, and an advisory lock so a conversation runs one turn at a time
                     even across several servers
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ai_backend.handoff.models import Handoff
from ai_backend.observability.tracing import TraceEvent

# ---------- the per-conversation lock ----------


class ConversationLock(Protocol):
    def hold(self, conversation_id: str) -> AsyncIterator[None]: ...


class InProcessLock:
    """Enough for one server process (memory and SQLite modes)."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @asynccontextmanager
    async def hold(self, conversation_id: str) -> AsyncIterator[None]:
        async with self._locks[conversation_id]:
            yield


class PostgresAdvisoryLock:
    """A session-level advisory lock on a dedicated connection, held for the whole turn."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def hold(self, conversation_id: str) -> AsyncIterator[None]:
        async with self._pool.connection() as conn:
            await conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (conversation_id,))
            try:
                yield
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (conversation_id,))


# ---------- the database ----------


async def ensure_database(url: str) -> None:
    """Create the database in `url` if it doesn't exist.

    Postgres init scripts only run when a volume is first created, so a teammate's existing
    `pgdata` would never get the AI backend's database; creating it here works for both.
    """
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    maintenance = urlunsplit(parts._replace(path="/postgres"))
    async with await psycopg.AsyncConnection.connect(maintenance, autocommit=True) as conn:
        cur = await conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if await cur.fetchone() is None:
            await conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


async def open_pool(url: str) -> AsyncConnectionPool:
    # These connection settings are what LangGraph's Postgres checkpointer requires.
    pool = AsyncConnectionPool(
        url,
        open=False,
        min_size=1,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=10)
    return pool


async def ping(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")


# ---------- stores ----------


class PostgresConversationStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                " conversation_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS conversation_intents ("
                " conversation_id TEXT NOT NULL, customer_id TEXT NOT NULL, intent TEXT NOT NULL,"
                " at TIMESTAMPTZ NOT NULL, PRIMARY KEY (conversation_id, intent))"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS conversation_intents_customer"
                " ON conversation_intents (customer_id, intent, at)"
            )

    async def owner(self, conversation_id: str) -> str | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT customer_id FROM conversations WHERE conversation_id = %s",
                (conversation_id,),
            )
            row = await cur.fetchone()
        return row["customer_id"] if row else None

    async def create(self, conversation_id: str, customer_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO conversations (conversation_id, customer_id) VALUES (%s, %s)"
                " ON CONFLICT (conversation_id) DO NOTHING",
                (conversation_id, customer_id),
            )


    async def record_intent(
        self, conversation_id: str, customer_id: str, intent: str, at: datetime
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO conversation_intents VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (conversation_id, intent) DO NOTHING",
                (conversation_id, customer_id, intent, at),
            )

    async def count_recent(
        self, customer_id: str, intent: str, since: datetime, exclude_conversation: str
    ) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_intents WHERE customer_id = %s"
                " AND intent = %s AND at >= %s AND conversation_id != %s",
                (customer_id, intent, since, exclude_conversation),
            )
            row = await cur.fetchone()
        return int(row["n"]) if row else 0


class PostgresTraceStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS trace_events ("
                " id BIGSERIAL PRIMARY KEY, conversation_id TEXT NOT NULL,"
                " trace_id TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL, event JSONB NOT NULL)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS trace_events_conversation"
                " ON trace_events (conversation_id, id)"
            )

    async def save(self, events: list[TraceEvent]) -> None:
        if not events:
            return
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO trace_events (conversation_id, trace_id, started_at, event)"
                " VALUES (%s, %s, %s, %s::jsonb)",
                [
                    (e.conversation_id, e.trace_id, e.started_at, e.model_dump_json())
                    for e in events
                ],
            )

    async def for_conversation(self, conversation_id: str) -> list[TraceEvent]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT event FROM trace_events WHERE conversation_id = %s ORDER BY id",
                (conversation_id,),
            )
            rows = await cur.fetchall()
        return [TraceEvent.model_validate(row["event"]) for row in rows]

    async def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM trace_events WHERE started_at < %s", (cutoff,))
            return cur.rowcount


class PostgresHandoffStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS handoffs ("
                " handoff_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,"
                " customer_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, body JSONB NOT NULL)"
            )

    async def save(self, handoff: Handoff) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO handoffs VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    handoff.handoff_id,
                    handoff.conversation_id,
                    handoff.customer_id,
                    handoff.created_at,
                    handoff.model_dump_json(),
                ),
            )

    async def get(self, handoff_id: str) -> Handoff | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT body FROM handoffs WHERE handoff_id = %s", (handoff_id,)
            )
            row = await cur.fetchone()
        if row is None:
            return None
        body = row["body"]
        return Handoff.model_validate(json.loads(body) if isinstance(body, str) else body)
