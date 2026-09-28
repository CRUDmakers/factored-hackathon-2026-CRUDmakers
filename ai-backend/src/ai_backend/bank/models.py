"""Bank data contracts (SPEC §4), shaped after the Node mock bank's responses.

Response models ignore fields we don't use, so Node can add fields without breaking us; a
missing or mistyped field we do use is a contract error. Records that carry fields the model
must not see have two views:
- `*LLMView`: what the model and the customer may see.
- `*PolicyView`: the LLM view plus fields for the policy engine only. `.llm_view()` strips them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Currency = Literal["USD", "MXN", "COP", "ARS"]
BankCountry = Literal["México", "Colombia", "Argentina"]
TransactionType = Literal["Purchase", "Withdrawal", "Transfer", "Payment", "Deposit", "Adjustment"]
TransactionStatus = Literal["Approved", "Declined", "Pending", "Reversed"]
Channel = Literal["POS", "ATM", "Web", "App", "Branch", "Transfer"]
PaymentMethod = Literal["transfer", "bill_payment", "pix"]

# Node's response codes (backend/src/lib/responseCodes.ts). For historical rows the codes don't
# match the product data, so no cause beyond this may be inferred. For simulated payments Node
# sets them itself: 05 source not active, 14 destination invalid, 51 insufficient funds/limit,
# 54 card expired.
REASON_CODES: dict[str, str] = {
    "00": "approved",
    "05": "do_not_honor",
    "14": "invalid_account",
    "51": "insufficient_funds",
    "54": "expired_card",
}


class _Response(BaseModel):
    """A Node response: unknown fields are ignored, known ones are validated."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Money(_Request):
    amount: Decimal
    currency: Currency


def last4(number: str | None) -> str | None:
    """Only the last 4 characters of a card or account number ever reach the model."""
    if not number:
        return None
    return f"•••• {number[-4:]}"


# ---------- balances ----------


class Account(_Response):
    product_id: str
    product_type: str
    product_number: str | None = None
    currency: Currency
    status: str | None
    balance: Decimal


class CreditCard(_Response):
    product_id: str
    product_number: str | None = None
    currency: Currency
    status: str | None
    invoice_amount: Decimal
    credit_limit: Decimal
    available_credit: Decimal
    utilization_pct: Decimal | None = None
    interest_rate: Decimal | None = None
    expiration_date: Date | None = None
    days_past_due: Decimal | None = None


class Loan(_Response):
    product_id: str
    product_type: str
    currency: Currency
    status: str | None
    outstanding_balance: Decimal
    interest_rate: Decimal | None = None
    expiration_date: Date | None = None
    days_past_due: Decimal | None = None


class CurrencyTotal(_Response):
    currency: Currency
    available_funds: Decimal
    investments: Decimal
    debt: Decimal
    net: Decimal


class Balances(_Response):
    """`GET /balances`. Closed products are not returned. Investments are out of scope, so they
    are parsed but left out of the LLM view."""

    accounts: list[Account]
    credit_cards: list[CreditCard]
    loans: list[Loan]
    totals_by_currency: list[CurrencyTotal]
    net_worth_usd: Decimal

    def llm_view(self) -> dict[str, object]:
        data = self.model_dump(mode="json")
        for item in data["accounts"] + data["credit_cards"]:
            item["product_number"] = last4(item["product_number"])
        return data


# ---------- transactions ----------


class TransactionItem(_Response):
    """One row of `GET /transactions`."""

    transaction_id: str
    transaction_date: AwareDatetime
    product_id: str | None
    product_type: str | None = None
    transaction_type: TransactionType
    category: str
    direction: Literal["in", "out", "adjustment"]
    amount: Decimal
    currency: Currency
    amount_usd: Decimal | None = None
    channel: Channel | None = None
    merchant_name: str | None = None
    transaction_city: str | None = None
    transaction_country: str | None = None
    transaction_status: TransactionStatus
    response_code: str | None = None
    origin: Literal["historical", "simulated"]
    payment_method: PaymentMethod | None = None
    description: str | None = None


class TransactionPage(_Response):
    total: int
    limit: int
    offset: int
    items: list[TransactionItem]


class StatusInfo(_Response):
    status: TransactionStatus
    completed: bool
    response_code: str | None = None
    reason_code: str | None = None


class BranchInfo(_Response):
    name: str | None = None
    address: str | None = None
    city: str | None = None


class Location(_Response):
    city: str | None = None
    country: str | None = None
    branch: BranchInfo | None = None


class DestinationAmount(_Response):
    currency: Currency
    amount: Decimal
    rate: Decimal
    rate_date: Date | None = None


class Counterparty(_Response):
    """What the model may know about the other side of a simulated payment. Account and document
    numbers are dropped by the field list; the name comes from Node."""

    type: Literal["internal", "external", "pix", "bill"]
    recipient_name: str | None = None
    name: str | None = None
    biller_name: str | None = None
    bank_name: str | None = None
    country: str | None = None
    to_product_type: str | None = None
    own_product: bool | None = None
    international: bool | None = None
    destination_amount: DestinationAmount | None = None


