"""HttpBankClient against respx mocks shaped like Node's responses (backend/src/services)."""

import json
from decimal import Decimal

import httpx
import pytest

from ai_backend.auth.session import Session
from ai_backend.bank.client import (
    AuthExpired,
    BankContractError,
    BankRejected,
    BankUnavailable,
    Forbidden,
    NotFound,
)
from ai_backend.bank.http_client import HttpBankClient, dumps_exact
from ai_backend.bank.models import (
    BillDestination,
    PaymentRequest,
    TransactionQuery,
    TransferDestination,
)
from ai_backend.config import Retries

BASE = "http://node.test"
CID = "CLI-G4X2AMVD62NR"
TOKEN = "eyJ.test.token"

SESSION = Session(
    customer_id=CID, session_id="s-1", expires_at="2026-09-28T12:15:00Z", token=TOKEN
)
BALANCES = {
    "customer_id": CID,
    "accounts": [
        {
            "product_id": "PRD-1", "product_type": "Cuenta Corriente",
            "product_number": "8115899730", "currency": "COP", "status": "Active",
            "balance": "8801675.81",
        }
    ],
    "credit_cards": [
        {
            "product_id": "PRD-2", "product_number": "•••• 4947", "currency": "COP",
            "status": "Active", "invoice_amount": "5851937.34", "credit_limit": "0",
            "available_credit": "-5851937.34", "utilization_pct": None, "interest_rate": 22.3,
            "expiration_date": "2029-01-31", "days_past_due": 0,
        }
    ],
    "loans": [],
    "investments": [],
    "totals_by_currency": [
        {
            "currency": "COP", "available_funds": "8801675.81", "investments": "0",
            "debt": "5851937.34", "net": "2949738.47", "usd_rate": "0.00025",
            "usd_rate_date": "2026-06-17",
        }
    ],
    "net_worth_usd": "737.43",
}
PAYMENT = {
    "transaction_id": "TRX-ABCDEFGHIJKLMNOPQRST",
    "transaction_date": "2026-09-28T12:00:00.000Z",
    "method": "transfer",
    "transaction_type": "Transfer",
    "amount": "10.5",
    "currency": "USD",
    "source": {
        "product_id": "PRD-1", "product_type": "Cuenta Corriente", "currency": "USD",
        "debited_amount": "10.5", "balance_after": "989.5",
    },
    "exchange": None,
    "counterparty": {"type": "internal", "to_product_id": "PRD-3", "international": False},
    "credited": None,
    "status": "Approved",
    "status_description": "Concluída com sucesso.",
    "completed": True,
    "response_code": "00",
    "reason_code": None,
    "reason": None,
    "decline_detail": None,
}
TRANSFER = PaymentRequest(
    method="transfer", source_product_id="PRD-1", amount=Decimal("10.50"),
    destination=TransferDestination(to_product_id="PRD-3"),
)


def _client() -> HttpBankClient:
    return HttpBankClient(BASE, timeout_seconds=1, retries=Retries(max=2, backoff_base_seconds=0))


def _error(status: int, code: str, message: str = "m", details=None) -> httpx.Response:
    body = {"error": code, "message": message}
    if details is not None:
        body["details"] = details
    return httpx.Response(status, json=body)


async def test_get_session_forwards_the_token(respx_mock):
    route = respx_mock.get(f"{BASE}/auth/sessions/current").respond(
        json={"customer_id": CID, "session_id": "s-1", "expires_at": "2026-09-28T12:15:00.000Z"}
    )
    s = await _client().get_session(TOKEN)
    assert s.customer_id == CID and s.token.get_secret_value() == TOKEN
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("code", ["unauthorized", "session_expired", "session_revoked"])
async def test_401s_are_auth_expired(respx_mock, code):
    respx_mock.get(f"{BASE}/auth/sessions/current").mock(return_value=_error(401, code))
    with pytest.raises(AuthExpired, match=code):
        await _client().get_session(TOKEN)


async def test_balances_url_is_built_from_the_session(respx_mock):
    route = respx_mock.get(f"{BASE}/api/customers/{CID}/balances").respond(json=BALANCES)
    b = await _client().get_balances(SESSION)
    assert b.accounts[0].balance == Decimal("8801675.81")
    assert b.credit_cards[0].interest_rate == Decimal("22.3")
    assert route.called


async def test_list_transactions_sends_node_query_names(respx_mock):
    route = respx_mock.get(f"{BASE}/api/customers/{CID}/transactions").respond(
        json={"total": 0, "limit": 5, "offset": 0, "items": []}
    )
    await _client().list_transactions(SESSION, TransactionQuery(status="Declined", limit=5))
    params = route.calls.last.request.url.params
    assert params["status"] == "Declined" and params["limit"] == "5"


@pytest.mark.parametrize("bad_id", ["../balances", "TRX-1/../../x", "trx-lower", "PRD-1"])
@pytest.mark.respx(assert_all_called=False)
async def test_ids_that_are_not_node_shaped_never_reach_a_url(respx_mock, bad_id):
    route = respx_mock.route().respond(json={})
    with pytest.raises(NotFound):
        await _client().get_transaction(SESSION, bad_id)
    assert not route.called


