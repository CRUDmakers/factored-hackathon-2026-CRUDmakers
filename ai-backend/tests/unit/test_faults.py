import time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_backend.bank.client import BankContractError, BankUnavailable
from ai_backend.bank.faults import BankFault, FaultyBankClient
from ai_backend.bank.models import PaymentRequest, TransactionQuery, TransferDestination


@pytest.mark.parametrize(
    ("fault", "error"),
    [
        ("timeout", BankUnavailable),
        ("error_500", BankUnavailable),
        ("malformed", BankContractError),
    ],
)
async def test_faults_raise_and_others_pass_through(bank, session_a, fault, error):
    faulty = FaultyBankClient(bank, [BankFault(method="get_balances", fault=fault)])
    with pytest.raises(error):
        await faulty.get_balances(session_a)
    await faulty.list_transactions(session_a, TransactionQuery())


async def test_times_then_recovers(bank, session_a):
    faulty = FaultyBankClient(bank, [BankFault(method="get_balances", fault="timeout", times=2)])
    for _ in range(2):
        with pytest.raises(BankUnavailable):
            await faulty.get_balances(session_a)
    await faulty.get_balances(session_a)


async def test_slow(bank):
    faulty = FaultyBankClient(bank, [BankFault(method="ping", fault="slow", delay_seconds=0.05)])
    start = time.perf_counter()
    await faulty.ping()
    assert time.perf_counter() - start >= 0.05


async def test_lost_response_means_the_payment_happened(bank, session_a):
    faulty = FaultyBankClient(bank, [BankFault(method="execute_payment", fault="lost_response")])
    req = PaymentRequest(
        method="transfer", source_product_id="PRD-ACHK", amount=Decimal("10.00"),
        destination=TransferDestination(to_product_id="PRD-ASAV"),
    )
    with pytest.raises(BankUnavailable):
        await faulty.execute_payment(session_a, req, "k")
    # This is what reconciliation will find.
    page = await bank.list_transactions(
        session_a, TransactionQuery(origin="simulated", product_id="PRD-ACHK")
    )
    assert page.total == 1 and page.items[0].amount == Decimal("10.00")


def test_unknown_method_is_rejected():
    with pytest.raises(ValidationError):
        BankFault(method="drop_tables", fault="timeout")
