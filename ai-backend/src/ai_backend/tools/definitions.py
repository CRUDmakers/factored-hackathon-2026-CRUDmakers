"""LLM-facing tools (SPEC §6): strict argument schemas, descriptions, and handlers.

Handlers are framework-free: they take a `ToolContext` (bank, session, today) and validated
arguments, and return a `ToolResult` holding the LLM view of the data plus the verified facts
it establishes. No tool takes a customer ID; identity comes from the session only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_backend.auth.session import Session
from ai_backend.bank.client import (
    BankClient,
    BankContractError,
    BankRejected,
    BankUnavailable,
    NotFound,
)
from ai_backend.bank.models import (
    Channel,
    Currency,
    TransactionDetailPolicyView,
    TransactionQuery,
    TransactionStatus,
    TransactionType,
    last4,
)
from ai_backend.files.store import FileStore
from ai_backend.fx.convert import Side, convert

ToolKind = Literal["read", "write", "escalate"]
# Node's reason codes, as the model should read them (it replies in the customer's language).
DECLINE_REASONS = {
    "insufficient_funds": "insufficient funds or credit limit",
    "invalid_account": "invalid account, card or recipient",
    "do_not_honor": "not authorised by the bank (no reason recorded)",
    "expired_card": "expired card",
}
# How many rows search_transactions scans when it has to filter in Python (R3).
SCAN_LIMIT = 200
# A filtered search with at most this many rows is about specific transactions: the policy
# engine checks them like get_transaction does (fraud flag, blocked product).
NARROW_SEARCH = 3


@dataclass(frozen=True)
class ToolContext:
    bank: BankClient
    session: Session
    today: date
    # Where generate_files stores what it builds; None where files aren't offered (eval B1).
    files: FileStore | None = None
    conversation_id: str | None = None
    file_ttl: timedelta = timedelta(hours=24)


@dataclass(frozen=True)
class Fact:
    fact: str
    source_tool: str
    record_id: str | None = None
    as_of: str | None = None


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    facts: list[Fact] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    # Policy-view facts (fraud flag, product status…): for the policy engine, never the model.
    policy_facts: list[dict[str, Any]] = field(default_factory=list)
    # Generated files (refs, no content): returned to the chat for download, never to the model.
    files: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def error(cls, code: str, message: str) -> ToolResult:
        return cls(ok=False, error_code=code, error_message=message)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------- get_balances ----------


class GetBalancesArgs(_Args):
    # No parameters. Some gateways add a placeholder parameter to empty tool schemas and the
    # model fills it in; with nothing to validate, ignoring it is safe (writes still forbid it).
    model_config = ConfigDict(extra="ignore", frozen=True)


async def get_balances(ctx: ToolContext, args: GetBalancesArgs) -> ToolResult:
    b = await ctx.bank.get_balances(ctx.session)
    facts = [
        Fact(
            f"{a.product_type} {last4(a.product_number) or a.product_id}: balance {a.balance} "
            f"{a.currency} ({a.status})",
            "get_balances",
            a.product_id,
        )
        for a in b.accounts
    ]
    facts += [
        Fact(
            f"Tarjeta Crédito {c.product_number or c.product_id}: owed {c.invoice_amount}, "
            f"available {c.available_credit} of {c.credit_limit} {c.currency} ({c.status})",
            "get_balances",
            c.product_id,
        )
        for c in b.credit_cards
    ]
    facts += [
        Fact(
            f"{loan.product_type}: outstanding {loan.outstanding_balance} {loan.currency}, "
            f"{int(loan.days_past_due or 0)} days past due ({loan.status})",
            "get_balances",
            loan.product_id,
        )
        for loan in b.loans
    ]
    return ToolResult(ok=True, data=b.llm_view(), facts=facts)


# ---------- search_transactions ----------


class SearchTransactionsArgs(_Args):
    date_from: date | None = Field(default=None, description="First day, inclusive (YYYY-MM-DD).")
    date_to: date | None = Field(default=None, description="Last day, inclusive (YYYY-MM-DD).")
    type: TransactionType | None = None
    status: TransactionStatus | None = None
    category: str | None = Field(
        default=None,
        description="Food, Services, Transport, Entertainment, Health, Other, Withdrawals, "
        "Transfers or Uncategorized.",
    )
    channel: Channel | None = None
    merchant: str | None = Field(
        default=None, description="Part of the merchant or biller name, any case."
    )
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    limit: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def _ranges(self) -> SearchTransactionsArgs:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount must be at most max_amount")
        return self

    def needs_local_filter(self) -> bool:
        return any(v is not None for v in (self.merchant, self.min_amount, self.max_amount))


async def search_transactions(ctx: ToolContext, args: SearchTransactionsArgs) -> ToolResult:
    node_filters = dict(
        date_from=args.date_from,
        date_to=args.date_to,
        type=args.type,
        status=args.status,
        category=args.category,
        channel=args.channel,
    )
    if not args.needs_local_filter():
        page = await ctx.bank.list_transactions(
            ctx.session, TransactionQuery(**node_filters, limit=args.limit)
        )
        items, total = page.items, page.total
    else:
        # Node has no merchant/amount filter yet (R3): scan newest first and filter here.
        scanned, offset, matched = 0, 0, []
        while scanned < SCAN_LIMIT:
            page = await ctx.bank.list_transactions(
                ctx.session, TransactionQuery(**node_filters, limit=50, offset=offset)
            )
            matched += [t for t in page.items if _local_match(t, args)]
            scanned += len(page.items)
            offset += len(page.items)
            if not page.items or offset >= page.total:
                break
        items, total = matched[: args.limit], len(matched)

    rows = [_item_view(t) for t in items]
    facts = [
        Fact(
            f"{r['transaction_type']} of {r['amount']} {r['currency']}"
            f"{' at ' + r['merchant_name'] if r['merchant_name'] else ''} on "
            f"{r['transaction_date'][:10]}: {r['transaction_status']}",
            "search_transactions",
            r["transaction_id"],
        )
        for r in rows
    ]
    data = {"total_matching": total, "returned": len(rows), "transactions": rows}
    policy_facts = []
    if _filtered(args) and 0 < len(items) <= NARROW_SEARCH:
        policy_facts = [f for t in items if (f := await _transaction_facts(ctx, t.transaction_id))]
    return ToolResult(ok=True, data=data, facts=facts, policy_facts=policy_facts)


def _filtered(args: SearchTransactionsArgs) -> bool:
    return any(
        v is not None
        for v in (
            args.date_from,
            args.date_to,
            args.type,
            args.status,
            args.category,
            args.channel,
            args.merchant,
            args.min_amount,
            args.max_amount,
        )
    )


async def _transaction_facts(ctx: ToolContext, transaction_id: str) -> dict[str, Any] | None:
    """The policy view of one transaction, or None if it can't be read (the search stands)."""
    try:
        detail = await ctx.bank.get_transaction(ctx.session, transaction_id)
    except (NotFound, BankUnavailable, BankContractError):
        return None
    return await _policy_facts(ctx, detail)


