"""The fake bank must behave like Node (backend/src/services); each rule mirrors a Node rule."""

from datetime import date
from decimal import Decimal

import pytest

from ai_backend.auth.session import Session
from ai_backend.bank.client import AuthExpired, BankRejected, Forbidden, NotFound
from ai_backend.bank.fake_client import CustomerInactive, FakeBankClient
from ai_backend.bank.models import (
    Beneficiary,
    BillDestination,
    PaymentRequest,
    PixDestination,
    TransactionQuery,
    TransferDestination,
)
from tests.conftest import CUSTOMER_A, CUSTOMER_B, CUSTOMER_SUSPENDED

# ---------- sessions (backend/src/services/auth.ts) ----------


def test_inactive_or_unknown_customers_get_no_session(bank):
    with pytest.raises(CustomerInactive):
        bank.issue_test_session(CUSTOMER_SUSPENDED)
    with pytest.raises(NotFound):
        bank.issue_test_session("CLI-NOPE0000")


async def test_session_check(bank, clock):
    s = bank.issue_test_session(CUSTOMER_A)
    token = s.token.get_secret_value()
    assert (await bank.get_session(token)).customer_id == CUSTOMER_A
    with pytest.raises(AuthExpired, match="unauthorized"):
        await bank.get_session("not-a-token")
    clock.advance(seconds=900)
    with pytest.raises(AuthExpired, match="session_expired"):
        await bank.get_session(token)


async def test_revoked_session_is_rejected_everywhere(bank, session_a):
    bank.revoke_session(session_a.token.get_secret_value())
    with pytest.raises(AuthExpired, match="session_revoked"):
        await bank.get_balances(session_a)


async def test_session_without_token_is_rejected(bank, session_a):
    with pytest.raises(AuthExpired):
        await bank.get_balances(session_a.model_copy(update={"token": None}))


async def test_token_of_one_customer_cannot_read_another(bank, session_a):
    # Node's hook: 403 when the token's customer isn't the URL's customer.
    forged = session_a.model_copy(update={"customer_id": CUSTOMER_B})
    with pytest.raises(Forbidden):
        await bank.get_balances(forged)


# ---------- reads (customers.ts, transactions.ts, exchange.ts) ----------


async def test_balances(bank, session_a):
    b = await bank.get_balances(session_a)
    assert {a.product_id for a in b.accounts} == {"PRD-ACHK", "PRD-ASAV", "PRD-AOLD", "PRD-ABLK"}
    assert "PRD-ACLS" not in {a.product_id for a in b.accounts}  # Closed is left out
    card = b.credit_cards[0]
    assert card.available_credit == Decimal("3799.50")
    assert card.utilization_pct == Decimal("24.01")
    assert card.product_number == "•••• 4321"
    [usd] = b.totals_by_currency
    assert usd.available_funds == Decimal("2010.00")
    assert usd.investments == Decimal("1000.00")
    assert usd.debt == Decimal("1200.50")
    assert b.net_worth_usd == Decimal("1809.50")


async def test_balances_convert_net_worth_with_latest_rate(bank, session_b):
    b = await bank.get_balances(session_b)
    assert [loan.product_id for loan in b.loans] == ["PRD-BLOAN"]
    # (2,500,000 − 900,000) COP × 0.000260 (latest COP→USD)
    assert b.net_worth_usd == Decimal("416.00")


async def test_other_customers_records_look_missing(bank, session_b):
    # Node filters by customer, so another customer's record is a 404, like an unknown ID.
    for call in (
        bank.get_transaction(session_b, "TRX-A1"),
        bank.get_product(session_b, "PRD-ACC"),
        bank.get_transaction(session_b, "TRX-NOPE"),
    ):
        with pytest.raises(NotFound):
            await call


