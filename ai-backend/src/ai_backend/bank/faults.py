"""Fault injection for any `BankClient` (fake or http), configured per method.

Used by tests and by eval scenarios (`bank_faults`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_backend.bank.client import METHODS, BankClient, BankContractError, BankUnavailable

FaultKind = Literal["timeout", "error_500", "malformed", "slow", "lost_response"]


class BankFault(BaseModel):
    """Make `method` fail with `fault`.

    - `timeout`, `error_500`: the call fails before reaching the bank.
    - `malformed`: the bank answered something that doesn't match the contract.
    - `slow`: the call succeeds after `delay_seconds`.
    - `lost_response`: the bank **did** the work, but the answer never arrived (a timeout after
      a payment was recorded). This is what reconciliation exists for.

    `times=None` fails every call; `times=n` fails the first n calls and then behaves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str
    fault: FaultKind
    delay_seconds: float = Field(default=0.0, ge=0)
    times: int | None = Field(default=None, ge=1)

    @field_validator("method")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in METHODS:
            raise ValueError(f"unknown bank method {v!r}")
        return v


class FaultyBankClient:
    """Wraps a `BankClient`; methods without a configured fault pass straight through."""

    def __init__(self, inner: BankClient, faults: Iterable[BankFault]) -> None:
        self.inner = inner
        self._faults = {f.method: f for f in faults}
        self._calls: dict[str, int] = {}

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.inner, name)
        fault = self._faults.get(name)
        if fault is None:
            return target
        return self._wrap(name, fault, target)

    def _wrap(
        self, name: str, fault: BankFault, target: Callable[..., Awaitable[Any]]
    ) -> Callable[..., Awaitable[Any]]:
        async def call(*args: Any, **kwargs: Any) -> Any:
            self._calls[name] = self._calls.get(name, 0) + 1
            if fault.times is not None and self._calls[name] > fault.times:
                return await target(*args, **kwargs)
            match fault.fault:
                case "slow":
                    await asyncio.sleep(fault.delay_seconds)
                    return await target(*args, **kwargs)
                case "timeout":
                    raise BankUnavailable(f"{name}: timeout")
                case "error_500":
                    raise BankUnavailable(f"{name}: HTTP 500")
                case "malformed":
                    raise BankContractError(f"{name}: malformed response")
                case "lost_response":
                    await target(*args, **kwargs)
                    raise BankUnavailable(f"{name}: timeout (the bank may have done it)")

        return call
