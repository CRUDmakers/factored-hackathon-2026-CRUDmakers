"""The PDF reports the assistant can generate: a fixed catalogue, each with its parameters.

Unlike spreadsheets (`files/`), the model never sends report content. It names a report and its
parameters; the backend reads the data from the bank with the customer's session and lays it
out in a fixed template. The same arguments are the `generate_report` tool's and the body of
`POST /v1/reports/{report}`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReportType = Literal[
    "account_statement",
    "balances",
    "spending",
    "recurring_payments",
    "transaction_receipt",
]
ReportLang = Literal["es", "pt"]

# A statement lists at most this many transactions (the newest ones); the PDF says so.
MAX_STATEMENT_ROWS = 500
# Without dates, a statement covers this many days up to today.
DEFAULT_STATEMENT_DAYS = 30
# Argument values that stand for "not given" (see ReportArgs._drop_placeholders).
PLACEHOLDERS = frozenset({"", "PRD-", "TRX-", "null", "None"})


class ReportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report: ReportType = Field(
        description="account_statement: transactions of a period (one account/card or all); "
        "balances: accounts, cards, loans and totals today; spending: spending by month, "
        "category and card; recurring_payments: payments expected this month; "
        "transaction_receipt: receipt of one transaction (needs transaction_id)."
    )
    date_from: date | None = Field(
        default=None,
        description="account_statement, spending: first day, inclusive (YYYY-MM-DD).",
    )
    date_to: date | None = Field(
        default=None,
        description="account_statement, spending: last day, inclusive (YYYY-MM-DD).",
    )
    months: int | None = Field(
        default=None,
        ge=1,
        le=12,
        description="spending without date_from: how many whole calendar months. Default 3.",
    )
    product_id: str | None = Field(
        default=None,
        pattern=r"^PRD-",
        description="account_statement, spending: only this account or card (a PRD-… id from "
        "get_balances). Leave it out for all of them.",
    )
    transaction_id: str | None = Field(
        default=None,
        description="transaction_receipt: the TRX-… id from search_transactions.",
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_placeholders(cls, data: Any) -> Any:
        """Some gateways make every parameter required, and the model then fills the unused
        ones with placeholders ("", "PRD-", "TRX-"). Those mean "left out", not an id."""
        if not isinstance(data, dict):
            return data
        return {
            k: None if isinstance(v, str) and v.strip() in PLACEHOLDERS else v
            for k, v in data.items()
        }

    @model_validator(mode="after")
    def _consistent(self) -> ReportArgs:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        if self.report == "transaction_receipt" and not self.transaction_id:
            raise ValueError("transaction_receipt needs a transaction_id")
        return self


@dataclass(frozen=True)
class ReportInfo:
    """One catalogue entry, for `GET /v1/reports`."""

    report: ReportType
    title: dict[ReportLang, str]
    description: str
    parameters: tuple[str, ...]


CATALOG: tuple[ReportInfo, ...] = (
    ReportInfo(
        "account_statement",
        {"es": "Extracto de movimientos", "pt": "Extrato de movimentações"},
        "Transactions of a period, oldest first, with inflows and outflows per currency. "
        f"Default period: the last {DEFAULT_STATEMENT_DAYS} days. At most "
        f"{MAX_STATEMENT_ROWS} transactions (the newest).",
        ("date_from", "date_to", "product_id"),
    ),
    ReportInfo(
        "balances",
        {"es": "Posición consolidada", "pt": "Posição consolidada"},
        "Accounts, credit cards and loans with their balances today, and totals per currency.",
        (),
    ),
    ReportInfo(
        "spending",
        {"es": "Informe de gastos", "pt": "Relatório de gastos"},
        "Spending in USD by month, category and card or account. Default: the last 3 "
        "calendar months.",
        ("date_from", "date_to", "months", "product_id"),
    ),
    ReportInfo(
        "recurring_payments",
        {"es": "Pagos previstos del mes", "pt": "Pagamentos previstos do mês"},
        "Recurring monthly payments expected this month: paid, scheduled or still due.",
        (),
    ),
    ReportInfo(
        "transaction_receipt",
        {"es": "Comprobante de transacción", "pt": "Comprovante de transação"},
        "Receipt of one transaction: amount, status, date, channel and counterparty.",
        ("transaction_id",),
    ),
)


class ReportUnavailable(Exception):
    """The report can't be issued for this data (e.g. a receipt for a transaction under fraud
    review). `code` goes to the caller; nothing is stored."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
