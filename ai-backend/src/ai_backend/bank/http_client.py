"""The Node mock-bank client (`BANK_MODE=http`).

- Forwards the customer's own token; builds `/api/customers/{id}/…` from the session only.
- Refuses IDs that aren't Node-shaped before they reach a URL path (no path injection).
- Retries reads on timeouts and 5xx; never retries a payment (SPEC rule 9).
- Validates every response and maps Node's `{error, message, details}` envelope to our errors.
- Parses JSON numbers as `Decimal` (Node sends money as numbers, not strings).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ai_backend.auth.session import Session
from ai_backend.bank.client import (
    AuthExpired,
    BankContractError,
    BankError,
    BankRejected,
    BankUnavailable,
    Forbidden,
    NotFound,
)
from ai_backend.bank.models import (
    Balances,
    Currency,
    ExchangeRate,
    PaymentRequest,
    PaymentResult,
    ProductDetail,
    RecurringPayments,
    Spending,
    SpendingQuery,
    TransactionDetailPolicyView,
    TransactionPage,
    TransactionQuery,
)
from ai_backend.config import Retries

M = TypeVar("M", bound=BaseModel)

_TRANSACTION_ID = re.compile(r"^TRX-[A-Z0-9]+$")
_PRODUCT_ID = re.compile(r"^PRD-[A-Z0-9]+$")


class HttpBankClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        retries: Retries,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_seconds, transport=transport
        )
        self._retries = retries

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- BankClient ----------

    async def ping(self) -> None:
        await self._request("GET", "/health")

    async def get_session(self, token: str) -> Session:
        data = await self._request("GET", "/auth/sessions/current", token=token)
        if not isinstance(data, dict):
            raise BankContractError("Session: expected an object")
        # Validate (not model_copy) so the token becomes a SecretStr and never prints.
        return _parse(Session, {**data, "token": token})

    async def get_balances(self, s: Session) -> Balances:
        data = await self._request("GET", _customer(s, "balances"), token=_token(s))
        return _parse(Balances, data)

    async def list_transactions(self, s: Session, q: TransactionQuery) -> TransactionPage:
        data = await self._request(
            "GET", _customer(s, "transactions"), token=_token(s), params=q.params()
        )
        return _parse(TransactionPage, data)

    async def get_transaction(
        self, s: Session, transaction_id: str
    ) -> TransactionDetailPolicyView:
        if not _TRANSACTION_ID.match(transaction_id):
            raise NotFound(f"Transação {transaction_id}")
        data = await self._request(
            "GET", _customer(s, f"transactions/{transaction_id}"), token=_token(s)
        )
        return _parse(TransactionDetailPolicyView, data)

    async def get_product(self, s: Session, product_id: str) -> ProductDetail:
        if not _PRODUCT_ID.match(product_id):
            raise NotFound(f"Produto {product_id}")
        data = await self._request("GET", _customer(s, f"products/{product_id}"), token=_token(s))
        return _parse(ProductDetail, data)

    async def get_rate(
        self, source: Currency, target: Currency, on: date | None = None
    ) -> ExchangeRate:
        params = {"from": source, "to": target}
        if on is not None:
            params["date"] = on.isoformat()
        data = await self._request("GET", "/api/exchange-rates", params=params)
        return _parse(ExchangeRate, data)

    async def get_recurring_payments(
        self, s: Session, as_of: date | None = None
    ) -> RecurringPayments:
        params = {"as_of": as_of.isoformat()} if as_of else None
        data = await self._request(
            "GET", _customer(s, "recurring-payments"), token=_token(s), params=params
        )
        return _parse(RecurringPayments, data)

    async def get_spending(self, s: Session, q: SpendingQuery) -> Spending:
        data = await self._request(
            "GET", _customer(s, "reports/spending"), token=_token(s), params=q.params()
        )
        return _parse(Spending, data)

    async def preview_payment(self, s: Session, req: PaymentRequest) -> PaymentResult:
        data = await self._request(
            "POST",
            _customer(s, req.endpoint()),
            token=_token(s),
            params={"dry_run": "true"},
            body=req.body(),
        )
        return _parse(PaymentResult, data)

    async def execute_payment(
        self, s: Session, req: PaymentRequest, idempotency_key: str
    ) -> PaymentResult:
        data = await self._request(
            "POST",
            _customer(s, req.endpoint()),
            token=_token(s),
            body=req.body(),
            headers={"Idempotency-Key": idempotency_key},
            retry=False,
        )
        return _parse(PaymentResult, data)

    # ---------- transport ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry: bool = True,
    ) -> Any:
        all_headers = dict(headers or {})
        if token is not None:
            all_headers["Authorization"] = f"Bearer {token}"
        content = None
        if body is not None:
            content = dumps_exact(body)
            all_headers["Content-Type"] = "application/json"

        attempts = 1 + (self._retries.max if retry else 0)
        error: BankError = BankUnavailable("no attempt made")
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(self._retries.backoff_base_seconds * 2 ** (attempt - 1))
            try:
                response = await self._http.request(
                    method, path, params=params, content=content, headers=all_headers
                )
            except httpx.TimeoutException:
                error = BankUnavailable(f"{method} {path}: timeout")
                continue
            except httpx.TransportError as exc:
                error = BankUnavailable(f"{method} {path}: {type(exc).__name__}")
                continue
            if response.status_code < 400:
                try:
                    # Node sends money as JSON numbers; parse them straight into Decimal so no
                    # digit is lost to a float on the way.
                    return json.loads(response.content, parse_float=Decimal)
                except ValueError as exc:
                    raise BankContractError(f"{method} {path}: response is not JSON") from exc
            error = _error_for(response)
            if not isinstance(error, BankUnavailable):
                raise error
        raise error


def _error_for(response: httpx.Response) -> BankError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    code = str(payload.get("error") or response.status_code)
    message = str(payload.get("message") or response.reason_phrase)
    status = response.status_code
    if status == 401:
        return AuthExpired(code)
    if status == 403:
        return Forbidden(code)
    if status == 404:
        return NotFound(f"{code}: {message}")
    if status == 422:
        return BankRejected(code, message, payload.get("details"))
    if status >= 500:
        return BankUnavailable(f"HTTP {status}: {code}")
    return BankContractError(f"HTTP {status}: {code}: {message}")


def _parse(model: type[M], data: Any) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise BankContractError(f"{model.__name__}: {exc}") from exc


def _customer(s: Session, path: str) -> str:
    # customer_id is validated by Session's pattern, so it is safe in a path.
    return f"/api/customers/{s.customer_id}/{path}"


def _token(s: Session) -> str:
    if s.token is None:
        raise AuthExpired("unauthorized")
    return s.token.get_secret_value()


def dumps_exact(payload: dict[str, Any]) -> bytes:
    """JSON with `Decimal`s written as number literals, exactly as given (never via float)."""
    literals: dict[str, str] = {}
    # A random prefix per call, so no string the customer typed can collide with a marker.
    prefix = uuid.uuid4().hex

    def swap(value: Any) -> Any:
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError(f"not a finite number: {value}")
            marker = f"{prefix}:{len(literals)}"
            literals[marker] = format(value, "f")
            return marker
        if isinstance(value, dict):
            return {k: swap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [swap(v) for v in value]
        return value

    text = json.dumps(swap(payload), ensure_ascii=False)
    for marker, literal in literals.items():
        text = text.replace(f'"{marker}"', literal)
    return text.encode("utf-8")
