"""Fixture-backed bank for tests and eval (`BANK_MODE=fake`).

It behaves like the Node mock bank (`../backend/src/services`), so the eval measures the system we
ship: the same session rules, the same scoping (another customer's record is a 404), the same
response shapes, and the same payment rules and decline codes. The contract tests in
`tests/contract/` run the same cases against both.

Differences, all deliberate:
- It issues opaque test tokens instead of JWTs.
- Pix isn't supported: the fixture has no e-mails, phones or documents to use as keys.
- Recipient names are unknown: the fixture has no customer names.
- IDs and timestamps are deterministic (injectable clock).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from ai_backend.auth.session import Session
from ai_backend.bank.client import AuthExpired, BankError, BankRejected, Forbidden, NotFound
from ai_backend.bank.fixture import (
    BankFixture,
    FixtureProduct,
    FixtureRate,
    FixtureTransaction,
    load_fixture,
)
from ai_backend.bank.models import (
    REASON_CODES,
    Balances,
    BillDestination,
    Currency,
    ExchangeRate,
    PaymentRequest,
    PaymentResult,
    PixDestination,
    ProductDetail,
    TransactionDetailPolicyView,
    TransactionPage,
    TransactionQuery,
    TransferDestination,
)

# backend/src/lib/domain.ts
CHECKING, SAVINGS, DEBIT_CARD = "Cuenta Corriente", "Cuenta Ahorro", "Tarjeta Débito"
CREDIT_CARD, INVESTMENT = "Tarjeta Crédito", "Inversión"
FUNDS_PRODUCTS = (CHECKING, SAVINGS, DEBIT_CARD)
DEBT_PRODUCTS = (CREDIT_CARD, "Préstamo Personal", "Préstamo Hipotecario")
LOAN_PRODUCTS = ("Préstamo Personal", "Préstamo Hipotecario")
CARD_PRODUCTS = (CREDIT_CARD, DEBIT_CARD)
SOURCE_TYPES = {
    "transfer": FUNDS_PRODUCTS,
    "pix": FUNDS_PRODUCTS,
    "bill_payment": (*FUNDS_PRODUCTS, CREDIT_CARD),
}
COUNTRY_ALIASES = {
    "mexico": "México", "mx": "México",
    "colombia": "Colombia", "co": "Colombia",
    "argentina": "Argentina", "ar": "Argentina",
}
COUNTRY_CURRENCY = {"México": "MXN", "Colombia": "COP", "Argentina": "ARS"}
SESSION_TTL = timedelta(seconds=900)
CENT = Decimal("0.01")


class CustomerInactive(BankError):
    """Node refuses to issue a session for a customer that isn't Active (403)."""


@dataclass
class _FakeSession:
    session: Session
    revoked: bool = False


@dataclass
class _Decline:
    code: str
    detail: str


@dataclass
class _Destination:
    product: FixtureProduct | None
    country: str | None
    counterparty: dict[str, Any]
    decline: _Decline | None = None


