"""The report templates: each reads its data from the bank with the customer's session and fills
a `Report` in the customer's language. Nothing here comes from the model but the parameters.

Card and account numbers are masked (last 4); internal product IDs never appear.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal

from ai_backend.auth.session import Session
from ai_backend.bank.client import BankClient
from ai_backend.bank.models import SpendingQuery, TransactionItem, TransactionQuery, last4
from ai_backend.reports.layout import Bars, Fields, Note, Report, Table
from ai_backend.reports.models import (
    DEFAULT_STATEMENT_DAYS,
    MAX_STATEMENT_ROWS,
    ReportArgs,
    ReportLang,
    ReportType,
    ReportUnavailable,
)
from ai_backend.tools.payments import money, product_label

PAGE_SIZE = 50

TEXT: dict[ReportLang, dict[str, str]] = {
    "es": {
        "statement": "Extracto de movimientos",
        "balances": "Posición consolidada",
        "spending": "Informe de gastos",
        "recurring": "Pagos previstos del mes",
        "receipt": "Comprobante de transacción",
        "all_products": "Todas las cuentas y tarjetas",
        "period": "Período",
        "as_of": "Posición al",
        "month": "Mes",
        "date": "Fecha",
        "description": "Descripción",
        "category": "Categoría",
        "product": "Producto",
        "number": "Número",
        "status": "Estado",
        "amount": "Monto",
        "currency": "Moneda",
        "transactions": "Movimientos",
        "approved": "Aprobados",
        "inflows": "Entradas",
        "outflows": "Salidas",
        "net": "Neto",
        "by_currency": "Resumen por moneda (solo aprobados)",
        "movements": "Movimientos",
        "no_transactions": "No hay movimientos en este período.",
        "truncated": "Se muestran los {shown} movimientos más recientes de {total}. Pida un "
        "período más corto para verlos todos.",
        "totals_note": "Los movimientos pendientes, rechazados o revertidos se listan pero no "
        "suman en los totales.",
        "accounts": "Cuentas",
        "balance": "Saldo",
        "cards": "Tarjetas de crédito",
        "limit": "Límite",
        "owed": "Deuda",
        "available": "Disponible",
        "loans": "Préstamos",
        "outstanding": "Saldo pendiente",
        "days_past_due": "Días de atraso",
        "totals": "Totales por moneda",
        "funds": "Fondos disponibles",
        "debt": "Deuda total",
        "none": "Ninguno.",
        "total_spent": "Total gastado (USD)",
        "monthly_average": "Promedio mensual (USD)",
        "by_category": "Gastos por categoría",
        "category_detail": "Detalle por categoría",
        "by_month": "Gastos por mes",
        "by_product": "Gastos por tarjeta o cuenta",
        "count": "Cant.",
        "share": "Part.",
        "change": "Variación",
        "total_usd": "Total (USD)",
        "spending_note": "Compras, retiros, transferencias y pagos aprobados, convertidos a USD "
        "con la tasa de la fecha de cada transacción.",
        "no_spending": "No hay gastos en este período.",
        "due_date": "Vencimiento",
        "recipient": "Destinatario",
        "method": "Forma",
        "recurring_count": "Pagos recurrentes",
        "due_count": "Pendientes",
        "still_due": "Pendiente de pago",
        "no_recurring": "No se encontraron pagos recurrentes.",
        "recurring_note": "Un pago es recurrente cuando el mismo destino, monto y moneda se "
        "pagaron al menos 2 meses seguidos.",
        "overdue": "vencido",
        "reference": "Referencia",
        "date_time": "Fecha y hora",
        "type": "Tipo",
        "amount_usd": "Monto en USD",
        "decline_reason": "Motivo",
        "channel": "Canal",
        "merchant": "Comercio",
        "bank": "Banco",
        "country": "País",
        "destination_amount": "Monto acreditado",
        "rate": "Tasa de cambio",
        "place": "Lugar",
        "balance_after": "Saldo posterior",
        "detail": "Detalle",
        "counterparty": "Contraparte",
        "under_review": "Esta transacción está en revisión; su comprobante no está disponible.",
    },
    "pt": {
        "statement": "Extrato de movimentações",
        "balances": "Posição consolidada",
        "spending": "Relatório de gastos",
        "recurring": "Pagamentos previstos do mês",
        "receipt": "Comprovante de transação",
        "all_products": "Todas as contas e cartões",
        "period": "Período",
        "as_of": "Posição em",
        "month": "Mês",
        "date": "Data",
        "description": "Descrição",
        "category": "Categoria",
        "product": "Produto",
        "number": "Número",
        "status": "Situação",
        "amount": "Valor",
        "currency": "Moeda",
        "transactions": "Movimentações",
        "approved": "Aprovadas",
        "inflows": "Entradas",
        "outflows": "Saídas",
        "net": "Líquido",
        "by_currency": "Resumo por moeda (somente aprovadas)",
        "movements": "Movimentações",
        "no_transactions": "Não há movimentações neste período.",
        "truncated": "Exibindo as {shown} movimentações mais recentes de {total}. Peça um "
        "período menor para ver todas.",
        "totals_note": "Movimentações pendentes, recusadas ou estornadas aparecem na lista, mas "
        "não entram nos totais.",
        "accounts": "Contas",
        "balance": "Saldo",
        "cards": "Cartões de crédito",
        "limit": "Limite",
        "owed": "Fatura",
        "available": "Disponível",
        "loans": "Empréstimos",
        "outstanding": "Saldo devedor",
        "days_past_due": "Dias em atraso",
        "totals": "Totais por moeda",
        "funds": "Recursos disponíveis",
        "debt": "Dívida total",
        "none": "Nenhum.",
        "total_spent": "Total gasto (USD)",
        "monthly_average": "Média mensal (USD)",
        "by_category": "Gastos por categoria",
        "category_detail": "Detalhe por categoria",
        "by_month": "Gastos por mês",
        "by_product": "Gastos por cartão ou conta",
        "count": "Qtd.",
        "share": "Part.",
        "change": "Variação",
        "total_usd": "Total (USD)",
        "spending_note": "Compras, saques, transferências e pagamentos aprovados, convertidos "
        "para USD pela taxa da data de cada transação.",
        "no_spending": "Não há gastos neste período.",
        "due_date": "Vencimento",
        "recipient": "Destinatário",
        "method": "Forma",
        "recurring_count": "Pagamentos recorrentes",
        "due_count": "Pendentes",
        "still_due": "A pagar",
        "no_recurring": "Nenhum pagamento recorrente encontrado.",
        "recurring_note": "Um pagamento é recorrente quando o mesmo destino, valor e moeda foram "
        "pagos em pelo menos 2 meses seguidos.",
        "overdue": "atrasado",
        "reference": "Referência",
        "date_time": "Data e hora",
        "type": "Tipo",
        "amount_usd": "Valor em USD",
        "decline_reason": "Motivo",
        "channel": "Canal",
        "merchant": "Estabelecimento",
        "bank": "Banco",
        "country": "País",
        "destination_amount": "Valor creditado",
        "rate": "Taxa de câmbio",
        "place": "Local",
        "balance_after": "Saldo após",
        "detail": "Detalhes",
        "counterparty": "Contraparte",
        "under_review": "Esta transação está em análise; o comprovante não está disponível.",
    },
}
TX_TYPES = {
    "es": {
        "Purchase": "Compra",
        "Withdrawal": "Retiro",
        "Transfer": "Transferencia",
        "Payment": "Pago",
        "Deposit": "Depósito",
        "Adjustment": "Ajuste",
    },
    "pt": {
        "Purchase": "Compra",
        "Withdrawal": "Saque",
        "Transfer": "Transferência",
        "Payment": "Pagamento",
        "Deposit": "Depósito",
        "Adjustment": "Ajuste",
    },
}
TX_STATUS = {
    "es": {
        "Approved": "Aprobada",
        "Declined": "Rechazada",
        "Pending": "Pendiente",
        "Reversed": "Revertida",
    },
    "pt": {
        "Approved": "Aprovada",
        "Declined": "Recusada",
        "Pending": "Pendente",
        "Reversed": "Estornada",
    },
}
CATEGORIES = {
    "es": {
        "Food": "Alimentación",
        "Services": "Servicios",
        "Transport": "Transporte",
        "Entertainment": "Entretenimiento",
        "Health": "Salud",
        "Other": "Otros",
        "Withdrawals": "Retiros",
        "Transfers": "Transferencias",
        "Uncategorized": "Sin categoría",
    },
    "pt": {
        "Food": "Alimentação",
        "Services": "Serviços",
        "Transport": "Transporte",
        "Entertainment": "Entretenimento",
        "Health": "Saúde",
        "Other": "Outros",
        "Withdrawals": "Saques",
        "Transfers": "Transferências",
        "Uncategorized": "Sem categoria",
    },
}
PRODUCT_STATUS = {
    "es": {"Active": "Activo", "Blocked": "Bloqueado", "Inactive": "Inactivo"},
    "pt": {"Active": "Ativo", "Blocked": "Bloqueado", "Inactive": "Inativo"},
}
METHODS = {
    "es": {"transfer": "Transferencia", "bill_payment": "Pago de factura", "pix": "Pix"},
    "pt": {"transfer": "Transferência", "bill_payment": "Pagamento de boleto", "pix": "Pix"},
}
RECURRING_STATUS = {
    "es": {"paid": "Pagado", "due": "Pendiente", "scheduled": "Programado"},
    "pt": {"paid": "Pago", "due": "Pendente", "scheduled": "Agendado"},
}
DECLINES = {
    "es": {
        "insufficient_funds": "saldo o límite insuficiente",
        "invalid_account": "cuenta o destinatario inválido",
        "do_not_honor": "no autorizada por el banco",
        "expired_card": "tarjeta vencida",
    },
    "pt": {
        "insufficient_funds": "saldo ou limite insuficiente",
        "invalid_account": "conta ou destinatário inválido",
        "do_not_honor": "não autorizada pelo banco",
        "expired_card": "cartão vencido",
    },
}
FILENAMES = {
    "es": {
        "account_statement": "extracto",
        "balances": "posicion_consolidada",
        "spending": "gastos",
        "recurring_payments": "pagos_previstos",
        "transaction_receipt": "comprobante",
    },
    "pt": {
        "account_statement": "extrato",
        "balances": "posicao_consolidada",
        "spending": "gastos",
        "recurring_payments": "pagamentos_previstos",
        "transaction_receipt": "comprovante",
    },
}

Template = Callable[[BankClient, Session, ReportArgs, date, ReportLang], Awaitable[Report]]


async def build(
    bank: BankClient, session: Session, args: ReportArgs, today: date, lang: ReportLang
) -> Report:
    """The report's content, read from the bank. Bank errors propagate (NotFound, …)."""
    return await TEMPLATES[args.report](bank, session, args, today, lang)


