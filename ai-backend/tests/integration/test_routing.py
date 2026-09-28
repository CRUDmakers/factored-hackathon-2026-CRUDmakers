"""Classifier triage in the graph (M4): direct handoff, flag, refusal, clarify, repeat contact.

A stub classifier returns scripted predictions; the thresholds come from config/policy.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_backend.api.app import create_app
from ai_backend.classifier.predict import Prediction
from tests.conftest import CUSTOMER_A, CUSTOMER_B
from tests.integration.test_agent import _settings
from tests.scripted_llm import ScriptedChatModel, answer

THRESHOLDS = {
    "human_confidence_tau": 0.18,
    "human_direct_tau": 0.63,
    "out_of_scope_min_confidence": 0.6,
}


@dataclass
class StubClassifier:
    predictions: list[Prediction]
    meta: dict = field(default_factory=lambda: {"thresholds": THRESHOLDS, "features": "stub"})

    def predict(self, text: str, tau: float) -> Prediction:
        return self.predictions.pop(0)


def pred(route="answer", confidence=0.9, p_human=0.0, intent="balance") -> Prediction:
    return Prediction(route, confidence, p_human, intent, 0.9)


HUMAN_DIRECT = pred("human", 0.95, 0.95, "other")
HUMAN_FLAG = pred("answer", 0.6, THRESHOLDS["human_confidence_tau"], "tx_status")
OOS = pred("out_of_scope", 0.95, 0.01, "other")
OOS_UNSURE = pred("out_of_scope", THRESHOLDS["out_of_scope_min_confidence"] - 0.05, 0.01, "other")
CLARIFY = pred("clarify", 0.8, 0.01, "other")
ANSWER = pred("answer", 0.9, 0.01, "balance")


class Routed:
    def __init__(self, predictions, script=()) -> None:
        self.llm = ScriptedChatModel(script=list(script))
        self.client = TestClient(
            create_app(_settings(), llm=self.llm, classifier=StubClassifier(list(predictions)))
        )

    def __enter__(self) -> Routed:
        self.client.__enter__()
        self.state = self.client.app.state.ai
        return self

    def __exit__(self, *exc) -> None:
        self.client.__exit__(*exc)

    def token(self, customer: str = CUSTOMER_A) -> str:
        return self.state.bank.issue_test_session(customer).token.get_secret_value()

    def say(self, token: str, message: str, conversation_id: str | None = None) -> dict:
        body = {"message": message}
        if conversation_id:
            body["conversation_id"] = conversation_id
        r = self.client.post("/v1/chat", json=body, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        return r.json()

    def handoff(self, token: str, body: dict) -> dict:
        return self.client.get(
            f"/v1/handoffs/{body['handoff']['handoff_id']}",
            headers={"Authorization": f"Bearer {token}"},
        ).json()


def test_confident_human_route_hands_off_without_the_model():
    with Routed([HUMAN_DIRECT]) as r:
        t = r.token()
        body = r.say(t, "Quiero hablar con una persona ya")
        assert body["status"] == "handed_off" and r.llm.calls == []
        h = r.handoff(t, body)
        assert h["reason_codes"] == ["HUMAN_ROUTE"]
        assert h["customer_message"] == "Quiero hablar con una persona ya"
        assert h["request_summary"]["generated_by"] == "system"


def test_possible_human_is_flagged_to_the_agent_which_still_answers():
    with Routed([HUMAN_FLAG], [answer("Tu transferencia fue aprobada.")]) as r:
        body = r.say(r.token(), "¿Qué pasó con mi transferencia?")
        assert body["status"] == "answered"
        system = r.llm.calls[0][0].content
        assert "## Routing note" in system and "handoff_to_human" in system


def test_confident_out_of_scope_is_refused_without_the_model():
    with Routed([OOS]) as r:
        body = r.say(r.token(), "Quero investir em ações")
        assert body["status"] == "refused" and r.llm.calls == []
        assert body["language"] == "pt" and "canais oficiais" in body["message"]


def test_unsure_out_of_scope_goes_to_the_agent():
    with Routed([OOS_UNSURE], [answer("No puedo ayudarte con inversiones.")]) as r:
        body = r.say(r.token(), "¿Qué hago con mis ahorros?")
        assert body["status"] == "answered" and len(r.llm.calls) == 1
        assert "## Routing note" not in r.llm.calls[0][0].content


def test_clarify_hints_then_hands_off_after_two_in_a_row():
    script = [answer("¿Qué quieres hacer?"), answer("¿Cuál transferencia?")]
    with Routed([CLARIFY, CLARIFY, CLARIFY], script) as r:
        t = r.token()
        first = r.say(t, "Necesito ayuda")
        assert "lack key details" in r.llm.calls[0][0].content
        r.say(t, "con una cosa", first["conversation_id"])
        third = r.say(t, "eso", first["conversation_id"])
        assert third["status"] == "handed_off" and len(r.llm.calls) == 2
        assert r.handoff(t, third)["reason_codes"] == ["LIMIT_REACHED"]


def test_a_clear_request_resets_the_clarify_count():
    script = [
        answer("¿Qué necesitas?"),
        answer("Tienes 1.500 USD."),
        answer("¿Cuál?"),
        answer("¿Qué cuenta?"),
    ]
    with Routed([CLARIFY, ANSWER, CLARIFY, CLARIFY], script) as r:
        t = r.token()
        c = r.say(t, "Hola")["conversation_id"]
        for message in ("¿Cuánto tengo en la cuenta corriente?", "¿y la otra?", "esa"):
            assert r.say(t, message, c)["status"] == "answered"


def test_repeat_contact_hands_off_on_the_third_conversation():
    follow = pred("human", 0.3, 0.1, "follow_up")  # below both human thresholds
    script = [answer("Lo reviso."), answer("Lo reviso otra vez.")]
    with Routed([follow, follow, follow], script) as r:
        t = r.token()
        for _ in range(2):
            assert r.say(t, "¿Y mi reembolso?")["status"] == "answered"
        third = r.say(t, "¿Y mi reembolso? otra vez")
        assert third["status"] == "handed_off" and len(r.llm.calls) == 2
        assert r.handoff(t, third)["reason_codes"] == ["REPEAT_CONTACT"]


def test_repeat_contact_is_per_customer_and_ignores_routine_intents():
    follow = pred("answer", 0.8, 0.0, "follow_up")
    balance = pred("answer", 0.9, 0.0, "balance")
    predictions = [follow, follow, follow, balance, balance, balance]
    script = [answer("ok")] * 6
    with Routed(predictions, script) as r:
        a, b = r.token(CUSTOMER_A), r.token(CUSTOMER_B)
        r.say(a, "reembolso 1")
        r.say(a, "reembolso 2")
        assert r.say(b, "reembolso de otro cliente")["status"] == "answered"
        for i in range(3):  # routine questions never count as repeat contact
            assert r.say(a, f"saldo {i}")["status"] == "answered"


def test_repeat_within_one_conversation_is_not_repeat_contact():
    follow = pred("answer", 0.8, 0.0, "follow_up")
    with Routed([follow] * 3, [answer("ok")] * 3) as r:
        t = r.token()
        c = r.say(t, "reembolso")["conversation_id"]
        for _ in range(2):
            assert r.say(t, "¿y el reembolso?", c)["status"] == "answered"


@pytest.mark.parametrize(
    ("classifier_path", "ok", "detail"),
    [(None, True, "disabled"), (Path("/nonexistent/model.joblib"), False, "not trained")],
)
def test_health_reports_the_classifier(classifier_path, ok, detail):
    with TestClient(create_app(_settings(classifier_path=classifier_path))) as client:
        check = client.get("/v1/health").json()["checks"]["classifier"]
        assert check["ok"] is ok and detail in check["detail"]
