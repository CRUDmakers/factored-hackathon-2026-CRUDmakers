"""Postgres storage (Compose/deploy). Needs a server; skipped otherwise:

    TEST_POSTGRES_URL=postgresql://banking:banking@localhost:55432/banking pytest -m postgres

Each test gets its own database, created by `ensure_database` like the service does.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from ai_backend import storage
from ai_backend.api.app import create_app
from ai_backend.handoff.builder import build
from ai_backend.observability.tracing import Tracer
from tests.conftest import CUSTOMER_A, Clock
from tests.integration.test_agent import _settings
from tests.scripted_llm import ScriptedChatModel, answer, tool_call

pytestmark = pytest.mark.postgres
BASE = os.environ.get("TEST_POSTGRES_URL")


@pytest.fixture
def db_url() -> str:
    if not BASE:
        pytest.skip("set TEST_POSTGRES_URL")
    parts = urlsplit(BASE)
    return urlunsplit(parts._replace(path=f"/ai_test_{uuid.uuid4().hex[:10]}"))


async def test_database_is_created_once(db_url):
    await storage.ensure_database(db_url)
    await storage.ensure_database(db_url)  # idempotent
    pool = await storage.open_pool(db_url)
    try:
        await storage.ping(pool)
    finally:
        await pool.close()


async def test_stores_round_trip(db_url):
    await storage.ensure_database(db_url)
    pool = await storage.open_pool(db_url)
    try:
        conversations = storage.PostgresConversationStore(pool)
        traces = storage.PostgresTraceStore(pool)
        handoffs = storage.PostgresHandoffStore(pool)
        for store in (conversations, traces, handoffs):
            await store.setup()
            await store.setup()  # idempotent

        await conversations.create("conv_1", CUSTOMER_A)
        await conversations.create("conv_1", "CLI-OTHER")  # can't take it over
        assert await conversations.owner("conv_1") == CUSTOMER_A
        assert await conversations.owner("conv_2") is None

        now = datetime.now(UTC)
        await conversations.record_intent("conv_1", CUSTOMER_A, "follow_up", now)
        await conversations.record_intent("conv_1", CUSTOMER_A, "follow_up", now)  # once only
        await conversations.record_intent("conv_2", CUSTOMER_A, "follow_up", now)
        await conversations.record_intent("conv_3", "CLI-OTHER", "follow_up", now)
        await conversations.record_intent(
            "conv_4", CUSTOMER_A, "follow_up", now - timedelta(days=9)
        )
        since = now - timedelta(days=7)
        assert await conversations.count_recent(CUSTOMER_A, "follow_up", since, "conv_9") == 2
        assert await conversations.count_recent(CUSTOMER_A, "follow_up", since, "conv_1") == 1
        assert await conversations.count_recent(CUSTOMER_A, "balance", since, "conv_9") == 0

        tracer = Tracer("conv_1", "t1")
        tracer.record("agent", datetime.now(UTC), 12.5, tokens_in=10)
        tracer.record("agent", datetime.now(UTC) - timedelta(days=40), 1.0)
        await traces.save(tracer.events)
        await traces.save([])
        assert [e.tokens_in for e in await traces.for_conversation("conv_1")] == [10, None]
        assert await traces.purge_older_than(30) == 1

        h = build(
            conversation_id="conv_1",
            customer_id=CUSTOMER_A,
            language="es",
            reason_codes=["FRAUD_RISK"],
            verified_facts=[],
            actions=[],
            trace_id="trc",
            now=datetime.now(UTC),
            model_id="m",
        )
        await handoffs.save(h)
        assert await handoffs.get(h.handoff_id) == h
        assert await handoffs.get("HND-000000000000") is None
    finally:
        await pool.close()


async def test_advisory_lock_serialises_one_conversation_only(db_url):
    await storage.ensure_database(db_url)
    pool = await storage.open_pool(db_url)
    lock = storage.PostgresAdvisoryLock(pool)
    order: list[str] = []

    async def turn(conversation: str, name: str, hold: float) -> None:
        async with lock.hold(conversation):
            order.append(f"{name} in")
            await asyncio.sleep(hold)
            order.append(f"{name} out")

    try:
        await asyncio.gather(turn("conv_x", "a", 0.2), turn("conv_x", "b", 0))
        assert order in (
            ["a in", "a out", "b in", "b out"],
            ["b in", "b out", "a in", "a out"],
        )
        order.clear()
        await asyncio.gather(turn("conv_x", "a", 0.2), turn("conv_y", "c", 0))
        assert order.index("c out") < order.index("a out")  # other conversations don't wait
    finally:
        await pool.close()


def test_app_on_postgres_survives_restarts_mid_payment(db_url):
    clock = Clock()
    pay = {"source_product_id": "PRD-ACHK", "amount": 100, "to_product_id": "PRD-ACC"}

    def app(llm):
        return TestClient(create_app(_settings(db_url=db_url), llm=llm, clock=clock))

    with app(ScriptedChatModel(script=[tool_call("transfer_money", pay)])) as client:
        health = client.get("/v1/health").json()
        assert health["checks"]["storage"] == {"ok": True, "detail": "postgresql: reachable"}
        bank = client.app.state.ai.bank
        token = bank.issue_test_session(CUSTOMER_A).token.get_secret_value()
        headers = {"Authorization": f"Bearer {token}"}
        body = client.post(
            "/v1/chat",
            json={"message": "Quiero pagar 100 dólares de mi tarjeta"},
            headers=headers,
        ).json()
        assert body["status"] == "awaiting_confirmation"

    # A new process: the pending payment and the history come back from Postgres.
    with app(ScriptedChatModel(script=[answer("De nada.")])) as client:
        client.app.state.ai.bank._sessions = bank._sessions  # the fake bank's logins
        client.app.state.ai.bank._fx = bank._fx
        done = client.post(
            "/v1/chat",
            json={
                "conversation_id": body["conversation_id"],
                "confirmation": {
                    "action_id": body["pending_action"]["action_id"],
                    "decision": "approve",
                },
            },
            headers=headers,
        ).json()
        assert done["message"].startswith("Listo"), done
        events = client.get(
            f"/v1/conversations/{body['conversation_id']}/trace", headers=headers
        ).json()["events"]
        assert [e["node"] for e in events].count("auth_guard") == 2
        handoff_missing = client.get("/v1/handoffs/HND-000000000000", headers=headers)
        assert handoff_missing.status_code == 404
