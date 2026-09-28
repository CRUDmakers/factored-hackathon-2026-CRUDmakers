from decimal import Decimal
from pathlib import Path

import pytest

from ai_backend.config import ConfigError, load_model_registry, load_policy_config

CONFIG = Path(__file__).parents[2] / "config"


def test_repo_policy_config_loads_with_spec_values():
    policy = load_policy_config(CONFIG / "policy.yaml")
    assert policy.limits.max_tool_steps_per_turn == 6
    assert policy.limits.max_clarifications == 2
    assert policy.limits.confirmation_ttl_seconds == 300
    assert policy.limits.write_amount_limit_usd == Decimal("5000")
    assert policy.thresholds.fraud_score_escalate == Decimal("40")
    assert policy.routing.human_confidence_tau == 0.80
    assert policy.timeouts_seconds.bank == 3
    assert policy.retries.max == 2


def test_repo_model_registry_loads():
    registry = load_model_registry(CONFIG / "models.yaml")
    spec = registry.get("claude-opus-5-5")
    assert spec.provider == "anthropic"
    assert spec.params["max_tokens"] == 4096


def test_unknown_model_key_is_a_config_error():
    registry = load_model_registry(CONFIG / "models.yaml")
    with pytest.raises(ConfigError, match="not in models.yaml"):
        registry.get("gpt-nonexistent")


def test_policy_rejects_unknown_keys(tmp_path: Path):
    text = (CONFIG / "policy.yaml").read_text().replace(
        "max_clarifications: 2", "max_clarifications: 2\n  max_clarificatons: 3"
    )
    path = tmp_path / "policy.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match="invalid"):
        load_policy_config(path)


def test_policy_rejects_out_of_range_values(tmp_path: Path):
    text = (CONFIG / "policy.yaml").read_text().replace(
        "human_confidence_tau: 0.80", "human_confidence_tau: 1.5"
    )
    path = tmp_path / "policy.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError):
        load_policy_config(path)


def test_model_registry_rejects_unknown_provider(tmp_path: Path):
    path = tmp_path / "models.yaml"
    path.write_text("models:\n  x:\n    provider: bedrock\n    model: m\n")
    with pytest.raises(ConfigError):
        load_model_registry(path)


def test_missing_file_is_a_config_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_policy_config(tmp_path / "nope.yaml")


def test_invalid_yaml_is_a_config_error(tmp_path: Path):
    path = tmp_path / "models.yaml"
    path.write_text("models: [unclosed")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_model_registry(path)
