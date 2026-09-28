from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_backend.api.app import create_app
from ai_backend.bank.fake_client import FakeBankClient
from ai_backend.bank.faults import BankFault, FaultyBankClient
from ai_backend.config import ConfigError
from ai_backend.settings import Settings
from tests.conftest import TEST_FIXTURE

ROOT = Path(__file__).parents[2]
NODE = "http://node.test"


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        bank_mode="fake",
        bank_fixture_dir=TEST_FIXTURE,
        models_config_path=ROOT / "config" / "models.yaml",
        policy_config_path=ROOT / "config" / "policy.yaml",
        anthropic_api_key="test-key",
    )
    base.update(overrides)
    return Settings(**base)


def _get_health(settings: Settings):
    with TestClient(create_app(settings)) as client:
        return client.get("/v1/health")


def test_health_ok_in_fake_mode():
    r = _get_health(_settings())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["bank"]["ok"] and body["checks"]["models"]["ok"]


def test_health_ok_in_http_mode_when_node_is_up(respx_mock):
    respx_mock.get(f"{NODE}/health").respond(json={"status": "ok"})
    r = _get_health(_settings(bank_mode="http", bank_base_url=NODE))
    assert r.status_code == 200 and r.json()["checks"]["bank"]["detail"] == "http: reachable"


def test_health_degraded_when_node_is_down(respx_mock):
    respx_mock.get(f"{NODE}/health").mock(side_effect=httpx.ConnectError("refused"))
    r = _get_health(_settings(bank_mode="http", bank_base_url=NODE))
    assert r.status_code == 503
    assert "BankUnavailable" in r.json()["checks"]["bank"]["detail"]


def test_http_mode_needs_a_base_url():
    with pytest.raises(ConfigError, match="BANK_BASE_URL"), TestClient(
        create_app(_settings(bank_mode="http", bank_base_url=None))
    ):
        pass


def test_health_degraded_when_agent_model_unknown():
    r = _get_health(_settings(agent_model="nope"))
    assert r.status_code == 503
    assert not r.json()["checks"]["models"]["ok"]


def test_health_degraded_when_judge_equals_agent():
    r = _get_health(_settings(judge_model="claude-opus-5-5"))
    assert r.status_code == 503
    assert "different model" in r.json()["checks"]["models"]["detail"]


def test_health_degraded_when_bank_fails():
    app = create_app(_settings())
    failing = FaultyBankClient(
        FakeBankClient.from_dir(TEST_FIXTURE), [BankFault(method="ping", fault="timeout")]
    )
    with TestClient(app) as client:
        app.state.ai = replace(app.state.ai, bank=failing)
        r = client.get("/v1/health")
    assert r.status_code == 503


def test_invalid_config_stops_startup(tmp_path: Path):
    bad = tmp_path / "policy.yaml"
    bad.write_text("limits: {}\n")
    with pytest.raises(ConfigError), TestClient(create_app(_settings(policy_config_path=bad))):
        pass


def test_cors_allows_the_frontend_only():
    with TestClient(create_app(_settings(cors_origins="http://localhost:5173"))) as client:
        preflight = {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        ok = client.options(
            "/v1/health", headers={"Origin": "http://localhost:5173", **preflight}
        )
        assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
        other = client.options("/v1/health", headers={"Origin": "https://evil.test", **preflight})
        assert "access-control-allow-origin" not in other.headers


def test_health_ok_with_openai_compatible_models():
    r = _get_health(
        _settings(
            agent_model="gemini-3.8-flash",
            judge_model="gemini-3.1-pro-low",
            openai_compat_base_url="http://localhost:20128/v1",
            openai_compat_api_key="test-key",
        )
    )
    assert r.status_code == 200
    assert r.json()["checks"]["models"]["detail"].startswith("agent=gemini-3.8-flash")


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"anthropic_api_key": None}, "ANTHROPIC_API_KEY"),
        (
            {"agent_model": "gemini-3.8-flash", "openai_compat_api_key": "k"},
            "OPENAI_COMPAT_BASE_URL",
        ),
        (
            {"judge_model": "gemini-3.1-pro-low", "openai_compat_base_url": "http://x/v1"},
            "OPENAI_COMPAT_API_KEY",
        ),
    ],
)
def test_health_degraded_when_a_selected_provider_has_no_credentials(overrides, missing):
    r = _get_health(_settings(**overrides))
    assert r.status_code == 503
    detail = r.json()["checks"]["models"]["detail"]
    assert missing in detail and "test-key" not in detail
