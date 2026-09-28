"""The chat service against a live Node, with a scripted model (deterministic). Not run by
default; needs a Node API with the dataset loaded:

    BANK_BASE_URL=http://localhost:3000 EVAL_SERVICE_KEY=demo-service-key pytest -m node tests/live

Covers the M3 smoke run: sessions checked by Node, reads, a payment previewed, confirmed,
executed and read back from Node, a rejection, Node's 422, and Node failures handing off.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_backend.api.app import create_app
from ai_backend.bank.faults import BankFault, FaultyBankClient
from ai_backend.settings import Settings
from tests.scripted_llm import ScriptedChatModel, answer, tool_call

pytestmark = pytest.mark.node
ROOT = Path(__file__).parents[2]
BASE, KEY = os.environ.get("BANK_BASE_URL"), os.environ.get("EVAL_SERVICE_KEY")
FRANCISCO = "CLI-7T6B34S2O9UL"
CHECKING, SAVINGS, CREDIT_CARD = "PRD-IFCGYI99EXAH", "PRD-TQ2IKKDV7YN9", "PRD-8RC6ZKX1BIWI"


class NodeChat:
    def __init__(self, script, faults=()) -> None:
        if not BASE or not KEY:
            pytest.skip("set BANK_BASE_URL and EVAL_SERVICE_KEY")
        settings = Settings(
            _env_file=None,
            bank_mode="http",
            bank_base_url=BASE,
            db_url="memory://",
            anthropic_api_key="unused",  # the scripted model replaces the real one
            models_config_path=ROOT / "config" / "models.yaml",
            policy_config_path=ROOT / "config" / "policy.yaml",
        )
        self.llm = ScriptedChatModel(script=list(script))
        self.client = TestClient(create_app(settings, llm=self.llm))
        self.faults = list(faults)

    def __enter__(self) -> NodeChat:
        self.client.__enter__()
        service = self.client.app.state.ai.service
        if self.faults:
            service.bank = FaultyBankClient(service.bank, self.faults)
        r = httpx.post(
            f"{BASE}/auth/test-sessions",
            json={"customer_id": FRANCISCO},
            headers={"x-service-key": KEY},
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        return self

    def __exit__(self, *exc) -> None:
        self.client.__exit__(*exc)

    def post(self, **body) -> httpx.Response:
        return self.client.post("/v1/chat", json=body, headers=self.headers)

    def node_transaction(self, transaction_id: str) -> dict:
        r = httpx.get(
            f"{BASE}/api/customers/{FRANCISCO}/transactions/{transaction_id}",
            headers=self.headers,
        )
        r.raise_for_status()
        return r.json()


def test_read_path_against_node():
    with NodeChat([tool_call("get_balances"), answer("Tienes varias cuentas en USD.")]) as c:
        body = c.post(message="¿Cuánto dinero tengo en mis cuentas?").json()
        assert body["status"] == "answered"
        tool_result = c.llm.calls[1][-1].content
        assert CHECKING in tool_result and "bank_data" in tool_result


def test_payment_confirmed_executes_once_in_node_and_is_verified():
    pay = {"source_product_id": CHECKING, "amount": 1.25, "to_product_id": SAVINGS}
    with NodeChat([tool_call("transfer_money", pay)]) as c:
        body = c.post(message="Quiero pasar 1,25 dólares a mi cuenta de ahorro").json()
        assert body["status"] == "awaiting_confirmation", body
        assert body["pending_action"]["preview"]["preview"] is True
        done = c.post(
            conversation_id=body["conversation_id"],
            confirmation={"action_id": body["pending_action"]["action_id"], "decision": "approve"},
        ).json()
        assert done["message"].startswith("Listo"), done
        transaction_id = done["message"].rsplit("Comprobante: ", 1)[1].rstrip(".")
        recorded = c.node_transaction(transaction_id)  # Node's own record, with the same token
        assert recorded["origin"] == "simulated" and recorded["payment_method"] == "transfer"
        assert Decimal(str(recorded["amount"])) == Decimal("1.25")
        assert recorded["status"]["status"] == "Approved"


def test_rejected_payment_is_not_executed_in_node():
    pay = {"source_product_id": CHECKING, "amount": 1.50, "to_product_id": SAVINGS}
    with NodeChat([tool_call("transfer_money", pay)]) as c:
        before = httpx.get(
            f"{BASE}/api/customers/{FRANCISCO}/transactions",
            params={"origin": "simulated", "limit": 1},
            headers=c.headers,
        ).json()["total"]
        body = c.post(message="Quiero pasar 1,50 dólares a mi ahorro").json()
        done = c.post(
            conversation_id=body["conversation_id"],
            confirmation={"action_id": body["pending_action"]["action_id"], "decision": "reject"},
        ).json()
        assert "cancel" in done["message"].lower()
        after = httpx.get(
            f"{BASE}/api/customers/{FRANCISCO}/transactions",
            params={"origin": "simulated", "limit": 1},
            headers=c.headers,
        ).json()["total"]
        assert after == before


def test_node_422_goes_back_to_the_model():
    bad = {"source_product_id": CREDIT_CARD, "amount": 1, "to_product_id": SAVINGS}
    with NodeChat([tool_call("transfer_money", bad), answer("La tarjeta no sirve para eso.")]) as c:
        c.post(message="Quiero transferir 1 dólar desde mi tarjeta de crédito")
        assert '"code": "INVALID_REQUEST"' in c.llm.calls[-1][-1].content


@pytest.mark.parametrize("fault", ["timeout", "error_500"])
def test_node_failures_give_a_safe_message_and_a_handoff(fault):
    faults = [BankFault(method="get_balances", fault=fault)]
    with NodeChat([tool_call("get_balances")], faults=faults) as c:
        body = c.post(message="¿Cuánto dinero tengo en mis cuentas?").json()
        assert body["status"] == "handed_off" and "HND-" in body["message"]
        handoff = c.client.get(
            f"/v1/handoffs/{body['handoff']['handoff_id']}", headers=c.headers
        ).json()
        assert handoff["reason_codes"] == ["BANK_UNAVAILABLE"]


def test_logout_in_node_ends_the_chat_session():
    with NodeChat([]) as c:
        httpx.delete(f"{BASE}/auth/sessions/current", headers=c.headers)
        r = c.post(message="¿Cuánto dinero tengo?")
        assert r.status_code == 401 and c.llm.calls == []
