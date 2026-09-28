"""Smoke run of the whole Compose stack over HTTP, with the real agent model. Not run by default:

    AI_BASE_URL=http://localhost:8000 BANK_BASE_URL=http://localhost:3000 \\
      EVAL_SERVICE_KEY=demo-service-key pytest -m "node and llm" tests/live/test_stack_smoke.py -s

The customer logs in at Node (like the frontend), talks to the AI container, and the payment
is then checked in Node with the same token.
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = [pytest.mark.node, pytest.mark.llm]
AI = os.environ.get("AI_BASE_URL")
NODE, KEY = os.environ.get("BANK_BASE_URL"), os.environ.get("EVAL_SERVICE_KEY")
FRANCISCO = "CLI-7T6B34S2O9UL"  # checking •••• 4234, savings •••• 1585 (USD)


@pytest.fixture
def headers() -> dict[str, str]:
    if not (AI and NODE and KEY):
        pytest.skip("set AI_BASE_URL, BANK_BASE_URL and EVAL_SERVICE_KEY")
    r = httpx.post(
        f"{NODE}/auth/test-sessions",
        json={"customer_id": FRANCISCO},
        headers={"x-service-key": KEY},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def chat(headers: dict[str, str], **body) -> dict:
    r = httpx.post(f"{AI}/v1/chat", json=body, headers=headers, timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    print(f"\n  [{data['status']}] {data['message']}")
    return data


def test_health_and_cors():
    if not AI:
        pytest.skip("set AI_BASE_URL")
    health = httpx.get(f"{AI}/v1/health").json()
    assert health["status"] == "ok", health
    preflight = httpx.options(
        f"{AI}/v1/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_transfer_through_the_stack(headers):
    first = chat(
        headers,
        message="Quiero transferir 5 dólares de mi cuenta corriente terminada en 4234 a mi "
        "cuenta de ahorro terminada en 1585",
    )
    assert first["status"] == "awaiting_confirmation", first["message"]
    done = chat(headers, conversation_id=first["conversation_id"], message="sí")
    assert done["status"] == "answered" and "TRX-" in done["message"]
    transaction_id = done["message"].rsplit(": ", 1)[1].rstrip(".")
    recorded = httpx.get(
        f"{NODE}/api/customers/{FRANCISCO}/transactions/{transaction_id}", headers=headers
    ).json()
    assert recorded["status"]["status"] == "Approved" and recorded["amount"] == 5

    trace = httpx.get(
        f"{AI}/v1/conversations/{first['conversation_id']}/trace", headers=headers
    ).json()["events"]
    nodes = [e["node"] for e in trace]
    assert {"prepare_write", "execute_write", "verify"} <= set(nodes)


def test_question_in_portuguese_through_the_stack(headers):
    body = chat(headers, message="Quais foram minhas últimas três transações?")
    assert body["status"] == "answered" and body["language"] == "pt"
