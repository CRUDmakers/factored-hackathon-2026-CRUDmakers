"""M1 acceptance with the real agent model (from .env) on the real fixture. Not run by default:

    pytest -m llm tests/live -s

Answers vary between runs, so the assertions check grounding (the right tool, the right facts,
the right language), not wording. `-s` prints each answer for review.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_backend.api.app import create_app
from ai_backend.settings import Settings

pytestmark = pytest.mark.llm
ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "eval" / "fixtures" / "data"


def _run(customer: str, today: str, message: str):
    if not (FIXTURE / "manifest.json").exists():
        pytest.skip("run `python -m eval.fixtures.extract`")
    settings = Settings(
        _env_file=ROOT / ".env",
        bank_mode="fake",
        bank_fixture_dir=FIXTURE,
        db_url="memory://",
        clock_override=datetime.fromisoformat(today).replace(hour=12, tzinfo=UTC),
        models_config_path=ROOT / "config" / "models.yaml",
        policy_config_path=ROOT / "config" / "policy.yaml",
    )
    with TestClient(create_app(settings)) as client:
        state = client.app.state.ai
        if state.service is None:
            pytest.skip(f"agent model not configured: {state.service_problem}")
        token = state.bank.issue_test_session(customer).token.get_secret_value()
        headers = {"Authorization": f"Bearer {token}"}
        body = client.post("/v1/chat", json={"message": message}, headers=headers).json()
        events = client.get(
            f"/v1/conversations/{body['conversation_id']}/trace", headers=headers
        ).json()["events"]
    tools = [e["tool"] for e in events if e["node"] == "tool"]
    agent = [e for e in events if e["node"] == "agent"]
    print(f"\n[{customer} {today}] {message}\n  tools={tools}\n  → {body['message']}")
    print(f"  tokens_in={[e.get('tokens_in') for e in agent]} "
          f"latency_ms={sum(e['duration_ms'] for e in events):.0f}")
    return body, tools


def test_pt_approved_purchase_yesterday():
    body, tools = _run(
        "CLI-EF70WD91TBJQ",
        "2026-06-12",
        "Minha compra de ontem no Laboratorio Central foi aprovada?",
    )
    assert body["status"] == "answered" and body["language"] == "pt"
    assert "search_transactions" in tools
    assert re.search(r"aprovad", body["message"], re.I)
    assert re.search(r"54[.,]12", body["message"])


def test_es_declined_payment_reason():
    body, tools = _run(
        "CLI-25NDK326VNE4", "2026-05-26", "¿Por qué rechazaron mi pago a Empresa Telefónica?"
    )
    assert body["status"] == "answered" and body["language"] == "es"
    assert set(tools) & {"search_transactions", "get_transaction"}
    assert re.search(r"51|fondos insuficientes|saldo insuficiente", body["message"], re.I)


def test_es_ambiguous_transfer_is_clarified_or_fully_answered():
    body, tools = _run("CLI-7T6B34S2O9UL", "2026-06-18", "¿Pasó mi transferencia de ayer?")
    assert body["status"] == "answered" and body["language"] == "es"
    assert "search_transactions" in tools
    # Two transfers yesterday: either ask which one, or cover both amounts.
    asks = "?" in body["message"]
    both = re.search(r"8[.,]?973", body["message"]) and re.search(r"7[.,]?541", body["message"])
    assert asks or both