# ---------- formatting ----------


def day(value: date | datetime) -> str:
    return value.strftime("%d/%m/%Y")


def pct(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%".replace(".", ",")


def signed(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return ("+" if value > 0 else "") + pct(value)


def _label(product_type: str | None, number: str | None, lang: ReportLang) -> str:
    if not product_type:
        return "-"
    text = product_label(product_type, number, lang)
    return text[:1].upper() + text[1:]


def _month(value: str) -> str:
    """'2026-06' → '06/2026'."""
    year, _, month = value.partition("-")
    return f"{month}/{year}" if month else value


# ---------- account_statement ----------


async def account_statement(
    bank: BankClient, session: Session, args: ReportArgs, today: date, lang: ReportLang
) -> Report:
    t = TEXT[lang]
    date_to = args.date_to or today
    date_from = args.date_from or date_to - timedelta(days=DEFAULT_STATEMENT_DAYS - 1)
    if date_from > date_to:
        raise ValueError("date_from must be on or before date_to (today, if date_to is left out)")
    scope = t["all_products"]
    if args.product_id:
        product = await bank.get_product(session, args.product_id)
        scope = _label(product.product_type, product.product_number, lang)

    items: list[TransactionItem] = []
    total, offset = 0, 0
    while len(items) < MAX_STATEMENT_ROWS:
        page = await bank.list_transactions(
            session,
            TransactionQuery(
                date_from=date_from,
                date_to=date_to,
                product_id=args.product_id,
                limit=PAGE_SIZE,
                offset=offset,
            ),
        )
        items += page.items
        total, offset = page.total, offset + len(page.items)
        if not page.items or offset >= page.total:
            break
    items = sorted(items[:MAX_STATEMENT_ROWS], key=lambda x: x.transaction_date)

    by_product = not args.product_id
    headers = [t["date"], t["description"], t["category"]]
    align: list = ["L", "L", "L"]
    widths = [1.35, 3.1, 1.6]
    if by_product:
        headers.append(t["product"])
        align.append("L")
        widths.append(1.8)
    headers += [t["status"], t["amount"]]
    align += ["L", "R"]
    widths += [1.2, 1.9]

    rows = []
    inflows: dict[str, Decimal] = defaultdict(Decimal)
    outflows: dict[str, Decimal] = defaultdict(Decimal)
    for x in items:
        sign = {"in": "+", "out": "-"}.get(x.direction, "")
        description = x.merchant_name or x.description or TX_TYPES[lang][x.transaction_type]
        row = [day(x.transaction_date), description, CATEGORIES[lang].get(x.category, x.category)]
        if by_product:
            row.append(_label(x.product_type, None, lang))
        row += [TX_STATUS[lang][x.transaction_status], sign + money(x.amount, x.currency)]
        rows.append(row)
        if x.transaction_status == "Approved":
            if x.direction == "in":
                inflows[x.currency] += x.amount
            elif x.direction == "out":
                outflows[x.currency] += x.amount

    currencies = sorted(set(inflows) | set(outflows))
    summary = [
        [
            c,
            money(inflows[c], c),
            money(outflows[c], c),
            money(inflows[c] - outflows[c], c),
        ]
        for c in currencies
    ]
    highlights = [
        (t["transactions"], str(len(items))),
        (t["approved"], str(sum(x.transaction_status == "Approved" for x in items))),
    ]
    if len(currencies) == 1:
        c = currencies[0]
        highlights += [(t["inflows"], money(inflows[c], c)), (t["outflows"], money(outflows[c], c))]

    sections: list = []
    if total > len(items):
        sections.append(Note(t["truncated"].format(shown=len(items), total=total)))
    if summary:
        sections.append(
            Table(
                t["by_currency"],
                [t["currency"], t["inflows"], t["outflows"], t["net"]],
                summary,
                ["L", "R", "R", "R"],
                [1, 2, 2, 2],
            )
        )
    sections.append(Table(t["movements"], headers, rows, align, widths, empty=t["no_transactions"]))
    if items:
        sections.append(Note(t["totals_note"]))
    return Report(
        filename=f"{FILENAMES[lang]['account_statement']}_{date_from}_{date_to}",
        title=t["statement"],
        subtitle=f"{t['period']}: {day(date_from)} - {day(date_to)} · {scope}",
        highlights=highlights,
        sections=sections,
        rows=len(items),
    )


# ---------- balances ----------


async def balances(
    bank: BankClient, session: Session, args: ReportArgs, today: date, lang: ReportLang
) -> Report:
    t = TEXT[lang]
    b = await bank.get_balances(session)
    status = PRODUCT_STATUS[lang]

    def st(value: str | None) -> str:
        return status.get(value or "", value or "-")

    accounts = Table(
        t["accounts"],
        [t["product"], t["number"], t["currency"], t["status"], t["balance"]],
        [
            [
                _label(a.product_type, None, lang),
                last4(a.product_number) or "-",
                a.currency,
                st(a.status),
                money(a.balance, a.currency),
            ]
            for a in b.accounts
        ],
        ["L", "L", "L", "L", "R"],
        [2.4, 1.3, 0.9, 1.1, 2],
        empty=t["none"],
    )
    cards = Table(
        t["cards"],
        [t["number"], t["limit"], t["owed"], t["available"], t["status"]],
        [
            [
                last4(c.product_number) or "-",
                money(c.credit_limit, c.currency),
                money(c.invoice_amount, c.currency),
                money(c.available_credit, c.currency),
                st(c.status),
            ]
            for c in b.credit_cards
        ],
        ["L", "R", "R", "R", "L"],
        [1.2, 1.9, 1.9, 1.9, 1.3],
        empty=t["none"],
    )
    loans = Table(
        t["loans"],
        [t["product"], t["outstanding"], t["days_past_due"], t["status"]],
        [
            [
                _label(loan.product_type, None, lang),
                money(loan.outstanding_balance, loan.currency),
                str(int(loan.days_past_due or 0)),
                st(loan.status),
            ]
            for loan in b.loans
        ],
        ["L", "R", "R", "L"],
        [2.6, 2, 1.3, 1.1],
        empty=t["none"],
    )
    totals = Table(
        t["totals"],
        [t["currency"], t["funds"], t["debt"]],
        [
            [x.currency, money(x.available_funds, x.currency), money(x.debt, x.currency)]
            for x in b.totals_by_currency
        ],
        ["L", "R", "R"],
        [1, 2, 2],
        empty=t["none"],
    )
    highlights = [
        (f"{t['funds']} ({x.currency})", money(x.available_funds, x.currency))
        for x in b.totals_by_currency
    ][:2]
    highlights += [
        (f"{t['debt']} ({x.currency})", money(x.debt, x.currency)) for x in b.totals_by_currency
    ][:2]
    return Report(
        filename=f"{FILENAMES[lang]['balances']}_{today}",
        title=t["balances"],
        subtitle=f"{t['as_of']} {day(today)}",
        highlights=highlights,
        sections=[totals, accounts, cards, loans],
        rows=len(b.accounts) + len(b.credit_cards) + len(b.loans),
    )


# ---------- spending ----------


async def spending(
    bank: BankClient, session: Session, args: ReportArgs, today: date, lang: ReportLang
) -> Report:
    t = TEXT[lang]
    r = await bank.get_spending(
        session,
        SpendingQuery(
            date_from=args.date_from,
            date_to=args.date_to,
            months=args.months,
            product_id=args.product_id,
        ),
    )
    labels = {p.product_id: _label(p.product_type, p.product_number, lang) for p in r.by_product}
    scope = labels.get(r.product_id, t["all_products"]) if r.product_id else t["all_products"]
    usd = "USD"
    sections: list = []
    if not r.by_category:
        sections.append(Note(t["no_spending"]))
    else:
        sections.append(
            Bars(
                t["by_category"],
                [
                    (
                        CATEGORIES[lang].get(c.category, c.category),
                        c.total_usd,
                        f"{money(c.total_usd, usd)} · {pct(c.share_pct)}",
                    )
                    for c in r.by_category
                ],
            )
        )
        sections.append(
            Table(
                t["category_detail"],
                [t["category"], t["count"], t["total_usd"], t["share"], t["monthly_average"]],
                [
                    [
                        CATEGORIES[lang].get(c.category, c.category),
                        str(c.count),
                        money(c.total_usd, usd),
                        pct(c.share_pct),
                        money(c.monthly_average_usd, usd),
                    ]
                    for c in r.by_category
                ],
                ["L", "R", "R", "R", "R"],
                [2.2, 0.8, 1.8, 0.9, 1.9],
                total=[
                    "Total",
                    str(sum(c.count for c in r.by_category)),
                    money(r.total_spent_usd, usd),
                    "100,0%",
                    money(r.monthly_average_usd, usd),
                ],
            )
        )
    sections.append(
        Table(
            t["by_month"],
            [t["month"], t["total_usd"], t["change"]],
            [[_month(m.month), money(m.total_usd, usd), signed(m.change_pct)] for m in r.by_month],
            ["L", "R", "R"],
            [1.5, 2, 1.5],
            empty=t["no_spending"],
        )
    )
    if len(r.by_product) > 1 or not r.product_id:
        sections.append(
            Table(
                t["by_product"],
                [t["product"], t["total_usd"], t["share"]],
                [
                    [labels[p.product_id], money(p.total_usd, usd), pct(p.share_pct)]
                    for p in r.by_product
                ],
                ["L", "R", "R"],
                [3, 2, 1],
                empty=t["none"],
            )
        )
    sections.append(Note(t["spending_note"]))
    return Report(
        filename=f"{FILENAMES[lang]['spending']}_{r.period.from_}_{r.period.to}",
        title=t["spending"],
        subtitle=f"{t['period']}: {day(r.period.from_)} - {day(r.period.to)} · {scope}",
        highlights=[
            (t["total_spent"], money(r.total_spent_usd, usd)),
            (t["monthly_average"], money(r.monthly_average_usd, usd)),
            (t["transactions"], str(sum(c.count for c in r.by_category))),
        ],
        sections=sections,
        rows=len(r.by_category),
    )


# ---------- recurring_payments ----------


async def recurring_payments(
    bank: BankClient, session: Session, args: ReportArgs, today: date, lang: ReportLang
) -> Report:
    t = TEXT[lang]
    r = await bank.get_recurring_payments(session, today)
    rows = []
    for i in r.items:
        status = RECURRING_STATUS[lang][i.status]
        if i.overdue:
            status += f" ({t['overdue']})"
        rows.append(
            [
                day(i.due_date),
                i.recipient or i.description or "-",
                METHODS[lang][i.method],
                money(i.amount, i.currency),
                status,
            ]
        )
    still_due = " + ".join(money(x.amount, x.currency) for x in r.summary.due_totals) or "-"
    return Report(
        filename=f"{FILENAMES[lang]['recurring_payments']}_{r.month}",
        title=t["recurring"],
        subtitle=f"{t['month']}: {_month(r.month)} · {t['as_of']} {day(r.as_of)}",
        highlights=[
            (t["recurring_count"], str(r.summary.recurring)),
            (t["due_count"], str(r.summary.due)),
            (t["still_due"], still_due),
        ],
        sections=[
            Table(
                t["recurring"],
                [t["due_date"], t["recipient"], t["method"], t["amount"], t["status"]],
                rows,
                ["L", "L", "L", "R", "L"],
                [1.2, 3, 1.8, 1.8, 1.7],
                empty=t["no_recurring"],
            ),
            Note(t["recurring_note"]),
        ],
        rows=len(rows),
    )


# ---------- transaction_receipt ----------


async def transaction_receipt(
    bank: BankClient, session: Session, args: ReportArgs, today: date, lang: ReportLang
) -> Report:
    t = TEXT[lang]
    assert args.transaction_id is not None  # ReportArgs checks it
    d = await bank.get_transaction(session, args.transaction_id)
    if d.flagged_as_fraud:
        raise ReportUnavailable("under_review", t["under_review"])

    status = TX_STATUS[lang][d.status.status]
    main: list[tuple[str, str]] = [
        (t["reference"], d.transaction_id),
        (t["date_time"], d.transaction_date.strftime("%d/%m/%Y %H:%M UTC")),
        (t["type"], TX_TYPES[lang][d.transaction_type]),
        (t["status"], status),
        (t["amount"], money(d.amount, d.currency)),
    ]
    if d.status.status == "Declined":
        reason = DECLINES[lang].get(d.status.reason_code or "", "-")
        main.append((t["decline_reason"], reason))
    if d.amount_usd is not None and d.currency != "USD":
        main.append((t["amount_usd"], money(d.amount_usd, "USD")))
    if d.product_type:
        main.append((t["product"], _label(d.product_type, None, lang)))
    if d.channel:
        main.append((t["channel"], d.channel))
    if d.balance_after is not None:
        main.append((t["balance_after"], money(d.balance_after, d.currency)))

    other: list[tuple[str, str]] = []
    if d.merchant_name:
        other.append((t["merchant"], d.merchant_name))
    c = d.counterparty
    if c is not None:
        who = c.recipient_name or c.name or c.biller_name
        if who:
            other.append((t["recipient"], who))
        if c.bank_name:
            other.append((t["bank"], c.bank_name))
        if c.country:
            other.append((t["country"], c.country))
        if c.destination_amount is not None:
            x = c.destination_amount
            other.append((t["destination_amount"], money(x.amount, x.currency)))
            other.append((t["rate"], f"{x.rate}"))
    place = d.location.branch.name if d.location.branch else None
    place = ", ".join(p for p in (place, d.location.city, d.location.country) if p)
    if place:
        other.append((t["place"], place))
    if d.description:
        other.append((t["description"], d.description))

    sections: list = [Fields(t["detail"], main)]
    if other:
        sections.append(Fields(t["counterparty"], other))
    return Report(
        filename=f"{FILENAMES[lang]['transaction_receipt']}_{d.transaction_id}",
        title=t["receipt"],
        subtitle=f"{t['reference']}: {d.transaction_id}",
        highlights=[(t["amount"], money(d.amount, d.currency)), (t["status"], status)],
        sections=sections,
        rows=1,
    )


TEMPLATES: dict[ReportType, Template] = {
    "account_statement": account_statement,
    "balances": balances,
    "spending": spending,
    "recurring_payments": recurring_payments,
    "transaction_receipt": transaction_receipt,
}