async def test_list_is_newest_first_with_total(bank, session_a):
    page = await bank.list_transactions(session_a, TransactionQuery(limit=2))
    assert page.total == 6
    assert [t.transaction_id for t in page.items] == ["TRX-A3", "TRX-A2"]
    page2 = await bank.list_transactions(session_a, TransactionQuery(limit=2, offset=2))
    assert [t.transaction_id for t in page2.items] == ["TRX-A1", "TRX-A5"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (TransactionQuery(status="Declined"), {"TRX-A2", "TRX-A5"}),
        (TransactionQuery(type="Withdrawal"), {"TRX-A3"}),
        (TransactionQuery(channel="POS"), {"TRX-A1", "TRX-A2", "TRX-A4"}),
        (TransactionQuery(product_id="PRD-ACHK"), {"TRX-A3", "TRX-A5", "TRX-A6"}),
        # category = transaction_category, else merchant_category, else a type-based default
        (TransactionQuery(category="Services"), {"TRX-A6"}),
        (TransactionQuery(category="Withdrawals"), {"TRX-A3"}),
        (TransactionQuery(category="Transfers"), {"TRX-A5"}),
        (
            TransactionQuery(date_from=date(2026, 6, 15), date_to=date(2026, 6, 16)),
            {"TRX-A1", "TRX-A2"},
        ),
        (TransactionQuery(origin="simulated"), set()),
    ],
)
async def test_list_filters(bank, session_a, query, expected):
    page = await bank.list_transactions(session_a, query)
    assert {t.transaction_id for t in page.items} == expected


async def test_list_item_fields(bank, session_a, session_b):
    page_a = await bank.list_transactions(session_a, TransactionQuery())
    items = {t.transaction_id: t for t in page_a.items}
    assert items["TRX-A1"].amount_usd == Decimal("45.90")  # USD: the amount itself
    assert items["TRX-A1"].direction == "out"
    assert items["TRX-A1"].product_type == "Tarjeta Crédito"
    assert items["TRX-A5"].transaction_country == "Mexico"  # raw, as in Node
    page_b = await bank.list_transactions(session_b, TransactionQuery())
    b = {t.transaction_id: t for t in page_b.items}
    assert b["TRX-B1"].amount_usd == Decimal("37.50")  # the dataset's value
    # No amount_usd: rate on or before the transaction's date (06-12: 0.000250), not the latest
    assert b["TRX-B2"].amount_usd == Decimal("100.00")
    assert b["TRX-B2"].direction == "in"


async def test_transaction_detail(bank, session_a, session_b):
    t = await bank.get_transaction(session_a, "TRX-A3")
    assert t.location.branch is not None and t.location.branch.name == "Banco LATAM Tijuana Sur"
    assert t.status.completed and t.status.reason_code is None
    declined = await bank.get_transaction(session_a, "TRX-A2")
    assert declined.status.reason_code == "insufficient_funds"
    assert (await bank.get_transaction(session_a, "TRX-A5")).status.response_code is None
    assert (await bank.get_transaction(session_a, "TRX-A4")).flagged_as_fraud is True
    assert (await bank.get_transaction(session_a, "TRX-A4")).fraud_score is None  # R1
    # Node gives a reason for non-Declined rows with a code too (R5); the fake mirrors it.
    pending = await bank.get_transaction(session_b, "TRX-B1")
    assert pending.status.status == "Pending" and pending.status.reason_code == "do_not_honor"


async def test_product_detail(bank, session_a):
    old = await bank.get_product(session_a, "PRD-AOLD")
    assert old.is_expired is True and old.product_number == "•••• 9876"
    cc = await bank.get_product(session_a, "PRD-ACC")
    assert cc.available_credit == Decimal("3799.50") and cc.is_expired is False
    chk = await bank.get_product(session_a, "PRD-ACHK")
    assert chk.product_number == "1111222233" and chk.available_credit is None


async def test_rates(bank):
    latest = await bank.get_rate("COP", "USD")
    assert latest.exchange_rate == Decimal("0.000260") and latest.rate_date == date(2026, 6, 15)
    older = await bank.get_rate("COP", "USD", date(2026, 6, 14))
    assert older.exchange_rate == Decimal("0.000250")
    same = await bank.get_rate("USD", "USD")
    assert same.exchange_rate == 1 and same.rate_date is None
    with pytest.raises(NotFound):
        await bank.get_rate("COP", "USD", date(2026, 1, 1))
    with pytest.raises(NotFound):
        await bank.get_rate("ARS", "MXN")


