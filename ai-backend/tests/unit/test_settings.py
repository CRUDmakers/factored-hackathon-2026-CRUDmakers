from pathlib import Path

from ai_backend.settings import Settings


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("BANK_MODE", "http")
    monkeypatch.setenv("AGENT_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("TRACE_RETENTION_DAYS", "7")
    s = Settings(_env_file=None)
    assert s.bank_mode == "http"
    assert s.agent_model == "claude-sonnet-5"
    assert s.trace_retention_days == 7


def test_defaults_are_offline_friendly():
    s = Settings(_env_file=None)
    assert s.bank_mode == "fake"
    assert s.bank_fixture_dir == Path("eval/fixtures/data")


def test_cors_origins_are_comma_separated(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://demo.example.com ,")
    s = Settings(_env_file=None)
    assert s.cors_origin_list() == ["http://localhost:5173", "https://demo.example.com"]


def test_secrets_are_not_printed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret")
    s = Settings(_env_file=None)
    assert "super-secret" not in repr(s)
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-super-secret"


def test_empty_classifier_path_disables_the_classifier(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_PATH", "")
    assert Settings(_env_file=None).classifier_path is None
    monkeypatch.setenv("CLASSIFIER_PATH", "models/x.joblib")
    assert Settings(_env_file=None).classifier_path == Path("models/x.joblib")
