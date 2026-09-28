"""Policy engine: one test per reason code, rule order, and 100% branch coverage (SPEC §7)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ai_backend.config import load_policy_config
from ai_backend.policy.engine import check_preview, evaluate, post_tool_checks, verify_readback
from ai_backend.policy.models import ALLOW, HIGH_PRIORITY, PolicyDecision, ReasonCode
from ai_backend.policy.rules import ToolCall, TurnFacts

CONFIG = load_policy_config(Path(__file__).parents[2] / "config" / "policy.yaml")
NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
R = ReasonCode


def facts(**overrides) -> TurnFacts:
    base = dict(
        now=NOW,
        session_expires_at=NOW + timedelta(minutes=10),
        tool_steps=0,
        clarifications=0,
        forbidden_seen=False,
    )
    base.update(overrides)
    return TurnFacts(**base)


READ = ToolCall("get_balances", {}, "read")
WRITE = ToolCall("transfer_money", {"amount": 10}, "write")


def preview(**overrides) -> PolicyDecision:
    base = dict(
        rejection_code=None, status="Approved", response_code="00",
        amount_usd=Decimal("100"), config=CONFIG,
    )
    base.update(overrides)
    return check_preview(**base)


# ---------- evaluate: one test per reason code ----------


def test_read_is_allowed():
    assert evaluate(READ, facts(), CONFIG) == ALLOW


def test_auth_expired():
    d = evaluate(READ, facts(session_expires_at=NOW), CONFIG)
    assert (d.decision, d.reason_code) == ("deny", R.AUTH_EXPIRED)


def test_tool_unknown():
    d = evaluate(ToolCall("drop_tables", {}, None), facts(), CONFIG)
    assert (d.decision, d.reason_code) == ("deny", R.TOOL_UNKNOWN)
    assert d.details == {"tool": "drop_tables"}


def test_cross_customer_stops_the_turn():
    d = evaluate(READ, facts(forbidden_seen=True), CONFIG)
    assert (d.decision, d.reason_code) == ("escalate", R.CROSS_CUSTOMER)


@pytest.mark.parametrize(
    ("overrides", "limit"),
    [({"tool_steps": 6}, "tool_steps"), ({"clarifications": 2}, "clarifications")],
)
def test_limit_reached(overrides, limit):
    d = evaluate(READ, facts(**overrides), CONFIG)
    assert (d.decision, d.reason_code, d.details) == ("escalate", R.LIMIT_REACHED, {"limit": limit})


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("unrecognized_charge", R.UNRECOGNIZED_CHARGE),
        ("debt_arrangement", R.DELINQUENT),
        ("follow_up", R.FOLLOW_UP_REQUIRED),
        ("customer_request", R.CUSTOMER_REQUEST),
        ("anything else", R.CUSTOMER_REQUEST),
        (None, R.CUSTOMER_REQUEST),
    ],
)
def test_handoff_reasons(reason, code):
    d = evaluate(ToolCall("handoff_to_human", {"reason": reason}, "escalate"), facts(), CONFIG)
    assert (d.decision, d.reason_code) == ("escalate", code)


def test_write_needs_confirmation():
    d = evaluate(WRITE, facts(), CONFIG)
    assert (d.decision, d.reason_code) == ("confirm", R.WRITE_NEEDS_CONFIRMATION)


def test_one_action_at_a_time():
    second = ToolCall("pay_bill", {}, "write", index_among_writes=1)
    d = evaluate(second, facts(), CONFIG)
    assert (d.decision, d.reason_code) == ("deny", R.ONE_ACTION_AT_A_TIME)


def test_rule_order_first_match_wins():
    # Expired session beats everything; unknown tool beats budget; budget beats a write.
    everything_wrong = facts(session_expires_at=NOW, forbidden_seen=True, tool_steps=99)
    assert evaluate(WRITE, everything_wrong, CONFIG).reason_code == R.AUTH_EXPIRED
    unknown = ToolCall("x", {}, None)
    assert evaluate(unknown, facts(tool_steps=99), CONFIG).reason_code == R.TOOL_UNKNOWN
    assert evaluate(WRITE, facts(tool_steps=99), CONFIG).reason_code == R.LIMIT_REACHED


# ---------- check_preview ----------


def test_approved_preview_needs_confirmation():
    assert preview().reason_code == R.WRITE_NEEDS_CONFIRMATION
    assert preview().decision == "confirm"


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("invalid_destination", R.INVALID_DESTINATION),
        ("country_not_supported", R.INVALID_DESTINATION),
        ("invalid_barcode", R.INVALID_DESTINATION),
        ("invalid_source_product", R.INVALID_REQUEST),
    ],
)
def test_rejected_requests(code, reason):
    d = preview(rejection_code=code, status=None, response_code=None)
    assert (d.decision, d.reason_code, d.details) == ("deny", reason, {"bank_code": code})


def test_amount_over_limit():
    d = preview(amount_usd=Decimal("5000.01"))
    assert (d.decision, d.reason_code) == ("escalate", R.AMOUNT_OVER_LIMIT)
    assert preview(amount_usd=Decimal("5000")).decision == "confirm"  # the limit itself is fine


def test_amount_without_usd_value_goes_to_a_human():
    d = preview(amount_usd=None)
    assert (d.decision, d.reason_code) == ("escalate", R.AMOUNT_OVER_LIMIT)


@pytest.mark.parametrize(
    ("code", "decision", "reason"),
    [
        ("05", "escalate", R.PRODUCT_BLOCKED),
        ("51", "deny", R.INSUFFICIENT_FUNDS),
        ("54", "deny", R.CARD_EXPIRED),
        ("14", "deny", R.INVALID_DESTINATION),
        ("99", "deny", R.INVALID_REQUEST),
    ],
)
def test_preview_declines(code, decision, reason):
    d = preview(status="Declined", response_code=code)
    assert (d.decision, d.reason_code) == (decision, reason)


def test_preview_order_rejection_then_limit_then_decline():
    assert preview(rejection_code="invalid_barcode", amount_usd=None).reason_code == (
        R.INVALID_DESTINATION
    )
    over_and_declined = preview(amount_usd=Decimal("9999"), status="Declined", response_code="51")
    assert over_and_declined.reason_code == R.AMOUNT_OVER_LIMIT


# ---------- post_tool_checks ----------


def tx_fact(**overrides) -> dict:
    base = {"kind": "transaction", "transaction_id": "TRX-1", "flagged_as_fraud": False,
            "fraud_score": None, "product_id": "PRD-1", "product_status": "Active"}
    base.update(overrides)
    return base


def test_clean_facts_escalate_nothing():
    assert post_tool_checks([tx_fact(), {"kind": "balances"}], CONFIG) == []


def test_fraud_flag():
    [d] = post_tool_checks([tx_fact(flagged_as_fraud=True)], CONFIG)
    assert (d.decision, d.reason_code, d.details) == (
        "escalate", R.FRAUD_RISK, {"transaction_id": "TRX-1"}
    )


@pytest.mark.parametrize(("score", "escalates"), [(39.99, False), (40, True), ("88.1", True)])
def test_fraud_score_threshold_from_config(score, escalates):
    assert bool(post_tool_checks([tx_fact(fraud_score=score)], CONFIG)) is escalates


@pytest.mark.parametrize("status", ["Blocked", "Suspended"])
def test_product_blocked(status):
    [d] = post_tool_checks([tx_fact(product_status=status)], CONFIG)
    assert (d.reason_code, d.details) == (R.PRODUCT_BLOCKED, {"product_id": "PRD-1"})


def test_several_escalations_are_all_reported():
    decisions = post_tool_checks(
        [tx_fact(flagged_as_fraud=True, product_status="Blocked")], CONFIG
    )
    assert [d.reason_code for d in decisions] == [R.FRAUD_RISK, R.PRODUCT_BLOCKED]


# ---------- verify_readback ----------


EXPECTED = {"payment_method": "transfer", "amount": "100.00", "currency": "USD", "product_id": "P"}


def test_matching_readback_is_verified():
    assert verify_readback(EXPECTED, dict(EXPECTED)) == ALLOW


def test_mismatched_readback_escalates():
    d = verify_readback(EXPECTED, {**EXPECTED, "amount": "1000.00", "currency": "COP"})
    assert (d.decision, d.reason_code, d.details) == (
        "escalate", R.VERIFY_MISMATCH, {"fields": ["amount", "currency"]}
    )


# ---------- models ----------


def test_message_keys_and_priorities():
    assert PolicyDecision("deny", R.CARD_EXPIRED).message_key == "card_expired"
    assert ALLOW.message_key is None
    assert R.FRAUD_RISK in HIGH_PRIORITY and R.CUSTOMER_REQUEST not in HIGH_PRIORITY
