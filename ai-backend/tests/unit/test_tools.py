from datetime import date
from decimal import Decimal

import pytest

from ai_backend.bank.client import AuthExpired
from ai_backend.tools import definitions as d
from ai_backend.tools.registry import REGISTRY, get_tool, parameters_schema, tool_schemas
from tests.conftest import NOW


@pytest.fixture
def ctx(bank, session_a):
    return d.ToolContext(bank=bank, session=session_a, today=NOW.date())


async def run(ctx, name, **args):
    return await get_tool(name).run(ctx, args)


# ---------- schemas ----------


def test_every_p0_tool_is_registered():
    kinds = {name: t.kind for name, t in REGISTRY.items()}
    assert kinds == {
        "get_balances": "read", "search_transactions": "read", "get_transaction": "read",
        "convert_currency": "read", "transfer_money": "write", "pay_bill": "write",
        "handoff_to_human": "escalate", "generate_files": "read",
        "get_recurring_payments": "read", "pay_recurring_payments": "write",
        "get_spending_summary": "read", "generate_report": "read",
    }


def _objects(schema):
    yield schema
    for prop in schema.get("properties", {}).values():
        if prop.get("type") == "object":
            yield from _objects(prop)


def test_schemas_are_strict_and_simple():
    for tool in tool_schemas():
        params = tool["function"]["parameters"]
        text = str(params)
        assert "anyOf" not in text and "$ref" not in text
        for obj in _objects(params):
            assert obj["additionalProperties"] is False
            assert not any("customer" in name for name in obj["properties"])  # no identity


def test_nested_beneficiary_is_inlined():
    beneficiary = parameters_schema(get_tool("transfer_money"))["properties"]["beneficiary"]
    assert beneficiary["type"] == "object"
    assert beneficiary["required"] == ["name", "account_number", "country"]


def test_money_is_a_number_and_date_keeps_its_public_name():
    props = parameters_schema(get_tool("convert_currency"))["properties"]
    assert props["amount"] == {"type": "number"}
    assert props["date"]["format"] == "date"


# ---------- get_balances ----------


async def test_get_balances_masks_numbers_and_records_facts(ctx):
    r = await run(ctx, "get_balances")
    assert r.ok
    numbers = [a["product_number"] for a in r.data["accounts"]]
    assert "•••• 2233" in numbers and "1111222233" not in str(r.data)
    assert any("Tarjeta Crédito" in f.fact and "available 3799.50" in f.fact for f in r.facts)


async def test_get_balances_ignores_a_placeholder_argument(ctx):
    # A gateway added {"reason": …} to the empty schema; rejecting it broke every balance lookup.
    r = await run(ctx, "get_balances", reason="El cliente quiere saber su saldo")
    assert r.ok


# ---------- search_transactions ----------


async def test_a_narrow_search_is_checked_like_a_single_transaction(ctx):
    # A question about one charge answered from a search must still reach the fraud check.
    narrow = await run(ctx, "search_transactions", merchant="Cine")
    assert [f["transaction_id"] for f in narrow.policy_facts] == ["TRX-A4"]
    assert narrow.policy_facts[0]["flagged_as_fraud"] is True
    assert "flagged_as_fraud" not in str(narrow.data)
    # A plain listing, or a filter that matches many rows, is not about one charge.
    assert (await run(ctx, "search_transactions", limit=3)).policy_facts == []
    assert (await run(ctx, "search_transactions", date_from="2026-06-01")).policy_facts == []


async def test_search_uses_node_filters(ctx):
    r = await run(ctx, "search_transactions", status="Declined")
    assert {t["transaction_id"] for t in r.data["transactions"]} == {"TRX-A2", "TRX-A5"}
    assert r.data["total_matching"] == 2


async def test_search_by_merchant_is_filtered_locally(ctx):
    r = await run(ctx, "search_transactions", merchant="uber")
    assert [t["transaction_id"] for t in r.data["transactions"]] == ["TRX-A2", "TRX-A1"]
    assert [f.record_id for f in r.facts] == ["TRX-A2", "TRX-A1"]
    assert "Declined" in r.facts[0].fact and "Uber" in r.facts[0].fact


