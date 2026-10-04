"""PDF reports end to end: the assistant asks for one in a turn, or the app posts to
/v1/reports/{report}; either way the customer downloads a PDF the backend built."""

from __future__ import annotations

import json

from tests.conftest import CUSTOMER_B
from tests.integration.test_agent import Harness
from tests.scripted_llm import ScriptedChatModel, answer, tool_call


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_assistant_asks_for_a_report_and_the_customer_downloads_it():
    def final(messages):
        payload = json.loads(messages[-1].content)
        assert payload["ok"] and payload["data"]["format"] == "pdf"
        return answer("Pronto: seu extrato de junho em PDF está disponível.")

    llm = ScriptedChatModel(
        script=[
            tool_call(
                "generate_report",
                {"report": "account_statement", "date_from": "2026-06-01", "date_to": "2026-06-18"},
            ),
            final,
        ]
    )
    with Harness(llm) as h:
        token = h.login()
        r = h.chat(token, "Quero o extrato de junho em PDF")
        assert r.status_code == 200, r.text
        [ref] = r.json()["files"]
        assert ref["format"] == "pdf" and ref["filename"].endswith(".pdf")

        download = h.client.get(ref["download_url"], headers=_auth(token))
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/pdf"
        assert download.content.startswith(b"%PDF-")
        assert (
            h.client.get(ref["download_url"], headers=_auth(h.login(CUSTOMER_B))).status_code == 404
        )


def test_catalog_lists_every_report_with_its_endpoint():
    with Harness(ScriptedChatModel()) as h:
        reports = h.client.get("/v1/reports").json()["reports"]
        assert {r["report"] for r in reports} == {
            "account_statement",
            "balances",
            "spending",
            "recurring_payments",
            "transaction_receipt",
        }
        receipt = next(r for r in reports if r["report"] == "transaction_receipt")
        assert receipt["parameters"] == ["transaction_id"]
        assert receipt["endpoint"] == "/v1/reports/transaction_receipt"
        assert receipt["title"]["pt"] == "Comprovante de transação"


def test_report_endpoint_builds_a_pdf_for_the_session_customer():
    with Harness(ScriptedChatModel()) as h:
        token = h.login()
        r = h.client.post("/v1/reports/balances", json={"language": "pt"}, headers=_auth(token))
        assert r.status_code == 201, r.text
        [ref] = r.json()["files"]
        assert ref["filename"].startswith("posicao_consolidada_")
        assert h.client.get(ref["download_url"], headers=_auth(token)).status_code == 200


def test_report_endpoint_errors():
    with Harness(ScriptedChatModel()) as h:
        token = h.login()
        post = h.client.post
        assert post("/v1/reports/balances", json={}).status_code == 401
        assert post("/v1/reports/anything", json={}, headers=_auth(token)).status_code == 422

        missing = post("/v1/reports/transaction_receipt", json={}, headers=_auth(token))
        assert missing.status_code == 422 and missing.json()["error"] == "invalid_arguments"

        # Another customer's transaction looks like one that doesn't exist.
        foreign = post(
            "/v1/reports/transaction_receipt",
            json={"transaction_id": "TRX-B1"},
            headers=_auth(token),
        )
        assert foreign.status_code == 404 and foreign.json()["error"] == "not_found"

        review = post(
            "/v1/reports/transaction_receipt",
            json={"transaction_id": "TRX-A4"},
            headers=_auth(token),
        )
        assert review.status_code == 422 and review.json()["error"] == "under_review"

        conv = {"conversation_id": "conv_" + "0" * 32}
        r = post("/v1/reports/balances", json=conv, headers=_auth(token))
        assert r.status_code == 404 and r.json()["error"] == "conversation_not_found"
