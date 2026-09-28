from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_backend.auth.session import Session
from ai_backend.bank.fake_client import FakeBankClient
from ai_backend.bank.fixture import load_fixture

TEST_FIXTURE = Path(__file__).parent / "fixtures" / "bank"
NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
CUSTOMER_A = "CLI-AAAA1111"
CUSTOMER_B = "CLI-BBBB2222"
CUSTOMER_SUSPENDED = "CLI-CCCC3333"


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def bank(clock: Clock) -> FakeBankClient:
    return FakeBankClient(load_fixture(TEST_FIXTURE), clock=clock)


@pytest.fixture
def session_a(bank: FakeBankClient) -> Session:
    return bank.issue_test_session(CUSTOMER_A)


@pytest.fixture
def session_b(bank: FakeBankClient) -> Session:
    return bank.issue_test_session(CUSTOMER_B)
