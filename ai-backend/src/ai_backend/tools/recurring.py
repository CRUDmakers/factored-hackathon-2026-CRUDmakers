"""Recurring monthly payments: find them (read) and pay several at once (write).

`pay_recurring_payments` never runs directly either: the graph previews every payment in Node,
shows the customer one confirmation for all of them, then executes and reads back each one in
turn (ARCHITECTURE §5). The model only names `recurring_id`s; the destinations come from Node.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from pydantic import ConfigDict, Field

from ai_backend.bank.models import PaymentResult
from ai_backend.tools.definitions import Fact, ToolContext, ToolResult, ToolSpec, _Args
from ai_backend.tools.payments import Lang, _destination, money

# ---------- get_recurring_payments ----------


class GetRecurringPaymentsArgs(_Args):
    # No parameters (see GetBalancesArgs for why extra arguments are ignored).
    model_config = ConfigDict(extra="ignore", frozen=True)


async def get_recurring_payments(ctx: ToolContext, args: GetRecurringPaymentsArgs) -> ToolResult:
    """The payments expected this month, by date, from Node's recurring list."""
    r = await ctx.bank.get_recurring_payments(ctx.session, ctx.today)
    expected = [
        {
            "recurring_id": i.recurring_id,
            "due_date": i.due_date.isoformat(),
            "recipient": i.recipient,
            "method": i.method,
            "amount": str(i.amount),
            "currency": i.currency,
            "description": i.description,
            "status": i.status,
            "overdue": i.overdue,
            "paid_on": i.last_paid_at.date().isoformat() if i.status == "paid" else None,
            "months_in_a_row": i.consecutive_months,
        }
        for i in r.items  # Node sorts them by due_date
    ]
    facts = [
        Fact(
            f"Expected on {e['due_date']}: {e['method']} of {e['amount']} {e['currency']}"
            f"{' to ' + e['recipient'] if e['recipient'] else ''}: {e['status']}"
            f"{' (overdue)' if e['overdue'] else ''}",
            "get_recurring_payments",
            e["recurring_id"],
            as_of=ctx.today.isoformat(),
        )
        for e in expected
    ]
    data = {
        "today": ctx.today.isoformat(),
        "month": r.month,
        "expected_this_month": expected,
        "still_due": r.summary.due,
        "still_due_totals": [t.model_dump(mode="json") for t in r.summary.due_totals],
    }
    return ToolResult(ok=True, data=data, facts=facts)


# ---------- pay_recurring_payments ----------


class PayRecurringPaymentsArgs(_Args):
    recurring_ids: list[str] = Field(
        min_length=1,
        max_length=10,
        description="The REC-… ids from get_recurring_payments, status due.",
    )


# ---------- customer-facing messages (built from Node's figures) ----------


def batch_confirmation_summary(previews: list[PaymentResult], labels: list[str], lang: Lang) -> str:
    """What the customer approves: every payment, from Node's dry runs, and the totals."""
    n = len(previews)
    head = (
        f"Pagar estos {n} pagos recurrentes:"
        if lang == "es"
        else f"Pagar estes {n} pagamentos recorrentes:"
    )
    to, source = ("a", "desde") if lang == "es" else ("para", "de")
    items = []
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for p, label in zip(previews, labels, strict=True):
        items.append(
            f"- {money(p.amount, p.currency)} {to} {_destination(p, lang)} ({source} {label})"
        )
        totals[p.currency] += p.amount
    total = "Total: " + " + ".join(money(a, c) for c, a in totals.items()) + "."
    ask = "¿Confirmas?" if lang == "es" else "Confirma?"
    # Blank lines between blocks: the chat renders replies as Markdown.
    return "\n\n".join([head, "\n".join(items), total, ask])


def batch_result_message(lines: list[str], lang: Lang) -> str:
    head = "Resultado de los pagos:" if lang == "es" else "Resultado dos pagamentos:"
    return head + "\n\n" + "\n".join(f"- {line}" for line in lines)


RECURRING_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "get_recurring_payments",
        "The payments expected for the customer this month, by date: their recurring monthly "
        "payments (the same transfer, Pix or bill paid at least 2 months in a row), each one "
        "already paid this month (paid), covered by a scheduled payment (scheduled) or still "
        "to be paid (due), with the total still due. Use it whenever the customer asks about "
        "expected, upcoming, pending or recurring payments, or what they have to pay this "
        "month. Don't use search_transactions for that.",
        GetRecurringPaymentsArgs,
        "read",
        get_recurring_payments,
    ),
    ToolSpec(
        "pay_recurring_payments",
        "Pay one or more recurring payments again, exactly as last time (same source account, "
        "destination and amount). Pass the recurring_ids with status due from "
        "get_recurring_payments; for 'pay them all', pass every due one. The system previews "
        "them and shows the customer one confirmation for all: don't ask for confirmation "
        "yourself, and never say they're done.",
        PayRecurringPaymentsArgs,
        "write",
    ),
)
