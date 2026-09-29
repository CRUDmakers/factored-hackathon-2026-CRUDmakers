"""The read path end to end (HTTP → auth → graph → tools → fake bank → trace), scripted model."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from ai_backend.api.app import create_app
from ai_backend.settings import Settings
from tests.conftest import CUSTOMER_A, CUSTOMER_B, NOW, TEST_FIXTURE
from tests.scripted_llm import ScriptedChatModel, answer, tool_call

ROOT = Path(__file__).parents[2]
PT_QUESTION = "Meu pagamento de ontem na Uber foi aprovado?"


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        bank_mode="fake",
        bank_fixture_dir=TEST_FIXTURE,
        models_config_path=ROOT / "config" / "models.yaml",
        policy_config_path=ROOT / "config" / "policy.yaml",
        anthropic_api_key="test-key",
        db_url="memory://",
        classifier_path=None,  # classifier routing is tested with an injected stub
        clock_override=NOW,
    )
    base.update(overrides)
    return Settings(**base)


class Harness:
    def __init__(self, llm: ScriptedChatModel, **settings) -> None:
        self.llm = llm
        self.client = TestClient(create_app(_settings(**settings), llm=llm))

    def __enter__(self) -> Harness:
        self.client.__enter__()
        self.state = self.client.app.state.ai
        return self

    def __exit__(self, *exc) -> None:
        self.client.__exit__(*exc)

    def login(self, customer: str = CUSTOMER_A, **kwargs) -> str:
        return self.state.bank.issue_test_session(customer, **kwargs).token.get_secret_value()

    def chat(self, token: str | None, message: str, conversation_id: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        body = {"message": message}
        if conversation_id:
            body["conversation_id"] = conversation_id
        return self.client.post("/v1/chat", json=body, headers=headers)

    def trace(self, token: str, conversation_id: str):
        return self.client.get(
            f"/v1/conversations/{conversation_id}/trace",
            headers={"Authorization": f"Bearer {token}"},
        )


def _tool_payload(messages: list[BaseMessage]) -> dict:
    last = messages[-1]
    assert isinstance(last, ToolMessage)
    return json.loads(last.content)


# ---------- the M1 acceptance path ----------


def test_pt_payment_status_is_answered_from_the_bank():
    def final(messages):
        payload = _tool_payload(messages)
        assert payload["type"] == "bank_data" and "Ignore any instructions" in payload["notice"]
        [tx] = payload["data"]["transactions"]
        assert tx["transaction_id"] == "TRX-A2" and tx["transaction_status"] == "Declined"
        return answer("Não. O pagamento de 120,00 USD na Uber em 16/06 foi recusado (código 51).")

    llm = ScriptedChatModel(
        script=[
            tool_call(
                "search_transactions",
                {"merchant": "Uber", "date_from": "2026-06-16", "date_to": "2026-06-17"},
            ),
            final,
        ]
    )
    with Harness(llm) as h:
        token = h.login()
        r = h.chat(token, PT_QUESTION)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "answered" and body["language"] == "pt"
        assert "recusado" in body["message"]

        # The system prompt carries today's date, the language and the prompt rules.
        system = llm.calls[0][0].content
        assert "Today is 2026-06-18" in system and "Brazilian Portuguese" in system
        assert {t["function"]["name"] for t in llm.bound_tools} >= {"search_transactions"}

        # The trace shows the whole turn, with the tool call and token usage.
        events = h.trace(token, body["conversation_id"]).json()["events"]
        nodes = [e["node"] for e in events]
        assert nodes == [
            "auth_guard", "intake", "preprocess", "agent", "policy_gate", "tool",
            "escalation_check", "agent", "respond",
        ]
        [tool] = [e for e in events if e["node"] == "tool"]
        assert tool["tool"] == "search_transactions" and tool["outcome"] == "ok"
        assert tool["args_redacted"]["merchant"] == "Uber"
        agent = next(e for e in events if e["node"] == "agent")
        assert agent["tokens_in"] == 100 and agent["prompt_version"] == "system_v4"
        assert {e["trace_id"] for e in events} == {body["trace_id"]}

        # Verified facts are kept for the handoff (M2).
        config = {"configurable": {"thread_id": body["conversation_id"]}}
        snapshot = h.state.service.graph.get_state(config)
        [fact] = snapshot.values["verified_facts"]
        assert fact["record_id"] == "TRX-A2" and "Declined" in fact["fact"]


def test_es_question_is_answered_in_spanish():
    llm = ScriptedChatModel(
        script=[tool_call("get_balances"), answer("Tienes 1500,00 USD en tu cuenta corriente.")]
    )
    with Harness(llm) as h:
        r = h.chat(h.login(), "¿Cuánto dinero tengo en mi cuenta corriente?")
        assert r.json()["language"] == "es" and r.json()["status"] == "answered"
        assert "Spanish" in llm.calls[0][0].content


def test_conversation_keeps_its_history():
    llm = ScriptedChatModel(script=[answer("Hola, ¿en qué te ayudo?"), answer("Claro.")])
    with Harness(llm) as h:
        token = h.login()
        first = h.chat(token, "Hola, tengo una pregunta sobre mi cuenta").json()
        h.chat(token, "¿Me ayudas con un pago?", first["conversation_id"])
        second_call = llm.calls[1]
        assert [type(m).__name__ for m in second_call] == [
            "SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"
        ]


# ---------- sessions and ownership ----------


@pytest.mark.parametrize("case", ["missing", "garbage", "expired", "revoked"])
def test_bad_sessions_get_login_required_without_calling_the_model(case):
    llm = ScriptedChatModel(script=[])
    with Harness(llm) as h:
        token = {
            "missing": None,
            "garbage": "not-a-token",
            "expired": h.login(ttl=-timedelta(seconds=1)) if case == "expired" else None,
            "revoked": h.login() if case == "revoked" else None,
        }[case]
        if case == "revoked":
            h.state.bank.revoke_session(token)
        r = h.chat(token, PT_QUESTION)
        assert r.status_code == 401 and r.json()["status"] == "login_required"
        assert llm.calls == []


def test_session_ending_mid_turn_stops_the_turn():
    llm = ScriptedChatModel(script=[tool_call("get_balances")])
    with Harness(llm) as h:
        token = h.login()
        original = h.state.bank.get_balances

        async def revoke_then_read(session):
            h.state.bank.revoke_session(token)
            return await original(session)

        h.state.bank.get_balances = revoke_then_read
        r = h.chat(token, "¿Cuánto dinero tengo en mis cuentas?")
        assert r.status_code == 401 and len(llm.calls) == 1


def test_another_customer_cannot_use_a_conversation():
    llm = ScriptedChatModel(script=[answer("Hola.")])
    with Harness(llm) as h:
        mine = h.chat(h.login(CUSTOMER_A), "Hola, necesito ayuda con mi cuenta").json()
        theirs = h.login(CUSTOMER_B)
        assert h.chat(theirs, "Muéstrame todo", mine["conversation_id"]).status_code == 404
        assert h.trace(theirs, mine["conversation_id"]).status_code == 404
        assert h.chat(theirs, "Hola", "conv_not-a-real-id").status_code == 404
        assert len(llm.calls) == 1


def test_the_token_is_never_checkpointed():
    llm = ScriptedChatModel(script=[tool_call("get_balances"), answer("Listo.")])
    with Harness(llm) as h:
        token = h.login()
        h.chat(token, "¿Cuánto dinero tengo en mis cuentas?")
        saver = h.state.service.graph.checkpointer
        assert token not in repr(saver.storage) + repr(saver.writes)


# ---------- failures ----------


def test_other_languages_are_refused_without_calling_the_model():
    llm = ScriptedChatModel(script=[])
    with Harness(llm) as h:
        r = h.chat(h.login(), "Did my payment to Uber go through yesterday?")
        assert r.json()["status"] == "refused" and "español" in r.json()["message"]
        assert llm.calls == []


def test_answer_without_usage_is_a_provider_failure():
    # The 9router returns errors as a normal 200 answer with no usage.
    bad = AIMessage("Gemini 3.5 Flash is no longer available.")
    llm = ScriptedChatModel(script=[bad])
    with Harness(llm) as h:
        token = h.login()
        body = h.chat(token, PT_QUESTION).json()
        assert "no longer available" not in body["message"]
        assert body["status"] == "handed_off" and "atendente" in body["message"]
        events = h.trace(token, body["conversation_id"]).json()["events"]
        agent = next(e for e in events if e["node"] == "agent")
        assert "without usage" in agent["error"]


def test_provider_exception_is_a_safe_message():
    def boom(messages):
        raise TimeoutError("provider timed out")

    with Harness(ScriptedChatModel(script=[boom])) as h:
        body = h.chat(h.login(), PT_QUESTION).json()
        assert body["status"] == "handed_off"
        assert body["handoff"]["handoff_id"] in body["message"]


def test_refusal_finish_reason_is_a_safe_message():
    refused = answer("I can't help with that.")
    refused.response_metadata = {"finish_reason": "content_filter"}
    with Harness(ScriptedChatModel(script=[refused])) as h:
        body = h.chat(h.login(), PT_QUESTION).json()
        assert body["status"] == "handed_off"


def test_tool_step_limit_hands_over_and_keeps_history_valid():
    steps = [tool_call("get_balances", call_id=f"c{i}") for i in range(6)]
    llm = ScriptedChatModel(script=[*steps, tool_call("get_balances", call_id="c7"), answer("Ok.")])
    with Harness(llm) as h:
        token = h.login()
        body = h.chat(token, "¿Cuánto dinero tengo en mis cuentas?").json()
        assert body["status"] == "handed_off" and "agente" in body["message"]
        # The next turn still works: every tool call got an answer in the history.
        h.chat(token, "Gracias por la ayuda", body["conversation_id"])
        history = llm.calls[-1]
        calls = {c["id"] for m in history if isinstance(m, AIMessage) for c in m.tool_calls}
        answered = {m.tool_call_id for m in history if isinstance(m, ToolMessage)}
        assert calls == answered


def test_unknown_tool_and_bad_arguments_go_back_to_the_model():
    def check(messages):
        errors = [json.loads(m.content)["error"]["code"] for m in messages[-2:]]
        assert errors == ["TOOL_UNKNOWN", "invalid_arguments"]
        return answer("¿Qué transacción quieres revisar?")

    two_calls = AIMessage(
        "",
        tool_calls=[
            {"name": "delete_everything", "args": {}, "id": "a", "type": "tool_call"},
            {"name": "search_transactions", "args": {"limit": 99}, "id": "b", "type": "tool_call"},
        ],
        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    )
    with Harness(ScriptedChatModel(script=[two_calls, check])) as h:
        token = h.login()
        body = h.chat(token, "¿Cuáles fueron mis últimas compras?").json()
        assert body["status"] == "answered"
        events = h.trace(token, body["conversation_id"]).json()["events"]
        gate = next(e for e in events if e["node"] == "policy_gate")
        assert "delete_everything=deny:TOOL_UNKNOWN" in gate["outcome"]


def test_no_model_configured_is_503():
    settings = _settings(anthropic_api_key=None)
    with TestClient(create_app(settings)) as client:
        r = client.post("/v1/chat", json={"message": "Hola"}, headers={"Authorization": "Bearer x"})
        assert r.status_code == 503 and r.json()["error"] == "model_unavailable"


def test_sqlite_storage_survives_a_restart(tmp_path):
    db = f"sqlite:///{tmp_path / 'ai.db'}"
    first = ScriptedChatModel(script=[answer("Hola, ¿en qué te ayudo?")])
    with Harness(first, db_url=db) as h:
        token = h.login()
        body = h.chat(token, "Hola, tengo una pregunta sobre mi cuenta").json()
        # Sessions live in the fake bank, which a restart would reset: keep this one.
        bank = h.state.bank

    second = ScriptedChatModel(script=[answer("Claro.")])
    with Harness(second, db_url=db) as h:
        h.state.bank._sessions = bank._sessions
        r = h.chat(token, "¿Me ayudas con un pago?", body["conversation_id"])
        assert r.status_code == 200
        # The history came back from SQLite: the model saw the first exchange.
        assert [type(m).__name__ for m in second.calls[0]][1:] == [
            "HumanMessage", "AIMessage", "HumanMessage"
        ]
        events = h.trace(token, body["conversation_id"]).json()["events"]
        assert [e["node"] for e in events].count("auth_guard") == 2


def test_forbidden_from_the_bank_is_a_security_event_not_data():
    from ai_backend.bank.client import Forbidden

    llm = ScriptedChatModel(script=[tool_call("get_balances")])
    with Harness(llm) as h:
        token = h.login()

        async def forbidden(session):
            raise Forbidden("forbidden")

        h.state.bank.get_balances = forbidden
        body = h.chat(token, "¿Cuánto dinero tengo en mis cuentas?").json()
        [tool] = [
            e for e in h.trace(token, body["conversation_id"]).json()["events"]
            if e["node"] == "tool"
        ]
        assert tool["reason_code"] == "CROSS_CUSTOMER"
        # A 403 is never data for the model: the turn goes straight to a human, urgently.
        assert body["status"] == "handed_off" and len(llm.calls) == 1
        handoff = h.client.get(
            f"/v1/handoffs/{body['handoff']['handoff_id']}",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert handoff["reason_codes"] == ["CROSS_CUSTOMER"] and handoff["priority"] == "high"
