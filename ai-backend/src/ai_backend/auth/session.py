"""The authenticated session, as confirmed by Node (`GET /auth/sessions/current`)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr


class Session(BaseModel):
    """Who is talking. It comes only from Node's session check, never from the request body.

    The raw token is kept only to forward it to Node for this request. It is excluded from
    serialisation and repr, so it never reaches the checkpointer, logs or traces.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    customer_id: str = Field(pattern=r"^CLI-[A-Z0-9]+$")
    session_id: str
    expires_at: AwareDatetime
    token: SecretStr | None = Field(default=None, exclude=True, repr=False)

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at