async def test_search_by_amount_and_limit(ctx):
    r = await run(ctx, "search_transactions", min_amount=100, max_amount=300, limit=1)
    assert r.data["returned"] == 1 and r.data["total_matching"] == 3  # 120, 200, 300


async def test_response_codes_only_for_declined(ctx, bank, session_b):
    # R5: a Pending row with a non-00 code must not reach the model as a reason.
    ctx_b = d.ToolContext(bank=bank, session=session_b, today=NOW.date())
    r = await run(ctx_b, "search_transactions")
    pending = next(t for t in r.data["transactions"] if t["transaction_id"] == "TRX-B1")
    assert pending["transaction_status"] == "Pending" and pending["response_code"] is None
    detail = await run(ctx_b, "get_transaction", transaction_id="TRX-B1")
    assert "decline_reason" not in detail.data["status"]
    assert detail.data["status"]["response_code"] is None


@pytest.mark.parametrize(
    "args",
    [
        {"limit": 21},
        {"date_from": "2026-06-10", "date_to": "2026-06-01"},
        {"min_amount": 10, "max_amount": 1},
        {"customer_id": "CLI-BBBB2222"},  # no identity parameters, ever
        {"status": "Maybe"},
    ],
)
async def test_invalid_arguments_become_an_error_result(ctx, args):
    r = await run(ctx, "search_transactions", **args)
    assert not r.ok and r.error_code == "invalid_arguments"


async def test_search_by_card(ctx):
    r = await run(ctx, "search_transactions", product_id="PRD-ACHK", limit=20)
    assert r.ok and r.data["transactions"]
    assert {t["product_id"] for t in r.data["transactions"]} == {"PRD-ACHK"}


# ---------- get_spending_summary ----------


async def test_spending_summary_by_month_category_and_card(ctx):
    r = await run(ctx, "get_spending_summary")
    assert r.ok
    # Default: 3 whole calendar months up to the latest transaction (2026-06-17).
    assert r.data["period"] == {"from": "2026-04-01", "to": "2026-06-17"}
    assert [m["month"] for m in r.data["by_month"]] == ["2026-04", "2026-05", "2026-06"]
    assert r.data["total_spent_usd"] == "1238.30"
    top = r.data["by_category"][0]
    assert top == {
        "category": "Entertainment",
        "count": 1,
        "total_usd": "912.40",
        "share_pct": "73.68",
        "monthly_average_usd": "304.13",
    }
    cards = {p["product"]: p["total_usd"] for p in r.data["by_product"]}
    assert cards == {"Tarjeta Crédito •••• 4321": "958.30", "Cuenta Corriente •••• 2233": "280.00"}
    assert "1111222233" not in str(r.data)  # numbers stay masked
    assert any("Entertainment: 912.40 USD" in f.fact for f in r.facts)


async def test_spending_summary_for_one_card(ctx):
    r = await run(ctx, "get_spending_summary", months=1, product_id="PRD-ACC")
    assert r.data["scope"] == "Tarjeta Crédito •••• 4321"
    assert r.data["total_spent_usd"] == "958.30"
    assert {c["category"] for c in r.data["by_category"]} == {"Entertainment", "Food"}
    assert len(r.data["by_product"]) == 2  # every card stays listed, to compare


async def test_spending_summary_month_over_month_change(bank, session_b):
    ctx = d.ToolContext(bank=bank, session=session_b, today=NOW.date())
    r = await run(ctx, "get_spending_summary", date_from="2026-05-01", date_to="2026-06-30")
    may, june = r.data["by_month"]
    assert may["total_usd"] == "0.00" and may["change_pct_vs_previous"] is None
    assert june["change_pct_vs_previous"] is None  # after a zero month there's no percentage


