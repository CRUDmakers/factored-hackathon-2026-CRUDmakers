"""The bank interface (SPEC §5), modelled on the Node mock bank. Every customer-scoped call takes
the session; nothing takes a customer ID."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from ai_backend.auth.session import Session
from ai_backend.bank.models import (
    Balances,
    Currency,
    ExchangeRate,
    PaymentRequest,
    PaymentResult,
    ProductDetail,
    RecurringPayments,
    TransactionDetailPolicyView,
    TransactionPage,
    TransactionQuery,
)

# Methods that change state. They are never retried automatically (SPEC rule 9).
WRITE_METHODS = frozenset({"execute_payment"})
METHODS = frozenset(
    {
        "ping", "get_session", "get_balances", "list_transactions", "get_transaction",
        "get_product", "get_rate", "preview_payment", "execute_payment",
        "get_recurring_payments",
    }
)


class BankError(Exception):
    """Base class for bank errors."""


class AuthExpired(BankError):
    """401: the session is missing, invalid, expired or revoked."""


class Forbidden(BankError):
    """403: the URL's customer isn't the session's. The client never does this, so it's a bug."""


class NotFound(BankError):
    """404: no such record for this customer (other customers' records look the same)."""


class BankRejected(BankError):
    """422: Node refused the request (bad source product, destination, barcode, country…).

    Nothing was recorded. The agent can ask the customer to correct it.
    """

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


class BankUnavailable(BankError):
    """Timeout, connection error or 5xx."""


class BankContractError(BankError):
    """A request or response that doesn't match the contract: our bug or Node's."""


class BankClient(Protocol):
    async def ping(self) -> None:
        """Raise a `BankError` if the bank can't serve requests (`GET /health`)."""

    async def get_session(self, token: str) -> Session:
        """`GET /auth/sessions/current`. Raises `AuthExpired` for any unusable token."""
        ...

    async def get_balances(self, s: Session) -> Balances: ...

    async def list_transactions(self, s: Session, q: TransactionQuery) -> TransactionPage: ...

    async def get_transaction(
        self, s: Session, transaction_id: str
    ) -> TransactionDetailPolicyView: ...

    async def get_product(self, s: Session, product_id: str) -> ProductDetail: ...

    async def get_rate(
        self, source: Currency, target: Currency, on: date | None = None
    ) -> ExchangeRate: ...

    async def get_recurring_payments(
        self, s: Session, as_of: date | None = None
    ) -> RecurringPayments:
        """`GET /recurring-payments`: monthly recurring payments, paid or still due in the month
        of `as_of` (today by default)."""
        ...

    async def preview_payment(self, s: Session, req: PaymentRequest) -> PaymentResult:
        """`?dry_run=true`: what would happen, with nothing recorded."""
        ...

    async def execute_payment(
        self, s: Session, req: PaymentRequest, idempotency_key: str
    ) -> PaymentResult:
        """Record the payment. Sent once; `idempotency_key` is ignored by Node until R2."""
        ...
