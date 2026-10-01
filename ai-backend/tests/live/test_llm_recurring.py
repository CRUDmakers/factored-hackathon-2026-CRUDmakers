"""Expected payments with the real agent model (from .env). Not run by default:

    pytest -m llm tests/live/test_llm_recurring.py -s

The test fixture is seeded with a bill and a card payment made in May and June; the
conversation happens in July, when both are expected again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_backend.api.app import create_app
from ai_backend.settings import Settings
from tests.conftest import CUSTOMER_A, TEST_FIXTURE
from tests.integration.test_recurring_payments import BILL, CARD

pytestmark = pytest.mark.llm
ROOT = Path(__file__).parents[2]
JULY = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


class Chat:
    def __init__(self) -> None:
        settings = Settings(
            _env_file=ROOT / ".env",
            bank_mode="fake",
            bank_fixture_dir=TEST_FIXTURE,
            db_url="memory://",
            clock_override=JULY,
            classifier_path=None,
            models_config_path=ROOT / "config" / "models.yaml",
            policy_config_path=ROOT / "config" / "policy.yaml",
        )
        self.client = TestClient(create_app(settings))
        self.conversation_id: str | None = None

    def __enter__(self) -> Chat:
        self.client.__enter__()
        self.state = self.client.app.state.ai
        if self.state.service is None:
            pytest.skip(f"agent model not configured: {self.state.service_problem}")
        bank = self.state.bank
        pinned = bank._clock
        for month in (5, 6):
            for request, day in ((BILL, 5), (CARD, 10)):
                bank._clock = lambda m=month, d=day: datetime(2026, m, d, 9, 0, tzinfo=UTC)
                bank._payment(CUSTOMER_A, request, dry_run=False)
        bank._clock = pinned
        self.token = bank.issue_test_session(CUSTOMER_A).token.get_secret_value()
        return self

    def __exit__(self, *exc) -> None:
        self.client.__exit__(*exc)

    def say(self, message: str) -> dict:
        body = {"message": message}
        if self.conversation_id:
            body["conversation_id"] = self.conversation_id
        headers = {"Authorization": f"Bearer {self.token}"}
        r = self.client.post("/v1/chat", json=body, headers=headers).json()
        self.conversation_id = r["conversation_id"]
        print(f"\n  customer: {message}\n  [{r['status']}] {r['message']}")
        return r

    def tools_called(self) -> list[str]:
        r = self.client.get(
            f"/v1/conversations/{self.conversation_id}/trace",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        return [e.get("tool") for e in r.json()["events"] if e["node"] == "tool"]


@pytest.mark.parametrize(
    "question",
    ["Quais são os meus pagamentos previstos?", "¿Qué pagos tengo previstos este mes?"],
)
def test_expected_payments_come_from_the_recurring_api(question):
    with Chat() as chat:
        r = chat.say(question)
        assert r["status"] == "answered"
        assert "get_recurring_payments" in chat.tools_called()
        assert "Luz" in r["message"]
        assert "50" in r["message"] and "100" in r["message"]


def test_pay_all_expected_payments_after_confirming():
    with Chat() as chat:
        chat.say("Quais pagamentos eu tenho previstos para este mês?")
        pending = chat.say("Paga todos")
        assert pending["status"] == "awaiting_confirmation", pending["message"]
        done = chat.say("sim")
        assert done["status"] == "answered" and done["message"].count("TRX-") == 2
