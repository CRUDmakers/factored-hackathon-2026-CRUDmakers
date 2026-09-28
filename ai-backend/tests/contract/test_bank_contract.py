"""One suite, two banks: the fake (always) and a live Node (`pytest -m node`).

The fake must behave like Node, or the eval measures a system we don't ship. These cases use the
frontend's demo customers, which exist in both the fixture and Node's database. Against Node they
need a freshly reset database (`npm run db:reset`) and:

    BANK_BASE_URL=http://localhost:3000 EVAL_SERVICE_KEY=dev-service-key pytest -m node

Only shapes and rules are asserted, never exact balances: Node holds three years of history and
any demo payments made since the last reset.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ai_backend.auth.session import Session
from ai_backend.bank.client import AuthExpired, BankClient, BankRejected, NotFound
from ai_backend.bank.fake_client import CustomerInactive, FakeBankClient
from ai_backend.bank.http_client import HttpBankClient
from ai_backend.bank.models import PaymentRequest, TransactionQuery, TransferDestination
from ai_backend.config import Retries

FIXTURE = Path(__file__).parents[2] / "eval" / "fixtures" / "data"

# frontend/src/testCustomers.ts, with products looked up in the dataset
FRANCISCO = "CLI-7T6B34S2O9UL"  # MX, USD
FRANCISCO_CHECKING = "PRD-IFCGYI99EXAH"
FRANCISCO_SAVINGS = "PRD-TQ2IKKDV7YN9"
FRANCISCO_EXPIRED_DEBIT = "PRD-E0RUGH87WNK1"  # expired 2023-03-08
FRANCISCO_CREDIT_CARD = "PRD-8RC6ZKX1BIWI"
GABRIELA = "CLI-QITAGXCUR83U"  # MX, USD
GABRIELA_BLOCKED_DEBIT = "PRD-6DAPOTHN7RRI"
SUSPENDED = "CLI-CSV0VF8IA55L"


@dataclass
class Env:
    bank: BankClient
    login: Callable[[str], Awaitable[Session]]


async def _fake_env() -> Env:
    if not (FIXTURE / "manifest.json").exists():
        pytest.skip("run `python -m eval.fixtures.extract`")
    fake = FakeBankClient.from_dir(FIXTURE)  # real clock, like Node

    async def login(customer_id: str) -> Session:
        return fake.issue_test_session(customer_id)

    return Env(fake, login)


def _node_env() -> tuple[Env, HttpBankClient]:
    base, key = os.environ.get("BANK_BASE_URL"), os.environ.get("EVAL_SERVICE_KEY")
    if not base or not key:
        pytest.skip("set BANK_BASE_URL and EVAL_SERVICE_KEY to run against Node")
    client = HttpBankClient(base, timeout_seconds=5, retries=Retries(max=0, backoff_base_seconds=0))

    async def login(customer_id: str) -> Session:
        async with httpx.AsyncClient(base_url=base) as http:
            r = await http.post(
                "/auth/test-sessions",
                json={"customer_id": customer_id},
                headers={"x-service-key": key},
            )
        if r.status_code == 403:
            raise CustomerInactive(r.json().get("error", "customer_inactive"))
        r.raise_for_status()
        return await client.get_session(r.json()["access_token"])

    return Env(client, login), client


@pytest.fixture(params=["fake", pytest.param("node", marks=pytest.mark.node)])
async def env(request) -> AsyncIterator[Env]:
    if request.param == "fake":
        yield await _fake_env()
        return
    node_env, client = _node_env()
    try:
        yield node_env
    finally:
        await client.aclose()


def _transfer(source: str, amount: str, to_product: str) -> PaymentRequest:
    return PaymentRequest(
        method="transfer",
        source_product_id=source,
        amount=Decimal(amount),
        destination=TransferDestination(to_product_id=to_product),
    )


# ---------- sessions ----------


async def test_session_round_trip(env):
    s = await env.login(FRANCISCO)
    assert s.customer_id == FRANCISCO
    again = await env.bank.get_session(s.token.get_secret_value())
    assert again.customer_id == FRANCISCO and again.session_id == s.session_id


async def test_garbage_token_is_auth_expired(env):
    with pytest.raises(AuthExpired):
        await env.bank.get_session("not-a-real-token")


async def test_suspended_customer_cannot_log_in(env):
    with pytest.raises(CustomerInactive):
        await env.login(SUSPENDED)


# ---------- reads ----------


async def test_balances_shape(env):
    b = await env.bank.get_balances(await env.login(FRANCISCO))
    assert FRANCISCO_CHECKING in {a.product_id for a in b.accounts}
    assert all(a.status != "Closed" for a in b.accounts)
    assert b.totals_by_currency


async def test_transactions_newest_first_and_filtered(env):
    s = await env.login(FRANCISCO)
    page = await env.bank.list_transactions(s, TransactionQuery(limit=5))
    dates = [t.transaction_date for t in page.items]
    assert 0 < len(dates) <= 5 and dates == sorted(dates, reverse=True)
    declined = await env.bank.list_transactions(s, TransactionQuery(status="Declined"))
    assert declined.items and all(t.transaction_status == "Declined" for t in declined.items)


async def test_detail_of_own_transaction(env):
    s = await env.login(FRANCISCO)
    [item] = (await env.bank.list_transactions(s, TransactionQuery(limit=1))).items
    t = await env.bank.get_transaction(s, item.transaction_id)
    assert t.transaction_id == item.transaction_id and t.amount == item.amount


async def test_another_customers_transaction_is_not_found(env):
    gabriela = await env.login(GABRIELA)
    [theirs] = (await env.bank.list_transactions(gabriela, TransactionQuery(limit=1))).items
    francisco = await env.login(FRANCISCO)
    with pytest.raises(NotFound):
        await env.bank.get_transaction(francisco, theirs.transaction_id)


async def test_unknown_product_is_not_found(env):
    with pytest.raises(NotFound):
        await env.bank.get_product(await env.login(FRANCISCO), "PRD-DOESNOTEXIST")


async def test_expired_card_is_flagged(env):
    p = await env.bank.get_product(await env.login(FRANCISCO), FRANCISCO_EXPIRED_DEBIT)
    assert p.is_expired is True and p.product_number and p.product_number.startswith("••••")


async def test_rates(env):
    r = await env.bank.get_rate("USD", "COP")
    assert r.exchange_rate > 0 and r.rate_date is not None
    same = await env.bank.get_rate("USD", "USD")
    assert same.exchange_rate == 1


# ---------- payments ----------


async def test_preview_records_nothing(env):
    s = await env.login(FRANCISCO)
    before = await env.bank.list_transactions(s, TransactionQuery(origin="simulated", limit=1))
    r = await env.bank.preview_payment(s, _transfer(FRANCISCO_CHECKING, "1.00", FRANCISCO_SAVINGS))
    assert r.preview and r.transaction_id is None and r.status == "Approved"
    after = await env.bank.list_transactions(s, TransactionQuery(origin="simulated", limit=1))
    assert after.total == before.total


@pytest.mark.parametrize(
    ("customer", "source", "amount", "code"),
    [
        (FRANCISCO, FRANCISCO_CHECKING, "99999999.00", "51"),
        (FRANCISCO, FRANCISCO_EXPIRED_DEBIT, "1.00", "54"),
        (GABRIELA, GABRIELA_BLOCKED_DEBIT, "1.00", "05"),
    ],
)
async def test_preview_declines(env, customer, source, amount, code):
    s = await env.login(customer)
    [dest] = [
        a.product_id
        for a in (await env.bank.get_balances(s)).accounts
        if a.product_id != source and a.product_type in ("Cuenta Corriente", "Cuenta Ahorro")
    ][:1]
    r = await env.bank.preview_payment(s, _transfer(source, amount, dest))
    assert r.status == "Declined" and r.response_code == code


async def test_preview_rejects_credit_card_as_transfer_source(env):
    s = await env.login(FRANCISCO)
    with pytest.raises(BankRejected) as exc:
        await env.bank.preview_payment(
            s, _transfer(FRANCISCO_CREDIT_CARD, "1.00", FRANCISCO_SAVINGS)
        )
    assert exc.value.code == "invalid_source_product"


async def test_execute_then_read_back(env):
    s = await env.login(FRANCISCO)
    r = await env.bank.execute_payment(
        s, _transfer(FRANCISCO_CHECKING, "1.00", FRANCISCO_SAVINGS), "contract-test"
    )
    assert r.status == "Approved" and r.transaction_id and not r.preview
    back = await env.bank.get_transaction(s, r.transaction_id)
    assert back.origin == "simulated" and back.payment_method == "transfer"
    assert back.amount == Decimal("1.00") and back.status.status == "Approved"