@pytest.mark.parametrize(
    "args",
    [
        {"months": 0},
        {"months": 13},
        {"product_id": "ACC-1"},
        {"date_from": "2026-06-10", "date_to": "2026-06-01"},
    ],
)
async def test_spending_summary_rejects_bad_arguments(ctx, args):
    r = await run(ctx, "get_spending_summary", **args)
    assert not r.ok


# ---------- get_transaction ----------


async def test_get_transaction(ctx):
    r = await run(ctx, "get_transaction", transaction_id="TRX-A2")
    assert r.data["status"]["decline_reason"] == "insufficient funds or credit limit"
    assert "reason_code" not in r.data["status"]  # readable text, not a machine code
    assert "flagged_as_fraud" not in r.data
    assert r.facts[0].record_id == "TRX-A2"
    assert "(code 51: insufficient funds or credit limit)" in r.facts[0].fact


async def test_get_transaction_policy_facts(ctx):
    fraud = await run(ctx, "get_transaction", transaction_id="TRX-A4")
    [fact] = fraud.policy_facts
    assert fact == {
        "kind": "transaction", "transaction_id": "TRX-A4", "flagged_as_fraud": True,
        "fraud_score": None, "product_id": "PRD-ACC", "product_status": "Active",
    }
    # The model never sees them.
    assert "flagged_as_fraud" not in str(fraud.data)


async def test_product_status_unknown_when_the_product_read_fails(bank, session_a):
    from ai_backend.bank.faults import BankFault, FaultyBankClient

    faulty = FaultyBankClient(bank, [BankFault(method="get_product", fault="timeout")])
    ctx = d.ToolContext(bank=faulty, session=session_a, today=NOW.date())
    r = await run(ctx, "get_transaction", transaction_id="TRX-A1")
    assert r.ok and r.policy_facts[0]["product_status"] is None


async def test_other_customers_transaction_is_not_found(bank, session_b):
    ctx_b = d.ToolContext(bank=bank, session=session_b, today=NOW.date())
    r = await run(ctx_b, "get_transaction", transaction_id="TRX-A1")
    assert not r.ok and r.error_code == "not_found"


async def test_expired_session_propagates(ctx, bank, session_a):
    bank.revoke_session(session_a.token.get_secret_value())
    with pytest.raises(AuthExpired):
        await run(ctx, "get_balances")


async def test_bank_outage_becomes_an_error_result(bank, session_a):
    from ai_backend.bank.faults import BankFault, FaultyBankClient

    faulty = FaultyBankClient(bank, [BankFault(method="get_balances", fault="timeout")])
    ctx = d.ToolContext(bank=faulty, session=session_a, today=NOW.date())
    r = await run(ctx, "get_balances")
    assert not r.ok and r.error_code == "bank_unavailable"
    assert r.policy_facts == [{"kind": "bank_unavailable", "tool": "get_balances"}]


# ---------- convert_currency ----------


async def test_convert_currency(ctx):
    r = await run(ctx, "convert_currency", amount=100, from_currency="USD", to_currency="COP")
    assert r.data["converted"] == {"amount": "400000.00", "currency": "COP"}
    assert r.data["rate_date"] == "2026-06-15"
    assert r.facts[0].fact.startswith("100 USD = 400000.00 COP")


async def test_convert_currency_on_a_date_and_side(ctx):
    r = await run(
        ctx, "convert_currency", amount=1000000, from_currency="COP", to_currency="USD",
        date="2026-06-13", side="sell",
    )
    assert r.data["converted"]["amount"] == "251.00" and r.data["rate_date"] == "2026-06-12"


async def test_convert_currency_without_a_rate(ctx):
    r = await run(ctx, "convert_currency", amount=1, from_currency="ARS", to_currency="MXN")
    assert not r.ok and r.error_code == "not_found"


def test_decimal_amounts_parse_exactly():
    args = d.ConvertCurrencyArgs.model_validate(
        {"amount": 0.1, "from_currency": "USD", "to_currency": "COP", "date": "2026-06-01"}
    )
    assert args.amount == Decimal("0.1") and args.on == date(2026, 6, 1)
