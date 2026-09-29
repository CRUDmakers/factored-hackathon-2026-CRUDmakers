from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_backend.bank.models import PaymentResult, TransactionDetailPolicyView
from ai_backend.tools import payments as p


def transfer_args(**overrides) -> dict:
    base = {"source_product_id": "PRD-ACHK", "amount": 100, "to_product_id": "PRD-ACC"}
    base.update(overrides)
    return base


def test_transfer_needs_exactly_one_destination():
    with pytest.raises(ValidationError, match="exactly one destination"):
        p.TransferMoneyArgs.model_validate(transfer_args(to_account_number="123"))
    with pytest.raises(ValidationError):
        p.TransferMoneyArgs.model_validate({"source_product_id": "PRD-A", "amount": 1})


@pytest.mark.parametrize(
    "bad",
    [{"amount": 0}, {"amount": 10.005}, {"source_product_id": "../x"}, {"customer_id": "CLI-X"}],
)
def test_transfer_args_are_strict(bad):
    with pytest.raises(ValidationError):
        p.TransferMoneyArgs.model_validate(transfer_args(**bad))


def test_to_payment_request_transfer_and_bill():
    t = p.to_payment_request(
        "transfer_money",
        p.TransferMoneyArgs.model_validate(
            transfer_args(
                to_product_id=None,
                beneficiary={"name": "Ana", "account_number": "9", "country": "Colombia"},
            )
        ),
    )
    assert t.method == "transfer" and t.destination.beneficiary.name == "Ana"
    assert t.amount == Decimal("100")
    b = p.to_payment_request(
        "pay_bill",
        p.PayBillArgs.model_validate(
            {"source_product_id": "PRD-ACC", "amount": 50.5, "barcode": "8" * 44,
             "due_date": "2026-07-01"}
        ),
    )
    assert b.method == "bill_payment" and b.destination.due_date == date(2026, 7, 1)
    assert b.body()["barcode"] == "8" * 44


def test_handoff_args():
    args = p.HandoffArgs.model_validate({"reason": "follow_up", "summary": "Pending 5 days"})
    assert args.open_questions == []
    with pytest.raises(ValidationError):
        p.HandoffArgs.model_validate({"reason": "because", "summary": "x"})


def test_money_format():
    assert p.money(Decimal("1234567.5"), "COP") == "1.234.567,50 COP"
    assert p.money(Decimal("0.1"), "USD") == "0,10 USD"


def _preview(**overrides) -> PaymentResult:
    base = {
        "transaction_id": None, "transaction_date": "2026-06-18T12:00:00Z", "method": "transfer",
        "transaction_type": "Payment", "amount": "100.00", "currency": "USD",
        "source": {"product_id": "PRD-ACHK", "product_type": "Cuenta Corriente",
                   "currency": "USD", "debited_amount": "100.00", "balance_after": "1400.00"},
        "exchange": None,
        "counterparty": {"type": "internal", "to_product_type": "Tarjeta Crédito",
                         "own_product": True, "international": False},
        "status": "Approved", "completed": True, "response_code": "00", "preview": True,
    }
    base.update(overrides)
    return PaymentResult.model_validate(base)


def test_confirmation_summary_es_and_pt():
    label = p.product_label("Cuenta Corriente", "1111222233", "es")
    es = p.confirmation_summary(_preview(), label, "es")
    assert es == (
        "Pagar 100,00 USD de tu tarjeta de crédito.\n"
        "Desde: cuenta corriente •••• 2233.\n"
        "Saldo después: 1.400,00 USD.\n¿Confirmas?"
    )
    pt = p.confirmation_summary(_preview(), p.product_label("Cuenta Corriente", None, "pt"), "pt")
    assert pt.startswith("Pagar 100,00 USD em seu cartão de crédito.")
    assert pt.endswith("Confirma?")


def test_summary_shows_exchange_and_destination_amount():
    preview = _preview(
        transaction_type="Transfer",
        currency="COP", amount="1000000.00",
        exchange={"from": "COP", "to": "USD", "rate": "0.00026", "rate_date": "2026-06-15"},
        source={"product_id": "PRD-ACHK", "product_type": "Cuenta Corriente", "currency": "USD",
                "debited_amount": "260.00", "balance_after": "1240.00"},
        counterparty={"type": "external", "name": "Ana", "international": True,
                      "destination_amount": {"currency": "COP", "amount": "1000000.00",
                                             "rate": "1", "rate_date": None}},
    )
    text = p.confirmation_summary(preview, "cuenta corriente", "es")
    assert "a Ana" in text and "Se debitarán 260,00 USD (tipo de cambio 0.00026)" in text
    assert "El destinatario recibe 1.000.000,00 COP" in text


def test_summary_for_bills_and_unknown_recipients():
    bill = _preview(method="bill_payment", counterparty={"type": "bill", "biller_name": "Luz"})
    assert p.confirmation_summary(bill, "x", "pt").startswith("Pagar 100,00 USD para Luz.")
    nameless = _preview(
        transaction_type="Transfer", counterparty={"type": "internal", "own_product": False}
    )
    assert "Transferir 100,00 USD a el destinatario" in p.confirmation_summary(nameless, "x", "es")
    no_biller = _preview(method="bill_payment", counterparty={"type": "bill"})
    assert "o boleto" in p.confirmation_summary(no_biller, "x", "pt")


def _readback(status: str, reason: str | None = None) -> TransactionDetailPolicyView:
    return TransactionDetailPolicyView.model_validate(
        {
            "transaction_id": "TRX-SIM1", "transaction_date": "2026-06-18T12:00:00Z",
            "product_id": "PRD-ACHK", "transaction_type": "Payment", "amount": "100.00",
            "currency": "USD", "origin": "simulated", "payment_method": "transfer",
            "status": {"status": status, "completed": status == "Approved",
                       "response_code": "51" if reason else "00", "reason_code": reason},
            "location": {},
        }
    )


def test_result_messages_come_from_the_readback():
    ok = p.result_message(_preview(), _readback("Approved"), "es")
    assert ok == (
        "Listo: la operación fue aprobada. 100,00 USD → tu tarjeta de crédito. "
        "Comprobante: TRX-SIM1."
    )
    declined = p.result_message(_preview(), _readback("Declined", "insufficient_funds"), "pt")
    assert declined == (
        "O banco recusou a operação: saldo ou limite insuficiente. "
        "Nenhum dinheiro foi movimentado."
    )
    unknown = p.result_message(_preview(), _readback("Declined"), "es")
    assert unknown == "El banco rechazó la operación. No se movió dinero."