# ---------- payments (payments.ts) ----------


def transfer(
    source: str, amount: str, currency: str | None = None, **destination
) -> PaymentRequest:
    return PaymentRequest(
        method="transfer",
        source_product_id=source,
        amount=Decimal(amount),
        currency=currency,
        destination=TransferDestination(**destination),
    )


def bill(source: str, amount: str, barcode: str = "8" * 44) -> PaymentRequest:
    return PaymentRequest(
        method="bill_payment",
        source_product_id=source,
        amount=Decimal(amount),
        destination=BillDestination(barcode=barcode, biller_name="Luz del Norte"),
    )


async def _balance(bank: FakeBankClient, s: Session, product_id: str) -> Decimal:
    p = await bank.get_product(s, product_id)
    assert p.current_balance is not None
    return p.current_balance


async def test_preview_changes_nothing(bank, session_a):
    req = transfer("PRD-ACHK", "100.00", to_product_id="PRD-ASAV")
    r = await bank.preview_payment(session_a, req)
    assert r.preview and r.transaction_id is None
    assert r.status == "Approved" and r.source.balance_after == Decimal("1400.00")
    assert await _balance(bank, session_a, "PRD-ACHK") == Decimal("1500.00")
    page = await bank.list_transactions(session_a, TransactionQuery(origin="simulated"))
    assert page.total == 0


async def test_pay_own_credit_card(bank, session_a):
    r = await bank.execute_payment(
        session_a, transfer("PRD-ACHK", "100.00", to_product_id="PRD-ACC"), "key-1"
    )
    assert r.status == "Approved" and not r.preview and r.transaction_id
    assert r.transaction_type == "Payment"  # paying a debt product
    assert r.counterparty.own_product is True and r.counterparty.international is False
    assert await _balance(bank, session_a, "PRD-ACHK") == Decimal("1400.00")
    assert await _balance(bank, session_a, "PRD-ACC") == Decimal("1100.50")  # debt reduced
    # Read-back (what `verify` will do)
    back = await bank.get_transaction(session_a, r.transaction_id)
    assert back.origin == "simulated" and back.payment_method == "transfer"
    assert back.amount == Decimal("100.00") and back.status.status == "Approved"
    # Node also records a Deposit on the destination product
    page = await bank.list_transactions(session_a, TransactionQuery(origin="simulated"))
    assert {t.transaction_type for t in page.items} == {"Payment", "Deposit"}


async def test_transfer_to_another_customer_by_account_number(bank, session_a, session_b):
    r = await bank.execute_payment(
        session_a, transfer("PRD-ACHK", "100.00", to_account_number="2222-3333 44"), "k"
    )
    assert r.status == "Approved" and r.transaction_type == "Transfer"
    assert r.counterparty.own_product is False
    assert r.counterparty.international is True  # México → Colombia
    assert r.counterparty.destination_amount is None  # only for other banks
    # The recipient receives COP at the latest USD→COP rate, as a Deposit in their country
    assert await _balance(bank, session_b, "PRD-BCHK") == Decimal("2900000.00")
    deposits = await bank.list_transactions(session_b, TransactionQuery(origin="simulated"))
    [deposit] = deposits.items
    assert deposit.transaction_type == "Deposit" and deposit.transaction_country == "Colombia"


async def test_transfer_to_other_bank_abroad_shows_destination_amount(bank, session_a):
    r = await bank.preview_payment(
        session_a,
        transfer(
            "PRD-ACHK", "10.00",
            beneficiary=Beneficiary(name="Ana", account_number="123", country="colombia"),
        ),
    )
    assert r.counterparty.type == "external" and r.counterparty.international is True
    assert r.counterparty.destination_amount is not None
    assert r.counterparty.destination_amount.currency == "COP"
    assert r.counterparty.destination_amount.amount == Decimal("40000.00")


async def test_amount_in_another_currency_is_converted(bank, session_a):
    r = await bank.preview_payment(
        session_a, transfer("PRD-ACHK", "1000000.00", "COP", to_product_id="PRD-ASAV")
    )
    assert r.source.debited_amount == Decimal("260.00")  # latest COP→USD
    assert r.exchange is not None and r.exchange.rate == Decimal("0.000260")


