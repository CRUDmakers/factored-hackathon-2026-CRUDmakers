"""The offline fixture: file format and loader.

`eval/fixtures/extract.py` writes these files from the raw dataset (the same data Node loads),
and `FakeBankClient` reads them. The column lists below are the contract between the two.
Personal data (names, documents, contacts, addresses) is never part of the fixture, and card
numbers keep only their last 4 digits.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from ai_backend.bank.models import aware

MANIFEST = "manifest.json"
COLUMNS: dict[str, list[str]] = {
    "customers": ["customer_id", "segment", "country", "customer_status", "tags"],
    "products": [
        "product_id", "customer_id", "product_type", "product_number", "currency",
        "current_balance", "credit_limit", "interest_rate", "opening_date", "expiration_date",
        "product_status", "days_past_due",
    ],
    "transactions": [
        "transaction_id", "transaction_date", "product_id", "customer_id", "transaction_type",
        "transaction_category", "amount", "currency", "amount_usd", "channel", "branch_id",
        "merchant_name", "merchant_category", "transaction_country", "transaction_city",
        "transaction_status", "response_code", "is_fraud", "fraud_score",
    ],
    "branches": ["branch_id", "branch_name", "address", "city", "country"],
    "exchange_rates": [
        "date", "source_currency", "target_currency", "exchange_rate", "buy_rate", "sell_rate",
        "source",
    ],
}

PRODUCT_TYPES = frozenset(
    {
        "Cuenta Ahorro", "Cuenta Corriente", "Tarjeta Crédito", "Tarjeta Débito",
        "Préstamo Personal", "Préstamo Hipotecario", "Inversión", "Seguro",
    }
)
CURRENCIES = frozenset({"USD", "MXN", "COP", "ARS"})
TRANSACTION_TYPES = frozenset(
    {"Purchase", "Withdrawal", "Transfer", "Payment", "Deposit", "Adjustment"}
)
STATUSES = frozenset({"Approved", "Declined", "Pending", "Reversed"})

T = TypeVar("T")


class FixtureError(Exception):
    """The fixture directory is missing or doesn't match the format."""


@dataclass(frozen=True)
class FixtureCustomer:
    customer_id: str
    segment: str
    country: str
    status: str
    tags: frozenset[str]


@dataclass
class FixtureProduct:
    """Mutable: simulated payments change balances, as in Node's database."""

    product_id: str
    customer_id: str
    product_type: str
    product_number: str | None
    currency: str
    current_balance: Decimal | None
    credit_limit: Decimal | None
    interest_rate: Decimal | None
    opening_date: date | None
    expiration_date: date | None
    status: str | None
    days_past_due: Decimal | None


@dataclass
class FixtureTransaction:
    transaction_id: str
    transaction_date: datetime
    product_id: str | None
    customer_id: str | None
    transaction_type: str
    transaction_category: str | None
    amount: Decimal
    currency: str
    amount_usd: Decimal | None
    channel: str | None
    branch_id: str | None
    merchant_name: str | None
    merchant_category: str | None
    country: str | None
    city: str | None
    status: str
    response_code: str | None
    is_fraud: bool | None
    fraud_score: Decimal | None
    # Set on operations simulated by the fake bank, as in Node's `transactions` table.
    origin: str = "historical"
    payment_method: str | None = None
    description: str | None = None
    counterparty: dict[str, Any] | None = None
    related_product_id: str | None = None
    balance_after: Decimal | None = None


@dataclass(frozen=True)
class FixtureBranch:
    branch_id: str
    name: str
    address: str | None
    city: str | None


@dataclass(frozen=True)
class FixtureRate:
    date: date
    rate: Decimal
    buy_rate: Decimal | None
    sell_rate: Decimal | None
    source: str | None


@dataclass
class BankFixture:
    as_of: datetime
    manifest: dict[str, Any]
    customers: dict[str, FixtureCustomer] = field(default_factory=dict)
    products: dict[str, FixtureProduct] = field(default_factory=dict)
    transactions: dict[str, FixtureTransaction] = field(default_factory=dict)
    branches: dict[str, FixtureBranch] = field(default_factory=dict)
    # (source, target) → quotes sorted by date
    rates: dict[tuple[str, str], list[FixtureRate]] = field(default_factory=dict)