def _local_match(t: Any, args: SearchTransactionsArgs) -> bool:
    if args.merchant and args.merchant.casefold() not in (t.merchant_name or "").casefold():
        return False
    if args.min_amount is not None and t.amount < args.min_amount:
        return False
    return not (args.max_amount is not None and t.amount > args.max_amount)


def _item_view(t: Any) -> dict[str, Any]:
    row = t.model_dump(mode="json")
    # R5: cite a reason only for Declined; other statuses carry codes that don't fit the data.
    if row["transaction_status"] != "Declined":
        row["response_code"] = None
    return row


# ---------- get_transaction ----------


class GetTransactionArgs(_Args):
    transaction_id: str = Field(description="The TRX-… id from search_transactions.")


async def get_transaction(ctx: ToolContext, args: GetTransactionArgs) -> ToolResult:
    detail: TransactionDetailPolicyView = await ctx.bank.get_transaction(
        ctx.session, args.transaction_id
    )
    data = detail.llm_view().model_dump(mode="json")
    status = data["status"]
    code = status.pop("reason_code")
    if status["status"] == "Declined":
        status["decline_reason"] = DECLINE_REASONS.get(code or "", "no reason recorded")
    else:
        status["response_code"] = None  # R5: no reasons for other statuses
    fact = (
        f"{data['transaction_type']} of {data['amount']} {data['currency']}"
        f"{' at ' + data['merchant_name'] if data['merchant_name'] else ''} on "
        f"{data['transaction_date'][:10]}: {status['status']}"
        + (
            f" (code {status['response_code']}: {status['decline_reason']})"
            if "decline_reason" in status
            else ""
        )
    )
    return ToolResult(
        ok=True,
        data=data,
        facts=[Fact(fact, "get_transaction", detail.transaction_id)],
        policy_facts=[await _policy_facts(ctx, detail)],
    )


async def _policy_facts(ctx: ToolContext, detail: TransactionDetailPolicyView) -> dict[str, Any]:
    return {
        "kind": "transaction",
        "transaction_id": detail.transaction_id,
        "flagged_as_fraud": detail.flagged_as_fraud,
        "fraud_score": detail.fraud_score,
        "product_id": detail.product_id,
        "product_status": await _product_status(ctx, detail.product_id),
    }


