from datetime import UTC, datetime

import pytest

from ai_backend.handoff.builder import build
from ai_backend.handoff.models import Handoff
from ai_backend.handoff.store import MemoryHandoffStore, SqliteHandoffStore

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
FACTS = [
    {
        "fact": "Purchase of 912.40 USD at Cine Premium: Approved",
        "source_tool": "get_transaction",
        "record_id": "TRX-A4",
        "as_of": "2026-06-18",
    },
    {
        "fact": "Purchase of 912.40 USD at Cine Premium: Approved",
        "source_tool": "get_transaction",
        "record_id": "TRX-A4",
        "as_of": "2026-06-18",
    },  # repeated in a later step
    {
        "fact": "Cuenta Corriente •••• 2233: balance 1500.00 USD",
        "source_tool": "get_balances",
        "record_id": "PRD-ACHK",
        "as_of": "2026-06-18",
    },
]
ACTIONS = [
    {
        "action_id": "act_1",
        "method": "transfer",
        "status": "Approved",
        "verified": True,
        "transaction_id": "TRX-SIM1",
    }
]


def _build(**overrides) -> Handoff:
    base = dict(
        conversation_id="conv_1",
        customer_id="CLI-AAAA1111",
        language="es",
        reason_codes=["FRAUD_RISK"],
        verified_facts=FACTS,
        actions=ACTIONS,
        trace_id="trc_1",
        now=NOW,
        model_id="gemini-x",
    )
    base.update(overrides)
    return build(**base)


def test_code_built_handoff():
    h = _build()
    assert h.handoff_id.startswith("HND-") and h.priority == "high"
    assert h.request_summary.generated_by == "system"
    assert "flagged for fraud" in h.request_summary.text
    assert len(h.verified_facts) == 2  # repeats dropped
    assert h.evidence.transaction_ids == ["TRX-A4", "TRX-SIM1"]
    assert h.actions_taken[0].verified and h.actions_taken[0].record_id == "TRX-SIM1"
    assert h.open_questions.items == [] and h.open_questions.generated_by == "system"


def test_model_text_is_marked_as_model_generated():
    h = _build(
        reason_codes=["DELINQUENT", "DELINQUENT"],
        summary="Wants to renegotiate",
        open_questions=["How much can they pay?"],
        language="pt",
    )
    assert h.reason_codes == ["DELINQUENT"] and h.priority == "normal" and h.language == "pt"
    assert h.request_summary.generated_by == "model:gemini-x"
    assert h.open_questions.generated_by == "model:gemini-x"


def test_every_reason_has_a_system_summary():
    from ai_backend.policy.models import ReasonCode

    for code in ReasonCode:
        assert _build(reason_codes=[code.value]).request_summary.text


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return (
        MemoryHandoffStore() if request.param == "memory" else SqliteHandoffStore(tmp_path / "h.db")
    )


async def test_store_round_trip(store):
    h = _build()
    await store.save(h)
    assert await store.get(h.handoff_id) == h
    assert await store.get("HND-000000000000") is None
