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


def test_every_p0_read_tool_is_registered():
    assert set(REGISTRY) == {
        "get_balances", "search_transactions", "get_transaction", "convert_currency"
    }
    assert all(t.kind == "read" for t in REGISTRY.values())


def test_schemas_are_strict_and_simple():
    for tool in tool_schemas():
        params = tool["function"]["parameters"]
        assert params["additionalProperties"] is False
        text = str(params)
        assert "anyOf" not in text and "customer" not in text  # no identity parameters


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


# ---------- search_transactions ----------


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
    assert detail.data["status"]["reason_code"] is None


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


# ---------- get_transaction ----------


async def test_get_transaction(ctx):
    r = await run(ctx, "get_transaction", transaction_id="TRX-A2")
    assert r.data["status"]["reason_code"] == "insufficient_funds"
    assert "flagged_as_fraud" not in r.data
    assert r.facts[0].record_id == "TRX-A2" and "(insufficient_funds)" in r.facts[0].fact


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
