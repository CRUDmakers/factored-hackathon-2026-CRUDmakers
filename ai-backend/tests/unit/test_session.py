from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_backend.auth.session import Session

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


def _session(**overrides) -> Session:
    data = dict(
        customer_id="CLI-AAAA1111",
        session_id="SES-1",
        expires_at=NOW + timedelta(minutes=5),
        token="secret-token",
    )
    data.update(overrides)
    return Session(**data)


def test_expiry():
    s = _session()
    assert not s.is_expired(NOW)
    assert s.is_expired(NOW + timedelta(minutes=5))


def test_token_never_serialised_or_printed():
    s = _session()
    assert "token" not in s.model_dump()
    assert "secret-token" not in s.model_dump_json()
    assert "secret-token" not in repr(s)
    assert s.token is not None and s.token.get_secret_value() == "secret-token"


def test_customer_id_format_is_enforced():
    # The customer ID goes into Node URL paths, so it must be Node-shaped.
    with pytest.raises(ValidationError):
        _session(customer_id="CLI-AAAA/../CLI-BBBB")


def test_parses_node_response():
    s = Session.model_validate(
        {
            "customer_id": "CLI-G4X2AMVD62NR",
            "session_id": "0b7c",
            "expires_at": "2026-09-28T12:15:00.000Z",
        }
    )
    assert s.expires_at.tzinfo is not None and s.token is None


def test_token_is_always_a_secret():
    s = Session.model_validate({**_session().model_dump(), "token": "t"})
    assert "SecretStr" in type(s.token).__name__
