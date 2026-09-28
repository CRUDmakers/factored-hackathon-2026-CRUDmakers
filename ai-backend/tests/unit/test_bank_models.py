from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_backend.bank.models import (
    Balances,
    BillDestination,
    PaymentRequest,
    PaymentResult,
    TransactionDetailLLMView,
    TransactionDetailPolicyView,
    TransactionQuery,
    TransferDestination,
    last4,
)

# Shapes as Node sends them: Prisma Decimals arrive as strings, Floats as numbers, dates as ISO.
NODE_DETAIL = {
    "transaction_id": "TRX-7I07NJ7LT0TPC5YC33UL",
    "transaction_date": "2026-03-14T20:00:00.000Z",
    "process_date": "2026-03-14",
    "product_id": "PRD-ACC",
    "product_type": "Tarjeta Crédito",
    "transaction_type": "Purchase",
    "transaction_category": "Entertainment",
    "amount": "912.4",
    "currency": "USD",
    "amount_usd": None,
    "channel": "POS",
    "merchant_name": "Cine Premium",
    "merchant_category": "Entertainment",
    "origin": "historical",
    "payment_method": None,
    "description": None,
    "counterparty": None,
    "related_product_id": None,
    "scheduled_payment_id": None,
    "balance_after": None,
    "flagged_as_fraud": True,
    "status": {
        "status": "Approved",
        "status_description": "Concluída com sucesso.",
        "completed": True,
        "response_code": "00",
        "reason_code": None,
        "reason": None,
    },
    "location": {
        "summary": "Maquininha (POS) em Cine Premium: São Paulo",
        "city": "São Paulo",
        "country": "Brazil",
        "coordinates": None,
        "branch": None,
    },
}


def test_node_detail_parses_and_ignores_unknown_fields():
    t = TransactionDetailPolicyView.model_validate(NODE_DETAIL)
    assert t.amount == Decimal("912.4")
    assert t.flagged_as_fraud is True
    assert t.transaction_date.tzinfo is not None


def test_llm_view_strips_risk_fields():
    view = TransactionDetailPolicyView.model_validate(NODE_DETAIL).llm_view()
    assert type(view) is TransactionDetailLLMView
    assert "flagged_as_fraud" not in view.model_dump()
    assert "fraud_score" not in view.model_dump()


def test_missing_required_field_is_rejected():
    broken = {k: v for k, v in NODE_DETAIL.items() if k != "status"}
    with pytest.raises(ValidationError):
        TransactionDetailPolicyView.model_validate(broken)


def test_balances_llm_view_masks_numbers():
    b = Balances.model_validate(
        {
            "accounts": [
                {
                    "product_id": "PRD-1",
                    "product_type": "Cuenta Corriente",
                    "product_number": "8115899730",
                    "currency": "COP",
                    "status": "Active",
                    "balance": "8801675.81",
                }
            ],
            "credit_cards": [],
            "loans": [],
            "totals_by_currency": [],
            "net_worth_usd": "2288.44",
        }
    )
    assert b.llm_view()["accounts"][0]["product_number"] == "•••• 9730"


def test_last4():
    assert last4("4429661823154947") == "•••• 4947"
    assert last4(None) is None


def test_query_params_use_node_names():
    q = TransactionQuery(date_from=date(2026, 6, 1), date_to=date(2026, 6, 30), status="Declined")
    assert q.params() == {
        "from": "2026-06-01", "to": "2026-06-30", "status": "Declined", "limit": "20", "offset": "0"
    }


def test_query_limits():
    with pytest.raises(ValidationError):
        TransactionQuery(limit=51)
    with pytest.raises(ValidationError):
        TransactionQuery(date_from=date(2026, 6, 2), date_to=date(2026, 6, 1))


def test_transfer_needs_exactly_one_destination():
    with pytest.raises(ValidationError):
        TransferDestination()
    with pytest.raises(ValidationError):
        TransferDestination(to_product_id="PRD-1", to_account_number="123")


def test_payment_destination_must_match_method():
    with pytest.raises(ValidationError):
        PaymentRequest(
            method="bill_payment",
            source_product_id="PRD-1",
            amount=Decimal("10"),
            destination=TransferDestination(to_product_id="PRD-2"),
        )


@pytest.mark.parametrize("amount", ["0", "-5", "10.001"])
def test_payment_amount_is_positive_with_cents(amount):
    with pytest.raises(ValidationError):
        PaymentRequest(
            method="transfer",
            source_product_id="PRD-1",
            amount=Decimal(amount),
            destination=TransferDestination(to_product_id="PRD-2"),
        )


def test_payment_body_is_node_flat_shape():
    req = PaymentRequest(
        method="bill_payment",
        source_product_id="PRD-1",
        amount=Decimal("150.25"),
        currency="USD",
        destination=BillDestination(barcode="1" * 44, biller_name="Luz"),
    )
    assert req.endpoint() == "bill-payments"
    assert req.body() == {
        "source_product_id": "PRD-1",
        "amount": Decimal("150.25"),
        "currency": "USD",
        "barcode": "1" * 44,
        "biller_name": "Luz",
    }


def test_payment_result_parses_node_preview():
    r = PaymentResult.model_validate(
        {
            "transaction_id": None,
            "transaction_date": "2026-09-28T12:00:00.000Z",
            "method": "transfer",
            "transaction_type": "Transfer",
            "amount": "100",
            "currency": "USD",
            "source": {
                "product_id": "PRD-1",
                "product_type": "Cuenta Corriente",
                "currency": "USD",
                "debited_amount": "100",
                "balance_after": "1400",
            },
            "exchange": {"from": "USD", "to": "COP", "rate": "4000", "rate_date": "2026-06-17"},
            "counterparty": {
                "type": "external", "name": "Ana", "account_number": "9", "international": True
            },
            "credited": None,
            "status": "Approved",
            "status_description": "Concluída com sucesso.",
            "completed": True,
            "response_code": "00",
            "reason_code": None,
            "reason": None,
            "decline_detail": None,
            "preview": True,
        }
    )
    assert r.preview and r.exchange is not None and r.exchange.from_currency == "USD"
    assert "account_number" not in r.counterparty.model_dump()