class TransactionDetailLLMView(_Response):
    """`GET /transactions/{id}`, minus risk fields."""

    transaction_id: str
    transaction_date: AwareDatetime
    product_id: str | None
    product_type: str | None = None
    transaction_type: TransactionType
    transaction_category: str | None = None
    amount: Decimal
    currency: Currency
    amount_usd: Decimal | None = None
    channel: Channel | None = None
    merchant_name: str | None = None
    origin: Literal["historical", "simulated"]
    payment_method: PaymentMethod | None = None
    description: str | None = None
    counterparty: Counterparty | None = None
    balance_after: Decimal | None = None
    status: StatusInfo
    location: Location


class TransactionDetailPolicyView(TransactionDetailLLMView):
    flagged_as_fraud: bool | None = None
    fraud_score: Decimal | None = None  # not exposed by Node yet (ARCHITECTURE §16, R1)

    def llm_view(self) -> TransactionDetailLLMView:
        return TransactionDetailLLMView.model_validate(
            self.model_dump(include=set(TransactionDetailLLMView.model_fields))
        )


class TransactionQuery(_Request):
    """Node's `GET /transactions` filters. Dates are inclusive calendar days."""

    date_from: Date | None = None
    date_to: Date | None = None
    type: TransactionType | None = None
    status: TransactionStatus | None = None
    category: str | None = None
    channel: Channel | None = None
    product_id: str | None = None
    origin: Literal["historical", "simulated"] | None = None
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self

    def params(self) -> dict[str, str]:
        """Node's query string."""
        names = {"date_from": "from", "date_to": "to"}
        return {
            names.get(k, k): str(v)
            for k, v in self.model_dump(mode="json", exclude_none=True).items()
        }


# ---------- products ----------


class ProductDetail(_Response):
    """`GET /products/{id}`."""

    product_id: str
    product_type: str
    product_number: str | None = None
    currency: Currency
    status: str | None
    current_balance: Decimal | None = None
    credit_limit: Decimal | None = None
    available_credit: Decimal | None = None
    interest_rate: Decimal | None = None
    opening_date: Date | None = None
    expiration_date: Date | None = None
    is_expired: bool
    days_past_due: Decimal | None = None

    def llm_view(self) -> dict[str, object]:
        data = self.model_dump(mode="json")
        data["product_number"] = last4(self.product_number)
        return data


# ---------- exchange rates ----------


class ExchangeRate(_Response):
    """`GET /api/exchange-rates`: the most recent quote up to the requested date."""

    source_currency: Currency
    target_currency: Currency
    rate_date: Date | None  # None when source == target
    exchange_rate: Decimal
    buy_rate: Decimal | None = None
    sell_rate: Decimal | None = None
    source: str | None = None


# ---------- payments ----------


class Beneficiary(_Request):
    name: str = Field(min_length=1)
    account_number: str = Field(min_length=1)
    bank_name: str | None = None
    country: str
    document_number: str | None = None


class TransferDestination(_Request):
    to_product_id: str | None = None
    to_account_number: str | None = None
    beneficiary: Beneficiary | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        given = [self.to_product_id, self.to_account_number, self.beneficiary]
        if sum(x is not None for x in given) != 1:
            raise ValueError("give exactly one of to_product_id, to_account_number, beneficiary")
        return self


class BillDestination(_Request):
    barcode: str
    biller_name: str | None = None
    due_date: Date | None = None


class PixDestination(_Request):
    pix_key: str = Field(min_length=1)


class PaymentRequest(_Request):
    method: PaymentMethod
    source_product_id: str
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: Currency | None = None
    description: str | None = Field(default=None, max_length=200)
    destination: TransferDestination | BillDestination | PixDestination

    @model_validator(mode="after")
    def _destination_matches_method(self) -> Self:
        expected = {
            "transfer": TransferDestination,
            "bill_payment": BillDestination,
            "pix": PixDestination,
        }[self.method]
        if not isinstance(self.destination, expected):
            raise ValueError(f"{self.method} needs a {expected.__name__}")
        return self

    def endpoint(self) -> str:
        return {"transfer": "transfers", "bill_payment": "bill-payments", "pix": "pix"}[self.method]

    def body(self) -> dict[str, object]:
        """Node's flat request body (destination fields sit next to the common ones)."""
        body: dict[str, object] = {
            "source_product_id": self.source_product_id,
            "amount": self.amount,
        }
        if self.currency:
            body["currency"] = self.currency
        if self.description:
            body["description"] = self.description
        body.update(self.destination.model_dump(mode="json", exclude_none=True))
        return body


class PaymentSource(_Response):
    product_id: str
    product_type: str
    currency: Currency
    debited_amount: Decimal
    balance_after: Decimal


class PaymentExchange(_Response):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    from_currency: Currency = Field(alias="from")
    to_currency: Currency = Field(alias="to")
    rate: Decimal
    rate_date: Date | None = None


class PaymentResult(_Response):
    """`POST /transfers | /bill-payments | /pix`, dry run or real."""

    transaction_id: str | None
    transaction_date: AwareDatetime
    method: PaymentMethod
    transaction_type: Literal["Transfer", "Payment"]
    amount: Decimal
    currency: Currency
    source: PaymentSource
    exchange: PaymentExchange | None = None
    counterparty: Counterparty
    status: Literal["Approved", "Declined"]
    completed: bool
    response_code: str
    reason_code: str | None = None
    decline_detail: str | None = None
    preview: bool = False


def aware(value: datetime) -> datetime:
    """Node's timestamps are UTC; the fixture's are naive UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