def load_fixture(directory: Path) -> BankFixture:
    manifest_path = directory / MANIFEST
    if not manifest_path.exists():
        raise FixtureError(
            f"no fixture at {directory} (run `python -m eval.fixtures.extract` to build it)"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fx = BankFixture(as_of=aware(datetime.fromisoformat(manifest["as_of"])), manifest=manifest)

    for c in _parse(directory, "customers", _customer):
        fx.customers[c.customer_id] = c
    for b in _parse(directory, "branches", _branch):
        fx.branches[b.branch_id] = b
    for p in _parse(directory, "products", _product):
        fx.products[p.product_id] = p
    for t in _parse(directory, "transactions", _transaction):
        fx.transactions[t.transaction_id] = t

    rates: dict[tuple[str, str], list[FixtureRate]] = defaultdict(list)
    for pair, quote in _parse(directory, "exchange_rates", _rate):
        rates[pair].append(quote)
    fx.rates = {pair: sorted(qs, key=lambda q: q.date) for pair, qs in rates.items()}
    return fx


def _customer(row: dict[str, str]) -> FixtureCustomer:
    return FixtureCustomer(
        customer_id=row["customer_id"],
        segment=row["segment"],
        country=row["country"],
        status=row["customer_status"],
        tags=frozenset(t for t in row["tags"].split(";") if t),
    )


def _branch(row: dict[str, str]) -> FixtureBranch:
    return FixtureBranch(
        branch_id=row["branch_id"],
        name=row["branch_name"],
        address=row["address"] or None,
        city=row["city"] or None,
    )


def _product(row: dict[str, str]) -> FixtureProduct:
    return FixtureProduct(
        product_id=row["product_id"],
        customer_id=row["customer_id"],
        product_type=_one_of(row["product_type"], PRODUCT_TYPES),
        product_number=row["product_number"] or None,
        currency=_one_of(row["currency"], CURRENCIES),
        current_balance=_dec(row["current_balance"]),
        credit_limit=_dec(row["credit_limit"]),
        interest_rate=_dec(row["interest_rate"]),
        opening_date=_date(row["opening_date"]),
        expiration_date=_date(row["expiration_date"]),
        status=row["product_status"] or None,
        days_past_due=_dec(row["days_past_due"]),
    )


def _transaction(row: dict[str, str]) -> FixtureTransaction:
    return FixtureTransaction(
        transaction_id=row["transaction_id"],
        transaction_date=aware(datetime.fromisoformat(row["transaction_date"])),
        product_id=row["product_id"] or None,
        customer_id=row["customer_id"] or None,
        transaction_type=_one_of(row["transaction_type"], TRANSACTION_TYPES),
        transaction_category=row["transaction_category"] or None,
        amount=Decimal(row["amount"]),
        currency=_one_of(row["currency"], CURRENCIES),
        amount_usd=_dec(row["amount_usd"]),
        channel=row["channel"] or None,
        branch_id=row["branch_id"] or None,
        merchant_name=row["merchant_name"] or None,
        merchant_category=row["merchant_category"] or None,
        country=row["transaction_country"] or None,
        city=row["transaction_city"] or None,
        status=_one_of(row["transaction_status"], STATUSES),
        response_code=row["response_code"] or None,
        is_fraud=_bool(row["is_fraud"]),
        fraud_score=_dec(row["fraud_score"]),
    )


def _rate(row: dict[str, str]) -> tuple[tuple[str, str], FixtureRate]:
    source = _one_of(row["source_currency"], CURRENCIES)
    target = _one_of(row["target_currency"], CURRENCIES)
    return (source, target), FixtureRate(
        date=date.fromisoformat(row["date"]),
        rate=Decimal(row["exchange_rate"]),
        buy_rate=_dec(row["buy_rate"]),
        sell_rate=_dec(row["sell_rate"]),
        source=row["source"] or None,
    )


def _parse(directory: Path, table: str, build: Callable[[dict[str, str]], T]) -> Iterator[T]:
    for row in _rows(directory, table):
        try:
            yield build(row)
        except (ValueError, ArithmeticError) as exc:
            raise FixtureError(f"{table}.csv: bad row {row}: {exc}") from exc


def _rows(directory: Path, table: str) -> list[dict[str, str]]:
    path = directory / f"{table}.csv"
    if not path.exists():
        raise FixtureError(f"{path} is missing")
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS[table]:
            raise FixtureError(
                f"{path}: expected columns {COLUMNS[table]}, got {reader.fieldnames}"
            )
        return list(reader)


def _one_of(value: str, allowed: frozenset[str]) -> str:
    if value not in allowed:
        raise ValueError(f"unexpected value {value!r}")
    return value


def _dec(value: str) -> Decimal | None:
    return Decimal(value) if value else None


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _bool(value: str) -> bool | None:
    if value == "":
        return None
    if value in ("True", "False"):
        return value == "True"
    raise ValueError(f"not a boolean: {value!r}")
