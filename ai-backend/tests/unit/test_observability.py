from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ai_backend.config import ModelSpec, Price
from ai_backend.conversations.store import MemoryConversationStore, SqliteConversationStore
from ai_backend.llm.pricing import cost_usd
from ai_backend.observability.store import MemoryTraceStore, SqliteTraceStore
from ai_backend.observability.tracing import Tracer, redact

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


def test_redact_removes_secrets_and_caps_text():
    out = redact(
        {
            "merchant": "Uber",
            "api_key": "sk-1",
            "nested": {"token": "t", "ok": 1},
            "note": "x" * 300,
        }
    )
    assert out["merchant"] == "Uber" and out["api_key"] == "[redacted]"
    assert out["nested"] == {"token": "[redacted]", "ok": 1}
    assert len(out["note"]) == 201


def test_span_records_duration_fields_and_errors():
    tracer = Tracer("conv_1", "turn_1", lambda: NOW)
    with tracer.span("tool", tool="get_balances") as event:
        event["outcome"] = "ok"
    with pytest.raises(RuntimeError), tracer.span("agent"):
        raise RuntimeError("boom")
    ok, failed = tracer.events
    assert ok.tool == "get_balances" and ok.outcome == "ok" and ok.duration_ms >= 0
    assert failed.error == "RuntimeError: boom"
    assert {e.trace_id for e in tracer.events} == {tracer.trace_id}


@pytest.fixture(params=["memory", "sqlite"])
def trace_store(request, tmp_path):
    return MemoryTraceStore() if request.param == "memory" else SqliteTraceStore(tmp_path / "t.db")


async def test_trace_store_round_trip(trace_store):
    a, b = Tracer("conv_a", "t1", lambda: NOW), Tracer("conv_b", "t1", lambda: NOW)
    a.record("agent", NOW, 12.5, tokens_in=10, cost_usd=Decimal("0.001"))
    b.record("agent", NOW, 1.0)
    await trace_store.save(a.events + b.events)
    [event] = await trace_store.for_conversation("conv_a")
    assert event.tokens_in == 10 and event.cost_usd == Decimal("0.001")


async def test_old_traces_are_purged(tmp_path):
    store = SqliteTraceStore(tmp_path / "t.db")
    old, new = Tracer("c", "t", lambda: NOW), Tracer("c", "t", lambda: NOW)
    old.record("agent", datetime.now(UTC) - timedelta(days=40), 1)
    new.record("agent", datetime.now(UTC), 1)
    await store.save(old.events + new.events)
    assert await store.purge_older_than(30) == 1
    assert len(await store.for_conversation("c")) == 1


@pytest.fixture(params=["memory", "sqlite"])
def conversations(request, tmp_path):
    if request.param == "memory":
        return MemoryConversationStore()
    return SqliteConversationStore(tmp_path / "c.db")


async def test_conversation_owner_is_fixed_at_creation(conversations):
    await conversations.create("conv_1", "CLI-A")
    await conversations.create("conv_1", "CLI-B")  # can't take it over
    assert await conversations.owner("conv_1") == "CLI-A"
    assert await conversations.owner("conv_2") is None


def test_cost_uses_prices_and_cache_rate():
    spec = ModelSpec(
        provider="anthropic", model="m",
        price_per_mtok=Price(input=Decimal("3"), output=Decimal("15"), cache_read=Decimal("0.3")),
    )
    # 1000 uncached in, 1000 cached in, 500 out
    assert cost_usd(spec, 2000, 500, 1000) == Decimal("0.010800")


def test_unknown_price_is_none_not_zero():
    spec = ModelSpec(provider="openai_compatible", model="m")
    assert cost_usd(spec, 1000, 100) is None


async def test_conversation_intents_for_repeat_contact(conversations):
    now = datetime(2026, 6, 18, 12, tzinfo=UTC)
    await conversations.record_intent("c1", "CLI-A", "follow_up", now)
    await conversations.record_intent("c1", "CLI-A", "follow_up", now)  # once per conversation
    await conversations.record_intent("c2", "CLI-A", "follow_up", now - timedelta(days=1))
    await conversations.record_intent("c3", "CLI-B", "follow_up", now)
    await conversations.record_intent("c4", "CLI-A", "follow_up", now - timedelta(days=9))
    since = now - timedelta(days=7)
    assert await conversations.count_recent("CLI-A", "follow_up", since, "c9") == 2
    assert await conversations.count_recent("CLI-A", "follow_up", since, "c1") == 1
    assert await conversations.count_recent("CLI-A", "balance", since, "c9") == 0