class FakeBankClient:
    def __init__(
        self,
        fixture: BankFixture,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._fx = fixture
        self._clock = clock
        self._sessions: dict[str, _FakeSession] = {}
        self._sequence = 0

    @classmethod
    def from_dir(
        cls, directory: Path, clock: Callable[[], datetime] | None = None
    ) -> FakeBankClient:
        fixture = load_fixture(directory)
        return cls(fixture, clock) if clock else cls(fixture)

    @property
    def fixture(self) -> BankFixture:
        return self._fx

    # ---------- test identity provider (not part of BankClient) ----------

    def issue_test_session(self, customer_id: str) -> Session:
        """Like `POST /auth/test-sessions`: the eval and tests use it to log customers in."""
        customer = self._fx.customers.get(customer_id)
        if customer is None:
            raise NotFound(f"Cliente {customer_id}")
        if customer.status != "Active":
            raise CustomerInactive(f"{customer_id} is {customer.status}")
        n = self._next()
        token = f"fake-session-{n:06d}"
        session = Session(
            customer_id=customer_id,
            session_id=f"SES-{n:06d}",
            expires_at=self._clock() + SESSION_TTL,
            token=token,
        )
        self._sessions[token] = _FakeSession(session)
        return session

    def revoke_session(self, token: str) -> None:
        """Like `DELETE /auth/sessions/current` (logout)."""
        if token in self._sessions:
            self._sessions[token].revoked = True

    # ---------- BankClient ----------

    async def ping(self) -> None:
        return None

    async def get_session(self, token: str) -> Session:
        entry = self._sessions.get(token)
        if entry is None:
            raise AuthExpired("unauthorized")
        if entry.session.is_expired(self._clock()):
            raise AuthExpired("session_expired")
        if entry.revoked:
            raise AuthExpired("session_revoked")
        return entry.session

    async def get_balances(self, s: Session) -> Balances:
        customer_id = await self._authorise(s)
        products = [
            p for p in self._products_of(customer_id) if p.status != "Closed"
        ]

        def balance(p: FixtureProduct) -> Decimal:
            return p.current_balance or Decimal(0)

        accounts = [
            {
                "product_id": p.product_id,
                "product_type": p.product_type,
                "product_number": _display_number(p),
                "currency": p.currency,
                "status": p.status,
                "balance": balance(p),
            }
            for p in products
            if p.product_type in FUNDS_PRODUCTS
        ]
        cards = []
        for p in products:
            if p.product_type != CREDIT_CARD:
                continue
            limit = p.credit_limit or Decimal(0)
            cards.append(
                {
                    "product_id": p.product_id,
                    "product_number": _display_number(p),
                    "currency": p.currency,
                    "status": p.status,
                    "invoice_amount": balance(p),
                    "credit_limit": limit,
                    "available_credit": limit - balance(p),
                    "utilization_pct": None if limit == 0 else _round2(balance(p) / limit * 100),
                    "interest_rate": p.interest_rate,
                    "expiration_date": p.expiration_date,
                    "days_past_due": p.days_past_due,
                }
            )
        loans = [
            {
                "product_id": p.product_id,
                "product_type": p.product_type,
                "currency": p.currency,
                "status": p.status,
                "outstanding_balance": balance(p),
                "interest_rate": p.interest_rate,
                "expiration_date": p.expiration_date,
                "days_past_due": p.days_past_due,
            }
            for p in products
            if p.product_type in LOAN_PRODUCTS
        ]

        totals: dict[str, dict[str, Decimal]] = {}
        for p in products:
            t = totals.setdefault(
                p.currency,
                {"available_funds": Decimal(0), "investments": Decimal(0), "debt": Decimal(0)},
            )
            if p.product_type in FUNDS_PRODUCTS:
                t["available_funds"] += balance(p)
            if p.product_type in DEBT_PRODUCTS:
                t["debt"] += balance(p)
            if p.product_type == INVESTMENT:
                t["investments"] += balance(p)
        net_worth = Decimal(0)
        totals_list = []
        for currency, t in totals.items():
            net = t["available_funds"] + t["investments"] - t["debt"]
            net_worth += net * self._rate(currency, "USD").exchange_rate
            totals_list.append({"currency": currency, **t, "net": net})

        return Balances.model_validate(
            {
                "accounts": accounts,
                "credit_cards": cards,
                "loans": loans,
                "totals_by_currency": totals_list,
                "net_worth_usd": _money(net_worth),
            }
        )

    async def list_transactions(self, s: Session, q: TransactionQuery) -> TransactionPage:
        customer_id = await self._authorise(s)
        hits = [
            t
            for t in self._fx.transactions.values()
            if t.customer_id == customer_id and self._matches(t, q)
        ]
        hits.sort(key=lambda t: t.transaction_id)
        hits.sort(key=lambda t: t.transaction_date, reverse=True)
        page = hits[q.offset : q.offset + q.limit]
        return TransactionPage.model_validate(
            {
                "total": len(hits),
                "limit": q.limit,
                "offset": q.offset,
                "items": [self._item(t) for t in page],
            }
        )

    async def get_transaction(
        self, s: Session, transaction_id: str
    ) -> TransactionDetailPolicyView:
        customer_id = await self._authorise(s)
        t = self._fx.transactions.get(transaction_id)
        if t is None or t.customer_id != customer_id:
            raise NotFound(f"Transação {transaction_id}")
        product = self._fx.products.get(t.product_id) if t.product_id else None
        branch = self._fx.branches.get(t.branch_id) if t.branch_id else None
        return TransactionDetailPolicyView.model_validate(
            {
                "transaction_id": t.transaction_id,
                "transaction_date": t.transaction_date,
                "product_id": t.product_id,
                "product_type": product.product_type if product else None,
                "transaction_type": t.transaction_type,
                "transaction_category": t.transaction_category,
                "amount": t.amount,
                "currency": t.currency,
                "amount_usd": t.amount_usd,
                "channel": t.channel,
                "merchant_name": t.merchant_name,
                "origin": t.origin,
                "payment_method": t.payment_method,
                "description": t.description,
                "counterparty": t.counterparty,
                "balance_after": t.balance_after,
                "flagged_as_fraud": t.is_fraud,
                # Node doesn't expose fraud_score yet (R1), so neither does the fake.
                "status": _explain_status(t.status, t.response_code),
                "location": {
                    "city": t.city,
                    "country": t.country,
                    "branch": branch
                    and {"name": branch.name, "address": branch.address, "city": branch.city},
                },
            }
        )

    async def get_product(self, s: Session, product_id: str) -> ProductDetail:
        customer_id = await self._authorise(s)
        p = self._fx.products.get(product_id)
        if p is None or p.customer_id != customer_id:
            raise NotFound(f"Produto {product_id}")
        return ProductDetail.model_validate(
            {
                "product_id": p.product_id,
                "product_type": p.product_type,
                "product_number": _display_number(p),
                "currency": p.currency,
                "status": p.status,
                "current_balance": p.current_balance,
                "credit_limit": p.credit_limit,
                "available_credit": (
                    None
                    if p.credit_limit is None
                    else p.credit_limit - (p.current_balance or 0)
                ),
                "interest_rate": p.interest_rate,
                "opening_date": p.opening_date,
                "expiration_date": p.expiration_date,
                "is_expired": p.expiration_date is not None and p.expiration_date < self._today(),
                "days_past_due": p.days_past_due,
            }
        )

    async def get_rate(
        self, source: Currency, target: Currency, on: date | None = None
    ) -> ExchangeRate:
        return self._rate(source, target, on)

    async def preview_payment(self, s: Session, req: PaymentRequest) -> PaymentResult:
        return self._payment(await self._authorise(s), req, dry_run=True)

    async def execute_payment(
        self, s: Session, req: PaymentRequest, idempotency_key: str
    ) -> PaymentResult:
        # Node ignores idempotency keys until R2, so the fake does too.
        return self._payment(await self._authorise(s), req, dry_run=False)

    # ---------- payments (backend/src/services/payments.ts) ----------

    def _payment(self, customer_id: str, req: PaymentRequest, dry_run: bool) -> PaymentResult:
        source, currency = self._validate(customer_id, req)
        amount = _money(req.amount)
        debit = _money(amount * self._rate(currency, source.currency).exchange_rate)
        destination = self._resolve_destination(customer_id, req, currency)
        decline = self._check_source(source, debit) or destination.decline

        customer_country = _bank_country(self._fx.customers[customer_id].country)
        counterparty = dict(destination.counterparty)
        international = destination.country is not None and destination.country != customer_country
        counterparty["international"] = international
        if international and destination.product is None:
            assert destination.country is not None
            local = COUNTRY_CURRENCY[destination.country]
            quote = self._rate(currency, local)
            counterparty["destination_amount"] = {
                "currency": local,
                "amount": _money(amount * quote.exchange_rate),
                "rate": quote.exchange_rate,
                "rate_date": quote.rate_date,
            }

        is_debt_payment = (
            destination.product is not None and destination.product.product_type in DEBT_PRODUCTS
        )
        tx_type = "Payment" if req.method == "bill_payment" or is_debt_payment else "Transfer"
        status = "Declined" if decline else "Approved"
        code = decline.code if decline else "00"
        now = self._clock()

        balance_after = source.current_balance or Decimal(0)
        if not decline:
            balance_after = (
                balance_after + debit
                if source.product_type == CREDIT_CARD
                else balance_after - debit
            )

        transaction_id = None
        if not dry_run:
            if not decline:
                source.current_balance = balance_after
                if destination.product is not None:
                    self._credit(destination, source, customer_id, req, amount, currency)
            transaction_id = self._new_id("TRX")
            self._fx.transactions[transaction_id] = FixtureTransaction(
                transaction_id=transaction_id,
                transaction_date=now,
                product_id=source.product_id,
                customer_id=customer_id,
                transaction_type=tx_type,
                transaction_category="Services" if req.method == "bill_payment" else None,
                amount=amount,
                currency=currency,
                amount_usd=self._usd(amount, currency),
                channel="App",
                branch_id=None,
                merchant_name=(
                    req.destination.biller_name
                    if isinstance(req.destination, BillDestination)
                    else None
                ),
                merchant_category=None,
                country=customer_country,
                city=None,
                status=status,
                response_code=code,
                is_fraud=False,
                fraud_score=None,
                origin="simulated",
                payment_method=req.method,
                description=req.description,
                counterparty=counterparty,
                related_product_id=destination.product.product_id if destination.product else None,
                balance_after=balance_after,
            )

        return PaymentResult.model_validate(
            {
                "transaction_id": transaction_id,
                "transaction_date": now,
                "method": req.method,
                "transaction_type": tx_type,
                "amount": amount,
                "currency": currency,
                "source": {
                    "product_id": source.product_id,
                    "product_type": source.product_type,
                    "currency": source.currency,
                    "debited_amount": Decimal(0) if decline else debit,
                    "balance_after": balance_after,
                },
                "exchange": None
                if currency == source.currency
                else {
                    "from": currency,
                    "to": source.currency,
                    "rate": self._rate(currency, source.currency).exchange_rate,
                    "rate_date": self._rate(currency, source.currency).rate_date,
                },
                "counterparty": counterparty,
                **_explain_status(status, code),
                "decline_detail": decline.detail if decline else None,
                "preview": dry_run,
            }
        )

    def _validate(self, customer_id: str, req: PaymentRequest) -> tuple[FixtureProduct, str]:
        source = self._fx.products.get(req.source_product_id)
        if source is None or source.customer_id != customer_id:
            raise NotFound(f"Produto {req.source_product_id}")
        if source.product_type not in SOURCE_TYPES[req.method]:
            raise BankRejected(
                "invalid_source_product",
                f"Um(a) {source.product_type} não pode ser usado(a) para {req.method}.",
                {"allowed_product_types": list(SOURCE_TYPES[req.method])},
            )
        d = req.destination
        if isinstance(d, TransferDestination):
            if d.to_product_id == source.product_id:
                raise BankRejected(
                    "invalid_destination", "O produto de origem e o de destino são iguais."
                )
            if d.beneficiary and _bank_country(d.beneficiary.country) is None:
                raise BankRejected(
                    "country_not_supported",
                    f"O banco não faz transferências para {d.beneficiary.country}.",
                    {"supported_countries": list(COUNTRY_CURRENCY)},
                )
        if isinstance(d, PixDestination):
            raise NotImplementedError("the fake bank has no Pix keys (P1)")
        if isinstance(d, BillDestination) and not 44 <= len(_digits(d.barcode)) <= 48:
            raise BankRejected(
                "invalid_barcode", "Código de barras inválido: são esperados de 44 a 48 dígitos."
            )
        return source, req.currency or source.currency

    def _resolve_destination(
        self, customer_id: str, req: PaymentRequest, currency: str
    ) -> _Destination:
        d = req.destination
        if isinstance(d, BillDestination):
            return _Destination(
                product=None,
                country=None,
                counterparty={
                    "type": "bill",
                    "barcode": _digits(d.barcode),
                    "biller_name": d.biller_name,
                    "due_date": d.due_date,
                    "paid_after_due_date": d.due_date is not None and d.due_date < self._today(),
                },
            )
        assert isinstance(d, TransferDestination)
        if d.beneficiary:
            b = d.beneficiary
            country = _bank_country(b.country)
            return _Destination(
                product=None,
                country=country,
                counterparty={
                    "type": "external",
                    "name": b.name,
                    "account_number": b.account_number,
                    "bank_name": b.bank_name,
                    "document_number": b.document_number,
                    "country": country,
                },
            )

        product_id = d.to_product_id
        if d.to_account_number:
            number = re.sub(r"[\s.-]", "", d.to_account_number)
            matches = [
                p
                for p in self._fx.products.values()
                if p.product_number == number and p.product_type in (CHECKING, SAVINGS)
            ]
            if len(matches) != 1:
                detail = (
                    "Número de conta ambíguo: mais de uma conta com esse número."
                    if matches
                    else "Conta de destino não encontrada."
                )
                return _Destination(
                    None,
                    None,
                    {"type": "internal", "to_account_number": number},
                    _Decline("14", detail),
                )
            product_id = matches[0].product_id
            if product_id == req.source_product_id:
                raise BankRejected(
                    "invalid_destination", "O produto de origem e o de destino são iguais."
                )

        assert product_id is not None
        dest = self._fx.products.get(product_id)
        counterparty: dict[str, Any] = {"type": "internal", "to_product_id": product_id}
        if dest is None:
            return _Destination(
                None, None, counterparty, _Decline("14", "Conta de destino não encontrada.")
            )
        if dest.product_type not in (*FUNDS_PRODUCTS, *DEBT_PRODUCTS):
            raise BankRejected(
                "invalid_destination", f"Não é possível transferir para um(a) {dest.product_type}."
            )
        if dest.status != "Active":
            return _Destination(
                None,
                None,
                counterparty,
                _Decline("14", f"A conta de destino está com status {dest.status}."),
            )
        owner = self._fx.customers.get(dest.customer_id)
        counterparty.update(
            to_product_type=dest.product_type,
            recipient_name=None,  # the fixture has no names; Node returns the owner's name
            own_product=dest.customer_id == customer_id,
        )
        return _Destination(dest, _bank_country(owner.country) if owner else None, counterparty)

    def _check_source(self, source: FixtureProduct, debit: Decimal) -> _Decline | None:
        if source.status != "Active":
            return _Decline("05", f"O produto de origem está com status {source.status}.")
        if (
            source.product_type in CARD_PRODUCTS
            and source.expiration_date is not None
            and source.expiration_date < self._today()
        ):
            return _Decline("54", f"O cartão venceu em {source.expiration_date}.")
        balance = source.current_balance or Decimal(0)
        is_credit = source.product_type == CREDIT_CARD
        available = (source.credit_limit or Decimal(0)) - balance if is_credit else balance
        if available < debit:
            kind = "Limite" if is_credit else "Saldo"
            return _Decline(
                "51", f"{kind} disponível ({available:.2f} {source.currency}) insuficiente."
            )
        return None

    def _credit(
        self,
        destination: _Destination,
        source: FixtureProduct,
        customer_id: str,
        req: PaymentRequest,
        amount: Decimal,
        currency: str,
    ) -> None:
        dest = destination.product
        assert dest is not None
        received = _money(amount * self._rate(currency, dest.currency).exchange_rate)
        is_debt = dest.product_type in DEBT_PRODUCTS
        current = dest.current_balance or Decimal(0)
        dest.current_balance = current - received if is_debt else current + received
        credit_id = self._new_id("TRX")
        self._fx.transactions[credit_id] = FixtureTransaction(
            transaction_id=credit_id,
            transaction_date=self._clock(),
            product_id=dest.product_id,
            customer_id=dest.customer_id,
            transaction_type="Deposit",
            transaction_category=None,
            amount=received,
            currency=dest.currency,
            amount_usd=self._usd(received, dest.currency),
            channel="App",
            branch_id=None,
            merchant_name=None,
            merchant_category=None,
            country=destination.country,
            city=None,
            status="Approved",
            response_code="00",
            is_fraud=False,
            fraud_score=None,
            origin="simulated",
            payment_method=req.method,
            description=f"{'Pagamento recebido' if is_debt else 'Recebido'} de {source.product_id}",
            counterparty={
                "type": "internal",
                "from_product_id": source.product_id,
                "from_customer_id": customer_id,
            },
            related_product_id=source.product_id,
            balance_after=dest.current_balance,
        )

    # ---------- helpers ----------

    async def _authorise(self, s: Session) -> str:
        """Node's `customer` auth mode: a valid token whose customer matches the URL's."""
        if s.token is None:
            raise AuthExpired("unauthorized")
        current = await self.get_session(s.token.get_secret_value())
        if current.customer_id != s.customer_id:
            raise Forbidden("forbidden")
        return current.customer_id

    def _products_of(self, customer_id: str) -> list[FixtureProduct]:
        return sorted(
            (p for p in self._fx.products.values() if p.customer_id == customer_id),
            key=lambda p: (p.product_type, p.product_id),
        )

    def _matches(self, t: FixtureTransaction, q: TransactionQuery) -> bool:
        day = t.transaction_date.date()
        return (
            (q.date_from is None or day >= q.date_from)
            and (q.date_to is None or day <= q.date_to)
            and (q.type is None or t.transaction_type == q.type)
            and (q.status is None or t.status == q.status)
            and (q.channel is None or t.channel == q.channel)
            and (q.product_id is None or t.product_id == q.product_id)
            and (q.origin is None or t.origin == q.origin)
            and (q.category is None or _category(t) == q.category)
        )

    def _item(self, t: FixtureTransaction) -> dict[str, Any]:
        product = self._fx.products.get(t.product_id) if t.product_id else None
        return {
            "transaction_id": t.transaction_id,
            "transaction_date": t.transaction_date,
            "product_id": t.product_id,
            "product_type": product.product_type if product else None,
            "transaction_type": t.transaction_type,
            "category": _category(t),
            "direction": {"Deposit": "in", "Adjustment": "adjustment"}.get(
                t.transaction_type, "out"
            ),
            "amount": t.amount,
            "currency": t.currency,
            "amount_usd": self._item_usd(t),
            "channel": t.channel,
            "merchant_name": t.merchant_name,
            "transaction_city": t.city,
            "transaction_country": t.country,
            "transaction_status": t.status,
            "response_code": t.response_code,
            "origin": t.origin,
            "payment_method": t.payment_method,
            "description": t.description,
        }

    def _item_usd(self, t: FixtureTransaction) -> Decimal | None:
        """Node: amount_usd, else the amount if USD, else the rate on the transaction's date."""
        if t.amount_usd is not None:
            return t.amount_usd
        if t.currency == "USD":
            return t.amount
        try:
            rate = self._rate(t.currency, "USD", t.transaction_date.date())
        except NotFound:
            return None
        return _money(t.amount * rate.exchange_rate)

    def _usd(self, amount: Decimal, currency: str) -> Decimal | None:
        # Same convention as the dataset: empty when the currency is already USD.
        if currency == "USD":
            return None
        return _money(amount * self._rate(currency, "USD").exchange_rate)

    def _rate(self, source: str, target: str, on: date | None = None) -> ExchangeRate:
        if source == target:
            return ExchangeRate(
                source_currency=source,  # type: ignore[arg-type]
                target_currency=target,  # type: ignore[arg-type]
                rate_date=None,
                exchange_rate=Decimal(1),
                buy_rate=Decimal(1),
                sell_rate=Decimal(1),
                source=None,
            )
        quotes: list[FixtureRate] = self._fx.rates.get((source, target), [])
        eligible = [q for q in quotes if on is None or q.date <= on]
        if not eligible:
            raise NotFound(f"rate_not_found: {source}->{target}")
        q = eligible[-1]
        return ExchangeRate.model_validate(
            {
                "source_currency": source,
                "target_currency": target,
                "rate_date": q.date,
                "exchange_rate": q.rate,
                "buy_rate": q.buy_rate,
                "sell_rate": q.sell_rate,
                "source": q.source,
            }
        )

    def _today(self) -> date:
        return self._clock().date()

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-SIM{self._next():017d}"


def _explain_status(status: str, response_code: str | None) -> dict[str, Any]:
    """backend/src/lib/responseCodes.ts: `explainStatus`, codes only (the text is pt-BR)."""
    approved = status == "Approved"
    known = (not approved) and response_code not in (None, "00") and response_code in REASON_CODES
    return {
        "status": status,
        "completed": approved,
        "response_code": response_code,
        "reason_code": REASON_CODES[response_code] if known and response_code else None,
    }


def _category(t: FixtureTransaction) -> str:
    return (
        t.transaction_category
        or t.merchant_category
        or {"Withdrawal": "Withdrawals", "Transfer": "Transfers"}.get(
            t.transaction_type, "Uncategorized"
        )
    )


def _display_number(p: FixtureProduct) -> str | None:
    """Node shows card numbers masked and account numbers in full (to the owner)."""
    if not p.product_number:
        return None
    if p.product_type in CARD_PRODUCTS:
        return f"•••• {p.product_number[-4:]}"
    return p.product_number


def _bank_country(value: str | None) -> str | None:
    key = unicodedata.normalize("NFD", value or "")
    key = "".join(c for c in key if not unicodedata.combining(c)).strip().lower()
    return COUNTRY_ALIASES.get(key)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _money(value: Decimal) -> Decimal:
    """Decimal.js `toDecimalPlaces(2)` (ROUND_HALF_UP)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _round2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)