async def _product_status(ctx: ToolContext, product_id: str | None) -> str | None:
    """The status of the product a transaction belongs to, for PRODUCT_BLOCKED."""
    if product_id is None:
        return None
    try:
        return (await ctx.bank.get_product(ctx.session, product_id)).status
    except (NotFound, BankUnavailable, BankContractError):
        return None


# ---------- convert_currency ----------


class ConvertCurrencyArgs(_Args):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    amount: Decimal = Field(gt=0)
    from_currency: Currency
    to_currency: Currency
    # Called `date` in the tool schema; renamed here so it doesn't shadow the `date` type.
    on: date | None = Field(
        default=None,
        alias="date",
        description="Use the rate of this day (or the latest before it).",
    )
    side: Side = Field(default="mid", description="mid, buy or sell rate, as published.")


async def convert_currency(ctx: ToolContext, args: ConvertCurrencyArgs) -> ToolResult:
    rate = await ctx.bank.get_rate(args.from_currency, args.to_currency, args.on)
    try:
        converted = convert(args.amount, rate, args.side)
    except ValueError as exc:
        return ToolResult.error("rate_unavailable", str(exc))
    used = {"mid": rate.exchange_rate, "buy": rate.buy_rate, "sell": rate.sell_rate}[args.side]
    data = {
        "amount": str(args.amount),
        "from_currency": args.from_currency,
        "converted": {"amount": str(converted), "currency": args.to_currency},
        "rate": str(used),
        "side": args.side,
        "rate_date": rate.rate_date.isoformat() if rate.rate_date else None,
        "rate_source": rate.source,
    }
    fact = (
        f"{args.amount} {args.from_currency} = {converted} {args.to_currency} "
        f"({args.side} rate {used}"
        f"{', ' + data['rate_date'] if data['rate_date'] else ''})"
    )
    return ToolResult(
        ok=True,
        data=data,
        facts=[Fact(fact, "convert_currency", as_of=data["rate_date"])],
    )


# ---------- registry entries ----------

Handler = Callable[[ToolContext, Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[_Args]
    kind: ToolKind
    handler: Handler | None = None  # reads only; writes and escalations run in the graph

    def parse(self, raw_args: dict[str, Any]) -> _Args | ToolResult:
        """The validated arguments, or an `invalid_arguments` error result for the model."""
        try:
            return self.args_model.model_validate(raw_args)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors()
            )
            return ToolResult.error("invalid_arguments", problems)

    async def run(self, ctx: ToolContext, raw_args: dict[str, Any]) -> ToolResult:
        """Validate the model's arguments and run a read tool. Bank failures become error
        results; `AuthExpired` and `Forbidden` propagate, because the turn must stop."""
        assert self.handler is not None, f"{self.name} is not a read tool"
        args = self.parse(raw_args)
        if isinstance(args, ToolResult):
            return args
        try:
            return await self.handler(ctx, args)
        except NotFound:
            return ToolResult.error("not_found", "No such record for this customer.")
        except BankRejected as exc:
            return ToolResult.error(exc.code, exc.message)
        except (BankUnavailable, BankContractError):
            result = ToolResult.error("bank_unavailable", "The bank could not answer right now.")
            result.policy_facts.append({"kind": "bank_unavailable", "tool": self.name})
            return result


P0_READ_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "get_balances",
        "The customer's accounts (balance), credit cards (amount owed, limit, available "
        "credit) and loans (outstanding, days past due). Use it for 'how much do I have / owe'. "
        "Don't use it for transaction history.",
        GetBalancesArgs,
        "read",
        get_balances,
    ),
    ToolSpec(
        "search_transactions",
        "Find the customer's transactions by date range, type, status, category, channel, "
        "merchant or amount, newest first. Use it to locate a payment the customer describes. "
        "If several transactions match, ask which one before answering about one.",
        SearchTransactionsArgs,
        "read",
        search_transactions,
    ),
    ToolSpec(
        "get_transaction",
        "Full detail of one transaction: status, decline code, place (ATM/branch), "
        "counterparty. Use it after search_transactions, with an id it returned. Never invent "
        "ids.",
        GetTransactionArgs,
        "read",
        get_transaction,
    ),
    ToolSpec(
        "convert_currency",
        "Convert an amount between USD, MXN, COP and ARS with the bank's published rate for a "
        "day (latest available on or before it). Use it for any currency maths; never convert "
        "by yourself.",
        ConvertCurrencyArgs,
        "read",
        convert_currency,
    ),
)