@pytest.mark.respx(assert_all_called=False)
async def test_product_ids_are_checked_too(respx_mock):
    route = respx_mock.route().respond(json={})
    with pytest.raises(NotFound):
        await _client().get_product(SESSION, "PRD-../x")
    assert not route.called


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (_error(403, "forbidden"), Forbidden),
        (_error(404, "not_found"), NotFound),
        (_error(400, "validation_error"), BankContractError),
        (_error(409, "conflict"), BankContractError),
        (httpx.Response(200, text="not json"), BankContractError),
        (httpx.Response(200, json={"unexpected": True}), BankContractError),
    ],
)
async def test_error_mapping(respx_mock, response, error):
    respx_mock.get(f"{BASE}/api/customers/{CID}/balances").mock(return_value=response)
    with pytest.raises(error):
        await _client().get_balances(SESSION)


async def test_422_carries_node_code_and_details(respx_mock):
    respx_mock.post(f"{BASE}/api/customers/{CID}/transfers").mock(
        return_value=_error(
            422, "country_not_supported", "O banco não faz transferências para Brasil.",
            {"supported_countries": ["México", "Colombia", "Argentina"]},
        )
    )
    with pytest.raises(BankRejected) as exc:
        await _client().preview_payment(SESSION, TRANSFER)
    assert exc.value.code == "country_not_supported"
    assert exc.value.details == {"supported_countries": ["México", "Colombia", "Argentina"]}


async def test_reads_are_retried_then_give_up(respx_mock):
    route = respx_mock.get(f"{BASE}/api/customers/{CID}/balances").mock(
        return_value=httpx.Response(503, text="")
    )
    with pytest.raises(BankUnavailable):
        await _client().get_balances(SESSION)
    assert route.call_count == 3  # 1 + retries.max


async def test_reads_recover_after_a_timeout(respx_mock):
    route = respx_mock.get(f"{BASE}/api/customers/{CID}/balances").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json=BALANCES)]
    )
    await _client().get_balances(SESSION)
    assert route.call_count == 2


async def test_connection_errors_are_unavailable(respx_mock):
    respx_mock.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(BankUnavailable):
        await _client().ping()


async def test_payments_are_never_retried(respx_mock):
    route = respx_mock.post(f"{BASE}/api/customers/{CID}/transfers").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with pytest.raises(BankUnavailable):
        await _client().execute_payment(SESSION, TRANSFER, "key-1")
    assert route.call_count == 1


async def test_execute_sends_body_and_idempotency_key(respx_mock):
    route = respx_mock.post(f"{BASE}/api/customers/{CID}/transfers").respond(201, json=PAYMENT)
    r = await _client().execute_payment(SESSION, TRANSFER, "key-1")
    request = route.calls.last.request
    assert request.headers["idempotency-key"] == "key-1"
    assert "dry_run" not in request.url.params
    assert request.content == (
        b'{"source_product_id": "PRD-1", "amount": 10.50, "to_product_id": "PRD-3"}'
    )
    assert r.transaction_id == "TRX-ABCDEFGHIJKLMNOPQRST" and r.amount == Decimal("10.5")


async def test_preview_uses_dry_run(respx_mock):
    route = respx_mock.post(f"{BASE}/api/customers/{CID}/bill-payments").respond(
        json={**PAYMENT, "transaction_id": None, "method": "bill_payment",
              "transaction_type": "Payment", "counterparty": {"type": "bill"}, "preview": True}
    )
    req = PaymentRequest(
        method="bill_payment", source_product_id="PRD-1", amount=Decimal("1"),
        destination=BillDestination(barcode="1" * 44),
    )
    r = await _client().preview_payment(SESSION, req)
    assert route.calls.last.request.url.params["dry_run"] == "true"
    assert r.preview and r.transaction_id is None


async def test_get_rate_is_public_and_dated(respx_mock):
    route = respx_mock.get(f"{BASE}/api/exchange-rates").respond(
        json={
            "source_currency": "USD", "target_currency": "COP", "rate_date": "2026-06-17",
            "exchange_rate": "3954.98", "buy_rate": "3915.22", "sell_rate": "3994.74",
            "source": "Central Bank",
        }
    )
    from datetime import date

    r = await _client().get_rate("USD", "COP", date(2026, 6, 1))
    request = route.calls.last.request
    assert "authorization" not in request.headers
    assert request.url.params["date"] == "2026-06-01" and r.exchange_rate == Decimal("3954.98")


async def test_session_without_token_never_calls_node():
    with pytest.raises(AuthExpired):
        await _client().get_balances(SESSION.model_copy(update={"token": None}))


def test_dumps_exact_keeps_decimals_exact():
    body = dumps_exact({"a": Decimal("0.10"), "b": [Decimal("12345678901234.99")], "c": "x"})
    assert body == b'{"a": 0.10, "b": [12345678901234.99], "c": "x"}'
    assert json.loads(body)["c"] == "x"


def test_dumps_exact_is_not_fooled_by_customer_text():
    # A description can't be turned into a number by looking like a placeholder.
    body = dumps_exact({"amount": Decimal("1.00"), "description": "0:0"})
    assert json.loads(body)["description"] == "0:0"


def test_dumps_exact_rejects_nan():
    with pytest.raises(ValueError):
        dumps_exact({"amount": Decimal("NaN")})


async def test_money_numbers_keep_every_digit(respx_mock):
    # Node sends money as JSON numbers. A float would round this one.
    text = json.dumps(BALANCES | {"net_worth_usd": "@"}).replace('"@"', "12345678901234567.89")
    respx_mock.get(f"{BASE}/api/customers/{CID}/balances").mock(
        return_value=httpx.Response(200, content=text.encode())
    )
    b = await _client().get_balances(SESSION)
    assert b.net_worth_usd == Decimal("12345678901234567.89")
