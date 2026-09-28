"""M2 end to end: preview → confirm → execute → reconcile → verify, and handoffs.

Scripted model, fake bank that behaves like Node, controllable clock and injected faults.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from ai_backend.api.app import create_app
from ai_backend.bank.faults import BankFault, FaultyBankClient
from ai_backend.handoff.models import Handoff
from tests.conftest import CUSTOMER_B, Clock
from tests.integration.test_agent import Harness, _settings
from tests.scripted_llm import ScriptedChatModel, answer, tool_call

PAY_CARD = {"source_product_id": "PRD-ACHK", "amount": 100, "to_product_id": "PRD-ACC"}
ASK_ES = "Quiero pagar 100 dólares de mi tarjeta de crédito desde mi cuenta corriente"


class Flow(Harness):
    """A harness with a movable clock, optional bank faults and payment helpers."""

    def __init__(self, script, faults=(), **settings) -> None:
        self.clock = Clock()
        self.llm = ScriptedChatModel(script=list(script))
        self.client = TestClient(create_app(_settings(**settings), llm=self.llm, clock=self.clock))
        self.faults = list(faults)

    def __enter__(self) -> Flow:
        super().__enter__()
        if self.faults:
            self.state.service.bank = FaultyBankClient(self.state.bank, self.faults)
        self.token = self.login()
        return self

    def ask(self, message: str = ASK_ES, conversation_id: str | None = None) -> dict:
        r = self.chat(self.token, message, conversation_id)
        assert r.status_code == 200, r.text
        return r.json()

    def confirm(self, body: dict, decision: str = "approve", action_id: str | None = None):
        action = action_id or body["pending_action"]["action_id"]
        return self.client.post(
            "/v1/chat",
            json={
                "conversation_id": body["conversation_id"],
                "confirmation": {"action_id": action, "decision": decision},
            },
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def balance(self, product_id: str) -> Decimal:
        return self.state.bank.fixture.products[product_id].current_balance

    def simulated(self) -> list:
        return [t for t in self.state.bank.fixture.transactions.values() if t.origin == "simulated"]

    def handoff(self, body: dict) -> Handoff:
        r = self.client.get(
            f"/v1/handoffs/{body['handoff']['handoff_id']}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert r.status_code == 200, r.text
        return Handoff.model_validate(r.json())

    def events(self, body: dict) -> list[dict]:
        return self.trace(self.token, body["conversation_id"]).json()["events"]


def _tool_error(llm: ScriptedChatModel) -> dict:
    return json.loads(llm.calls[-1][-1].content)["error"]


# ---------- the happy path ----------


def test_preview_then_approve_executes_once_and_verifies():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        assert body["status"] == "awaiting_confirmation"
        pending = body["pending_action"]
        assert pending["summary"].startswith("Pagar 100,00 USD de tu tarjeta de crédito.")
        assert "cuenta corriente •••• 2233" in pending["summary"]
        assert body["message"] == pending["summary"]  # built by code, not by the model
        assert f.simulated() == []  # the preview recorded nothing
        assert len(f.llm.calls) == 1

        r = f.confirm(body)
        done = r.json()
        assert done["status"] == "answered" and done["message"].startswith("Listo")
        assert f.balance("PRD-ACHK") == Decimal("1400.00")
        assert f.balance("PRD-ACC") == Decimal("1100.50")
        [payment] = [t for t in f.simulated() if t.transaction_type == "Payment"]
        assert payment.transaction_id in done["message"]
        assert len(f.llm.calls) == 1  # confirming needs no model call

        nodes = [e["node"] for e in f.events(done)]
        assert nodes[-4:] == ["intake", "execute_write", "verify", "respond"]
        snapshot = f.state.service.graph.get_state(
            {"configurable": {"thread_id": done["conversation_id"]}}
        )
        [action] = snapshot.values["actions"]
        assert action["verified"] is True and action["status"] == "Approved"
        assert snapshot.values["pending_action"] is None


@pytest.mark.parametrize("word", ["sí", "Sim!", "confirmo", "OK"])
def test_free_text_yes_approves(word):
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        done = f.ask(word, body["conversation_id"])
        assert done["message"].startswith("Listo") and len(f.simulated()) == 2


@pytest.mark.parametrize("how", ["button", "no", "Não", "cancelar"])
def test_reject_executes_nothing(how):
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        r = (
            f.confirm(body, "reject")
            if how == "button"
            else f.chat(f.token, how, body["conversation_id"])
        )
        assert "cancel" in r.json()["message"].lower()
        assert f.simulated() == [] and f.balance("PRD-ACHK") == Decimal("1500.00")


def test_confirmation_expires():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        f.clock.advance(seconds=300)
        r = f.confirm(body)
        assert "venció" in r.json()["message"] and f.simulated() == []
        # A second approval finds nothing pending.
        assert "No hay ninguna operación" in f.confirm(body).json()["message"]


def test_moving_on_drops_the_pending_payment():
    script = [tool_call("transfer_money", PAY_CARD), answer("Tienes 1.500,00 USD.")]
    with Flow(script) as f:
        body = f.ask()
        other = f.ask("Mejor dime cuánto tengo en la cuenta corriente", body["conversation_id"])
        assert other["status"] == "answered" and f.simulated() == []
        assert "No hay ninguna operación" in f.confirm(body).json()["message"]


def test_wrong_action_id_keeps_the_payment_pending():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        r = f.confirm(body, action_id="act_forged")
        assert "No hay ninguna operación" in r.json()["message"] and f.simulated() == []
        assert f.confirm(body).json()["message"].startswith("Listo")


def test_confirmation_without_anything_pending():
    with Flow([answer("Hola.")]) as f:
        body = f.ask("Hola, necesito ayuda con mi cuenta")
        r = f.confirm(body, action_id="act_nothing")
        assert "No hay ninguna operación" in r.json()["message"]


def test_parallel_approvals_execute_once():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        service = f.state.service
        confirmation = {"action_id": body["pending_action"]["action_id"], "decision": "approve"}

        async def both():
            return await asyncio.gather(
                *(
                    service.turn(f.token, None, body["conversation_id"], confirmation)
                    for _ in range(2)
                )
            )

        results = f.client.portal.call(both)
        messages = sorted(r.message for r in results)
        assert messages[0].startswith("Listo") and "No hay ninguna" in messages[1]
        assert len([t for t in f.simulated() if t.transaction_type == "Payment"]) == 1


def test_session_ending_before_approval_keeps_the_payment_safe():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        f.state.bank.revoke_session(f.token)
        assert f.confirm(body).status_code == 401
        assert f.simulated() == []


# ---------- previews the policy stops ----------


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ({**PAY_CARD, "amount": 1500.01}, "INSUFFICIENT_FUNDS"),
        ({**PAY_CARD, "source_product_id": "PRD-AOLD"}, "CARD_EXPIRED"),
        (
            {**PAY_CARD, "to_product_id": None, "to_account_number": "0000000000"},
            "INVALID_DESTINATION",
        ),
        ({**PAY_CARD, "to_product_id": "PRD-AINV"}, "INVALID_DESTINATION"),  # 422
        (
            {**PAY_CARD, "source_product_id": "PRD-ACC", "to_product_id": "PRD-ASAV"},
            "INVALID_REQUEST",
        ),  # 422: a credit card can't fund a transfer
        ({**PAY_CARD, "amount": 10.001}, "invalid_arguments"),
    ],
)
def test_denied_previews_go_back_to_the_model(args, code):
    args = {k: v for k, v in args.items() if v is not None}
    script = [tool_call("transfer_money", args), answer("No se puede: …")]
    with Flow(script) as f:
        body = f.ask()
        assert body["status"] == "answered"
        assert _tool_error(f.llm)["code"] == code
        assert f.simulated() == []
        snapshot = f.state.service.graph.get_state(
            {"configurable": {"thread_id": body["conversation_id"]}}
        )
        assert snapshot.values.get("pending_action") is None
        if code == "INVALID_DESTINATION":
            assert snapshot.values["clarifications"] == 1


def test_bad_barcode_is_an_invalid_destination():
    bill = {"source_product_id": "PRD-ACHK", "amount": 10, "barcode": "123"}
    with Flow([tool_call("pay_bill", bill), answer("El código de barras no es válido.")]) as f:
        f.ask("Quiero pagar una factura de 10 dólares")
        assert _tool_error(f.llm)["code"] == "INVALID_DESTINATION"


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({**PAY_CARD, "source_product_id": "PRD-ABLK"}, "PRODUCT_BLOCKED"),  # preview 05
        ({**PAY_CARD, "amount": 6000}, "AMOUNT_OVER_LIMIT"),  # checked before the decline
    ],
)
def test_escalated_previews_hand_off(args, reason):
    with Flow([tool_call("transfer_money", args)]) as f:
        body = f.ask()
        assert body["status"] == "handed_off"
        handoff = f.handoff(body)
        assert handoff.reason_codes == [reason] and f.simulated() == []


def test_two_payments_at_once_only_the_first_is_previewed():
    two = tool_call("transfer_money", PAY_CARD, "w1")
    two.tool_calls.append({"name": "pay_bill", "args": {}, "id": "w2", "type": "tool_call"})
    with Flow([two]) as f:
        body = f.ask()
        assert body["status"] == "awaiting_confirmation"
        assert "tarjeta de crédito" in body["pending_action"]["summary"]


# ---------- the outcome is unknown or doesn't match ----------


def test_lost_response_is_found_by_reconciliation():
    fault = BankFault(method="execute_payment", fault="lost_response")
    with Flow([tool_call("transfer_money", PAY_CARD)], faults=[fault]) as f:
        body = f.ask()
        done = f.confirm(body).json()
        assert done["status"] == "answered" and done["message"].startswith("Listo")
        nodes = [e["node"] for e in f.events(done)]
        assert "reconcile" in nodes and nodes.index("reconcile") < nodes.index("verify")
        assert len([t for t in f.simulated() if t.transaction_type == "Payment"]) == 1


def test_timeout_that_never_executed_hands_off_without_retrying():
    fault = BankFault(method="execute_payment", fault="timeout")
    with Flow([tool_call("transfer_money", PAY_CARD)], faults=[fault]) as f:
        body = f.ask()
        done = f.confirm(body).json()
        assert done["status"] == "handed_off" and f.simulated() == []
        handoff = f.handoff(done)
        assert handoff.reason_codes == ["OUTCOME_UNKNOWN"] and handoff.priority == "high"
        assert handoff.actions_taken[0].status == "unknown"


def test_readback_mismatch_hands_off():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        original = f.state.bank.get_transaction

        async def tampered(session, transaction_id):
            real = await original(session, transaction_id)
            return real.model_copy(update={"amount": Decimal("1000.00")})

        f.state.bank.get_transaction = tampered
        done = f.confirm(body).json()
        assert done["status"] == "handed_off"
        assert f.handoff(done).reason_codes == ["VERIFY_MISMATCH"]


def test_execution_already_marked_goes_to_reconciliation_not_a_second_payment():
    # As after a crash between "executed" being saved and the bank's answer.
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        config = {"configurable": {"thread_id": body["conversation_id"]}}
        graph = f.state.service.graph
        pending = graph.get_state(config).values["pending_action"]
        graph.update_state(config, {"pending_action": {**pending, "executed": True}})
        done = f.confirm(body).json()
        assert done["status"] == "handed_off" and f.simulated() == []
        assert f.handoff(done).reason_codes == ["OUTCOME_UNKNOWN"]


def test_bank_refusing_at_execution_moves_no_money():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        f.state.bank.fixture.products["PRD-ACC"].status = "Closed"  # changed after the preview
        done = f.confirm(body).json()
        assert "rechazó" in done["message"] or "no aceptó" in done["message"]
        assert f.balance("PRD-ACHK") == Decimal("1500.00")


# ---------- handoffs ----------


def test_delinquent_customer_asking_to_renegotiate_hands_off():
    handoff_call = tool_call(
        "handoff_to_human",
        {
            "reason": "debt_arrangement",
            "summary": "Quer renegociar o empréstimo pessoal com 30 dias de atraso.",
            "open_questions": ["Qual parcela o cliente consegue pagar?"],
        },
    )
    with Flow([tool_call("get_balances"), handoff_call]) as f:
        f.token = f.login(CUSTOMER_B)
        body = f.ask("Estou com o empréstimo atrasado, quero renegociar a dívida")
        assert body["status"] == "handed_off" and "HND-" in body["message"]
        h = f.handoff(body)
        assert h.reason_codes == ["DELINQUENT"] and h.priority == "normal"
        assert h.language == "pt" and h.customer_id == CUSTOMER_B
        assert h.request_summary.generated_by == "model:claude-opus-5-5"
        assert h.open_questions.items == ["Qual parcela o cliente consegue pagar?"]
        assert any("30 days past due" in fact.fact for fact in h.verified_facts)
        # The JSON the panel receives validates against the schema.
        Handoff.model_validate_json(h.model_dump_json())


def test_fraud_flagged_transaction_hands_off_urgently():
    script = [
        tool_call("search_transactions", {"merchant": "Cine"}),
        tool_call("get_transaction", {"transaction_id": "TRX-A4"}, "c2"),
    ]
    with Flow(script) as f:
        body = f.ask("¿Qué es este cargo de Cine Premium en mi tarjeta?")
        assert body["status"] == "handed_off"
        h = f.handoff(body)
        assert h.reason_codes == ["FRAUD_RISK"] and h.priority == "high"
        assert h.request_summary.generated_by == "system"
        assert "TRX-A4" in h.evidence.transaction_ids
        assert len(f.llm.calls) == 2  # the model never saw the flagged record's reply


def test_handoffs_are_private_to_their_customer():
    with Flow([tool_call("handoff_to_human", {"reason": "customer_request", "summary": "x"})]) as f:
        body = f.ask("Quiero hablar con una persona, por favor")
        other = f.login(CUSTOMER_B)
        r = f.client.get(
            f"/v1/handoffs/{body['handoff']['handoff_id']}",
            headers={"Authorization": f"Bearer {other}"},
        )
        assert r.status_code == 404


# ---------- failures at each step ----------


@pytest.mark.parametrize(
    ("fault", "code"),
    [("timeout", "bank_unavailable"), ("malformed", "bank_unavailable")],
)
def test_preview_failures_go_back_to_the_model(fault, code):
    faults = [BankFault(method="preview_payment", fault=fault)]
    script = [tool_call("transfer_money", PAY_CARD), answer("El banco no responde ahora.")]
    with Flow(script, faults=faults) as f:
        body = f.ask()
        assert body["status"] == "answered" and _tool_error(f.llm)["code"] == code


def test_unknown_source_product_goes_back_to_the_model():
    args = {**PAY_CARD, "source_product_id": "PRD-NOPE"}
    with Flow([tool_call("transfer_money", args), answer("No encuentro esa cuenta.")]) as f:
        f.ask()
        assert _tool_error(f.llm)["code"] == "not_found"


def test_session_expiring_during_the_preview_asks_to_log_in():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        original = f.state.bank.preview_payment

        async def revoked(session, request):
            f.state.bank.revoke_session(f.token)
            return await original(session, request)

        f.state.bank.preview_payment = revoked
        assert f.chat(f.token, ASK_ES).status_code == 401


def test_amount_limit_uses_the_usd_value_of_other_currencies():
    # 25,000,000 COP × 0.000260 = 6,500 USD: over the 5,000 USD limit.
    args = {"source_product_id": "PRD-BCHK", "amount": 25_000_000, "to_product_id": "PRD-BLOAN"}
    with Flow([tool_call("transfer_money", args)]) as f:
        f.token = f.login(CUSTOMER_B)
        body = f.ask("Quiero pagar 25 millones de pesos de mi préstamo")
        assert f.handoff(body).reason_codes == ["AMOUNT_OVER_LIMIT"]


def test_session_expiring_before_execution_keeps_the_payment_confirmable():
    with Flow([tool_call("transfer_money", PAY_CARD)]) as f:
        body = f.ask()
        original = f.state.bank.execute_payment

        async def revoked(session, request, key):
            f.state.bank.revoke_session(f.token)
            return await original(session, request, key)

        f.state.bank.execute_payment = revoked
        assert f.confirm(body).status_code == 401
        assert f.simulated() == []
        config = {"configurable": {"thread_id": body["conversation_id"]}}
        pending = f.state.service.graph.get_state(config).values["pending_action"]
        assert pending is not None and pending["executed"] is False


def test_reconciliation_that_cannot_reach_the_bank_hands_off():
    faults = [
        BankFault(method="execute_payment", fault="timeout"),
        BankFault(method="list_transactions", fault="error_500"),
    ]
    with Flow([tool_call("transfer_money", PAY_CARD)], faults=faults) as f:
        body = f.ask()
        done = f.confirm(body).json()
        assert f.handoff(done).reason_codes == ["OUTCOME_UNKNOWN"]


def test_readback_failure_hands_off():
    faults = [BankFault(method="get_transaction", fault="timeout")]
    with Flow([tool_call("transfer_money", PAY_CARD)], faults=faults) as f:
        body = f.ask()
        done = f.confirm(body).json()
        assert done["status"] == "handed_off"
        assert f.handoff(done).reason_codes == ["VERIFY_MISMATCH"]
        # The payment did happen; the agent gets the transaction to check.
        assert f.handoff(done).evidence.transaction_ids


def test_session_expiring_mid_turn_is_caught_by_the_policy_gate():
    def expire_then_call(messages):
        f.clock.advance(seconds=901)  # past the 15-minute session
        return tool_call("get_balances")

    with Flow([expire_then_call]) as f:
        assert f.chat(f.token, "¿Cuánto tengo en mis cuentas?").status_code == 401


def test_empty_model_answer_hands_off():
    with Flow([answer("   ")]) as f:
        body = f.ask("Hola, tengo una duda sobre mi cuenta")
        assert f.handoff(body).reason_codes == ["ASSISTANT_FAILURE"]
