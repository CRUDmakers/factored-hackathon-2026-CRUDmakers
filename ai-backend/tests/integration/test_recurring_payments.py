"""Recurring monthly payments: find them, then pay several with one confirmation.

Scripted model and the fake bank. The history is seeded with payments made in May and June;
the conversation happens in July, when both are due again.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from langchain_core.messages import BaseMessage, ToolMessage

from ai_backend.bank.faults import BankFault
from ai_backend.bank.models import BillDestination, PaymentRequest, TransferDestination
from tests.conftest import CUSTOMER_A
from tests.integration.test_payment_flow import Flow
from tests.scripted_llm import answer, tool_call

BARCODE = "23793381286000000000000000000000000000000000"
BILL = PaymentRequest(
    method="bill_payment",
    source_product_id="PRD-ACHK",
    amount=Decimal("50"),
    destination=BillDestination(barcode=BARCODE, biller_name="Luz"),
)
CARD = PaymentRequest(
    method="transfer",
    source_product_id="PRD-ACHK",
    amount=Decimal("100"),
    destination=TransferDestination(to_product_id="PRD-ACC"),
)
JULY = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
ASK = "¿Qué pagos tengo pendientes este mes?"
PAY_ALL = "Págalos todos"


def _seed(f: Flow) -> None:
    """Bill on the 5th and card on the 10th, in May and June; then move the clock to July."""
    bank = f.state.bank
    for month in (5, 6):
        for request, day in ((BILL, 5), (CARD, 10)):
            f.clock.now = datetime(2026, month, day, 9, 0, tzinfo=UTC)
            bank._payment(CUSTOMER_A, request, dry_run=False)
    f.clock.now = JULY
    f.token = f.login()


def _ids(messages: list[BaseMessage]) -> list[str]:
    """The ids get_recurring_payments returned earlier in the conversation."""
    for m in reversed(messages):
        if isinstance(m, ToolMessage) and m.name == "get_recurring_payments":
            data = json.loads(m.content)["data"]
            return [r["recurring_id"] for r in data["expected_this_month"]]
    raise AssertionError("get_recurring_payments was not called")


def pay_all(messages: list[BaseMessage]):
    return tool_call("pay_recurring_payments", {"recurring_ids": _ids(messages)}, "call_pay")


def _tool_result(f: Flow) -> dict:
    return json.loads(f.llm.calls[-1][-1].content)


def _list_then_pay(*after):
    return [
        tool_call("get_recurring_payments"),
        answer("Tienes 2 pagos pendientes: Luz y tu tarjeta."),
        pay_all,
        *after,
    ]


# ---------- the fake bank ----------


def test_fake_bank_finds_payments_made_two_months_in_a_row():
    with Flow([]) as f:
        _seed(f)
        session = f.state.bank.issue_test_session(CUSTOMER_A)
        r = f.client.portal.call(f.state.bank.get_recurring_payments, session, None)
        assert r.month == "2026-07"
        assert [(i.method, i.amount, i.status) for i in r.items] == [
            ("bill_payment", Decimal("50.00"), "due"),
            ("transfer", Decimal("100.00"), "due"),
        ]
        bill, card = r.items
        assert bill.recipient == "Luz" and bill.months == ["2026-05", "2026-06"]
        assert bill.next_due_date == date(2026, 7, 5) and not bill.overdue
        expected = CARD.model_copy(update={"amount": Decimal("100.00"), "currency": "USD"})
        assert card.payment == expected
        assert r.summary.due == 2 and r.summary.due_totals[0].amount == Decimal("150.00")

        june = f.client.portal.call(f.state.bank.get_recurring_payments, session, date(2026, 6, 30))
        assert {i.status for i in june.items} == {"paid"}
        assert [i.due_date for i in june.items] == [date(2026, 6, 5), date(2026, 6, 10)]
        assert june.items[0].next_due_date == date(2026, 7, 5)


# ---------- reading ----------


def test_the_model_lists_what_is_due():
    with Flow([tool_call("get_recurring_payments"), answer("Tienes 2 pagos pendientes.")]) as f:
        _seed(f)
        body = f.ask(ASK)
        assert body["status"] == "answered"
        data = _tool_result(f)["data"]
        assert data["month"] == "2026-07" and data["still_due"] == 2
        assert data["still_due_totals"] == [{"currency": "USD", "amount": "150.00"}]
        expected = data["expected_this_month"]
        assert [(e["due_date"], e["recipient"], e["status"]) for e in expected] == [
            ("2026-07-05", "Luz", "due"),
            ("2026-07-10", None, "due"),
        ]
        first = data["expected_this_month"][0]
        assert first["amount"] == "50.00" and first["paid_on"] is None
        assert "payment" not in first  # account numbers and barcodes stay out of the prompt


# ---------- paying them all ----------


def test_pay_all_asks_once_then_executes_and_verifies_each():
    with Flow(_list_then_pay()) as f:
        _seed(f)
        listed = f.ask(ASK)
        body = f.ask(PAY_ALL, listed["conversation_id"])
        assert body["status"] == "awaiting_confirmation"
        summary = body["pending_action"]["summary"]
        assert [line for line in summary.splitlines() if line] == [
            "Pagar estos 2 pagos recurrentes:",
            "- 50,00 USD a Luz (desde cuenta corriente •••• 2233)",
            "- 100,00 USD a tu tarjeta de crédito (desde cuenta corriente •••• 2233)",
            "Total: 150,00 USD.",
            "¿Confirmas?",
        ]
        assert body["message"] == summary
        assert f.balance("PRD-ACHK") == Decimal("1200.00")  # previews recorded nothing

        done = f.confirm(body).json()
        lines = [line for line in done["message"].splitlines() if line]
        assert lines[0] == "Resultado de los pagos:"
        assert len(lines) == 3 and all(line.startswith("- Listo") for line in lines[1:])
        assert f.balance("PRD-ACHK") == Decimal("1050.00")
        assert f.balance("PRD-ACC") == Decimal("900.50")  # 1200.50 - 2 × 100 seeded - 100
        assert len(f.llm.calls) == 3  # confirming needs no model call

        snapshot = f.state.service.graph.get_state(
            {"configurable": {"thread_id": done["conversation_id"]}}
        )
        actions = snapshot.values["actions"]
        assert [(a["method"], a["status"], a["verified"]) for a in actions] == [
            ("bill_payment", "Approved", True),
            ("transfer", "Approved", True),
        ]
        assert snapshot.values["pending_action"] is None
        nodes = [e["node"] for e in f.events(done)]
        assert nodes.count("execute_write") == 2 and nodes.count("verify") == 2

        session = f.state.bank.issue_test_session(CUSTOMER_A)
        after = f.client.portal.call(f.state.bank.get_recurring_payments, session, None)
        assert {i.status for i in after.items} == {"paid"}


def test_rejecting_the_batch_pays_nothing():
    with Flow(_list_then_pay()) as f:
        _seed(f)
        listed = f.ask(ASK)
        body = f.ask(PAY_ALL, listed["conversation_id"])
        r = f.chat(f.token, "no", body["conversation_id"]).json()
        assert "cancelé" in r["message"]
        assert f.balance("PRD-ACHK") == Decimal("1200.00")
        snapshot = f.state.service.graph.get_state(
            {"configurable": {"thread_id": body["conversation_id"]}}
        )
        assert [a["status"] for a in snapshot.values["actions"]] == ["rejected", "rejected"]


def test_a_payment_declined_during_the_batch_does_not_stop_the_rest():
    with Flow(_list_then_pay()) as f:
        _seed(f)
        listed = f.ask(ASK)
        body = f.ask(PAY_ALL, listed["conversation_id"])
        # The balance drops after the preview: the bill goes through, the card payment doesn't.
        f.state.bank.fixture.products["PRD-ACHK"].current_balance = Decimal("120.00")
        lines = [line for line in f.confirm(body).json()["message"].splitlines() if line]
        assert lines[1].startswith("- Listo")
        assert lines[2].startswith("- El banco rechazó la operación: saldo o límite insuficiente")
        assert f.balance("PRD-ACHK") == Decimal("70.00")


def test_unknown_outcome_hands_off_and_skips_the_rest():
    faults = [BankFault(method="execute_payment", fault="timeout")]
    with Flow(_list_then_pay(), faults=faults) as f:
        _seed(f)
        listed = f.ask(ASK)
        body = f.ask(PAY_ALL, listed["conversation_id"])
        done = f.confirm(body).json()
        assert done["status"] == "handed_off"
        handoff = f.handoff(done)
        assert [a.status for a in handoff.actions_taken] == ["unknown", "cancelled"]
        assert f.balance("PRD-ACHK") == Decimal("1200.00")


# ---------- what the policy stops ----------


def test_a_payment_the_bank_would_decline_goes_back_to_the_model():
    with Flow(_list_then_pay(answer("No alcanza el saldo para la tarjeta."))) as f:
        _seed(f)
        f.state.bank.fixture.products["PRD-ACHK"].current_balance = Decimal("60.00")
        listed = f.ask(ASK)
        body = f.ask(PAY_ALL, listed["conversation_id"])
        assert body["status"] == "answered" and body["pending_action"] is None
        error = _tool_result(f)["error"]
        assert error["code"] == "INSUFFICIENT_FUNDS" and "Saldo disponível" in error["message"]


def test_only_due_payments_can_be_paid():
    script = [
        tool_call("get_recurring_payments"),
        answer("Ya pagaste todo este mes."),
        pay_all,
        answer("Esos pagos ya están hechos este mes."),
    ]
    with Flow(script) as f:
        _seed(f)
        f.clock.now = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)  # both already paid in June
        f.token = f.login()
        listed = f.ask(ASK)
        body = f.ask(PAY_ALL, listed["conversation_id"])
        assert body["pending_action"] is None
        assert _tool_result(f)["error"]["code"] == "not_due"


def test_unknown_ids_are_refused():
    script = [
        tool_call("pay_recurring_payments", {"recurring_ids": ["REC-NOPE"]}),
        answer("No encontré ese pago."),
    ]
    with Flow(script) as f:
        _seed(f)
        body = f.ask(PAY_ALL)
        assert body["pending_action"] is None
        assert _tool_result(f)["error"]["code"] == "not_found"


def test_the_total_must_be_within_the_amount_limit():
    with Flow(_list_then_pay()) as f:
        _seed(f)
        f.state.service.policy = f.state.service.policy.model_copy(
            update={
                "limits": f.state.service.policy.limits.model_copy(
                    update={"write_amount_limit_usd": Decimal("120")}
                )
            }
        )
        listed = f.ask(ASK)
        body = f.ask(PAY_ALL, listed["conversation_id"])
        assert body["status"] == "handed_off"
        assert f.handoff(body).reason_codes == ["AMOUNT_OVER_LIMIT"]