@pytest.mark.parametrize(
    ("req", "code"),
    [
        (transfer("PRD-ACHK", "1500.01", to_product_id="PRD-ASAV"), "51"),
        (transfer("PRD-AOLD", "1.00", to_product_id="PRD-ASAV"), "54"),  # card expired 2024
        (transfer("PRD-ABLK", "1.00", to_product_id="PRD-ASAV"), "05"),  # blocked
        (transfer("PRD-ACHK", "1.00", to_account_number="0000000000"), "14"),
        (transfer("PRD-ACHK", "1.00", to_product_id="PRD-ACLS"), "14"),  # closed destination
        (transfer("PRD-ACHK", "1.00", to_product_id="PRD-NOPE"), "14"),
        (bill("PRD-ACC", "3799.51"), "51"),  # over the card's available credit
    ],
)
async def test_declines(bank, session_a, req, code):
    r = await bank.execute_payment(session_a, req, "k")
    assert r.status == "Declined" and r.response_code == code and not r.completed
    assert r.source.debited_amount == 0 and r.decline_detail
    # Declined operations are recorded too, and nothing moved
    back = await bank.get_transaction(session_a, r.transaction_id)
    assert back.status.status == "Declined" and back.status.response_code == code


async def test_bill_payment(bank, session_a):
    r = await bank.execute_payment(session_a, bill("PRD-ACC", "3799.50"), "k")
    assert r.status == "Approved" and r.transaction_type == "Payment"
    assert r.counterparty.biller_name == "Luz del Norte"
    assert await _balance(bank, session_a, "PRD-ACC") == Decimal("5000.00")  # credit: debt grows
    back = await bank.get_transaction(session_a, r.transaction_id)
    assert back.transaction_category == "Services" and back.merchant_name == "Luz del Norte"


@pytest.mark.parametrize(
    ("req", "code"),
    [
        (transfer("PRD-ACC", "1.00", to_product_id="PRD-ASAV"), "invalid_source_product"),
        (transfer("PRD-ACHK", "1.00", to_product_id="PRD-ACHK"), "invalid_destination"),
        (transfer("PRD-ACHK", "1.00", to_account_number="1111222233"), "invalid_destination"),
        (transfer("PRD-ACHK", "1.00", to_product_id="PRD-AINV"), "invalid_destination"),
        (
            transfer(
                "PRD-ACHK", "1.00",
                beneficiary=Beneficiary(name="Ana", account_number="1", country="Brasil"),
            ),
            "country_not_supported",
        ),
        (bill("PRD-ACHK", "1.00", barcode="123"), "invalid_barcode"),
    ],
)
async def test_validation_errors_record_nothing(bank, session_a, req, code):
    with pytest.raises(BankRejected) as exc:
        await bank.execute_payment(session_a, req, "k")
    assert exc.value.code == code
    page = await bank.list_transactions(session_a, TransactionQuery(origin="simulated"))
    assert page.total == 0


async def test_source_of_another_customer_is_not_found(bank, session_b):
    with pytest.raises(NotFound):
        await bank.preview_payment(
            session_b, transfer("PRD-ACHK", "1.00", to_product_id="PRD-BCHK")
        )


async def test_same_key_twice_pays_twice_like_node(bank, session_a):
    # Node ignores idempotency keys until R2. This is why writes are never retried.
    req = transfer("PRD-ACHK", "10.00", to_product_id="PRD-ASAV")
    a = await bank.execute_payment(session_a, req, "same-key")
    b = await bank.execute_payment(session_a, req, "same-key")
    assert a.transaction_id != b.transaction_id
    assert await _balance(bank, session_a, "PRD-ACHK") == Decimal("1480.00")


async def test_pix_is_not_supported_by_the_fake(bank, session_a):
    req = PaymentRequest(
        method="pix", source_product_id="PRD-ACHK", amount=Decimal("1"),
        destination=PixDestination(pix_key="ana@example.com"),
    )
    with pytest.raises(NotImplementedError):
        await bank.preview_payment(session_a, req)


async def test_ping(bank):
    await bank.ping()
