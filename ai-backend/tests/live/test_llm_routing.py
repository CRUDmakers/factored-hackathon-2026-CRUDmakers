"""M4 with the real classifier and the real agent model (from .env), on the real fixture.
Not run by default:  pytest -m llm tests/live/test_llm_routing.py -s
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_backend.api.app import create_app
from ai_backend.settings import Settings

pytestmark = pytest.mark.llm
ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "eval" / "fixtures" / "data"
MODEL = ROOT / "models" / "route_classifier.joblib"


@pytest.fixture(scope="module")
def chat():
    if not (FIXTURE / "manifest.json").exists() or not MODEL.exists():
        pytest.skip("needs the fixture and the trained classifier")
    import os

    os.chdir(ROOT)
    settings = Settings(
        _env_file=ROOT / ".env",
        bank_mode="fake",
        bank_fixture_dir=FIXTURE,
        db_url="memory://",
        clock_override=datetime(2026, 6, 18, 12, tzinfo=UTC),
        classifier_path=MODEL,
    )
    with TestClient(create_app(settings)) as client:
        state = client.app.state.ai
        if state.service is None:
            pytest.skip(f"agent model not configured: {state.service_problem}")

        def say(customer: str, message: str) -> tuple[dict, list[dict]]:
            token = state.bank.issue_test_session(customer).token.get_secret_value()
            headers = {"Authorization": f"Bearer {token}"}
            body = client.post("/v1/chat", json={"message": message}, headers=headers).json()
            events = client.get(
                f"/v1/conversations/{body['conversation_id']}/trace", headers=headers
            ).json()["events"]
            route = next((e["outcome"] for e in events if e["node"] == "route"), None)
            agent_calls = sum(e["node"] == "agent" for e in events)
            print(f"\n  {message}\n  {route} | agent calls={agent_calls}")
            print(f"  [{body['status']}] {body['message'][:160]}")
            return body, events

        yield say


def _agent_calls(events: list[dict]) -> int:
    return sum(e["node"] == "agent" for e in events)


def test_explicit_request_for_a_person_hands_off_without_the_model(chat):
    body, events = chat("CLI-EF70WD91TBJQ", "Quero falar com um atendente humano agora")
    assert body["status"] == "handed_off" and _agent_calls(events) == 0


def test_investment_question_is_refused_without_the_model(chat):
    body, events = chat("CLI-EF70WD91TBJQ", "Quero investir em ações, o que vocês recomendam?")
    assert body["status"] == "refused" and _agent_calls(events) == 0


def test_balance_question_is_answered(chat):
    body, events = chat("CLI-7T6B34S2O9UL", "¿Cuánto dinero tengo en mis cuentas de ahorro?")
    assert body["status"] == "answered" and _agent_calls(events) >= 1


def test_unrecognized_charge_reaches_a_human(chat):
    body, _ = chat("CLI-25NDK326VNE4", "No reconozco un cargo de 900 dólares en mi tarjeta")
    assert body["status"] == "handed_off"
