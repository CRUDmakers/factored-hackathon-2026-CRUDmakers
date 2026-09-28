"""Behaviour configuration: the model registry (`models.yaml`) and policy limits (`policy.yaml`).

Both files are validated strictly (unknown keys are errors) so a typo can't silently fall back
to a default.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ConfigError(Exception):
    """A configuration file is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------- models.yaml ----------


class Price(_Strict):
    """USD per million tokens."""

    input: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)
    cache_read: Decimal | None = Field(default=None, ge=0)
    cache_write: Decimal | None = Field(default=None, ge=0)


class ModelSpec(_Strict):
    provider: Literal["anthropic", "openai_compatible"]
    model: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    price_per_mtok: Price | None = None
    capabilities: list[str] = Field(default_factory=list)


class ModelRegistry(_Strict):
    models: dict[str, ModelSpec] = Field(min_length=1)

    def get(self, key: str) -> ModelSpec:
        try:
            return self.models[key]
        except KeyError:
            known = ", ".join(sorted(self.models))
            raise ConfigError(f"model {key!r} is not in models.yaml (known: {known})") from None


# ---------- policy.yaml ----------


class Limits(_Strict):
    max_tool_steps_per_turn: int = Field(gt=0)
    max_clarifications: int = Field(ge=0)
    confirmation_ttl_seconds: int = Field(gt=0)
    write_amount_limit_usd: Decimal = Field(gt=0)


class Thresholds(_Strict):
    fraud_score_escalate: Decimal = Field(ge=0, le=100)
    repeat_contact_window_days: int = Field(gt=0)
    repeat_contact_count: int = Field(gt=0)


class Routing(_Strict):
    human_confidence_tau: float = Field(ge=0, le=1)


class Timeouts(_Strict):
    bank: float = Field(gt=0)
    llm: float = Field(gt=0)


class Retries(_Strict):
    max: int = Field(ge=0)
    backoff_base_seconds: float = Field(ge=0)


class PolicyConfig(_Strict):
    limits: Limits
    thresholds: Thresholds
    routing: Routing
    timeouts_seconds: Timeouts
    retries: Retries


# ---------- loaders ----------


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path} not found") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc


def load_model_registry(path: Path) -> ModelRegistry:
    try:
        return ModelRegistry.model_validate(_load_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc


def load_policy_config(path: Path) -> PolicyConfig:
    try:
        return PolicyConfig.model_validate(_load_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
