"""Environment configuration. Secrets come from env vars (or a local `.env`) only."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr | None = None
    openai_compat_base_url: str | None = None
    openai_compat_api_key: SecretStr | None = None

    agent_model: str = "claude-opus-5-5"
    judge_model: str = "claude-sonnet-5"

    bank_mode: Literal["fake", "http"] = "fake"
    bank_base_url: str | None = None
    bank_fixture_dir: Path = Path("eval/fixtures/data")

    # Comma-separated origins allowed to call the API from a browser (the frontend).
    cors_origins: str = "http://localhost:5173"

    # "sqlite:///<path>" for checkpoints, conversations and traces; "memory://" for tests.
    db_url: str = "sqlite:///./ai_backend.db"
    trace_retention_days: int = 30
    log_level: str = "INFO"

    # Pins "now" (fake bank, agent's "today") for reproducible eval runs; real time if unset.
    clock_override: AwareDatetime | None = None
    # The dataset's last day; Node uses the real clock for everything new (ARCHITECTURE §8).
    history_end: date = date(2026, 6, 17)

    # The trained route classifier; empty/None disables classifier routing (the agent decides).
    classifier_path: Path | None = Path("models/route_classifier.joblib")

    @field_validator("classifier_path", mode="before")
    @classmethod
    def _empty_disables(cls, value: object) -> object:
        # CLASSIFIER_PATH= (empty) must mean "off", not the current directory.
        return None if value in ("", None) else value

    models_config_path: Path = Path("config/models.yaml")
    policy_config_path: Path = Path("config/policy.yaml")


    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
