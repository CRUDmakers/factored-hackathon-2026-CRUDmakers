"""Write and escalation tools (P0): transfer_money, pay_bill, handoff_to_human.

They never run directly. The graph previews a payment in Node, asks the customer to confirm,
executes it once, and reads it back (ARCHITECTURE §5). The confirmation and result messages are
built here by code from Node's own figures, never written by the model.
"""

from __future__ import annotations

from datetime import date as Date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from ai_backend.bank.models import (
    Beneficiary,
    BillDestination,
    Currency,
    PaymentRequest,
    PaymentResult,
    TransactionDetailPolicyView,
    TransferDestination,
    last4,
)
from ai_backend.tools.definitions import DECLINE_REASONS, _Args


class BeneficiaryArgs(_Args):
    name: str = Field(min_length=1, max_length=100)
    account_number: str = Field(min_length=1, max_length=40)
    bank_name: str | None = Field(default=None, max_length=100)
    country: str = Field(description="México, Colombia or Argentina.")
    document_number: str | None = Field(default=None, max_length=40)


class TransferMoneyArgs(_Args):
    source_product_id: str = Field(
        pattern=r"^PRD-[A-Z0-9]+$", description="The customer's account the money leaves from."
    )
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: Currency | None = Field(
        default=None, description="Currency of `amount`; the source account's by default."
    )
    to_product_id: str | None = Field(
        default=None,
        pattern=r"^PRD-[A-Z0-9]+$",
        description="One of the customer's own products (e.g. to pay their credit card).",
    )
    to_account_number: str | None = Field(
        default=None, max_length=40, description="Another person's account at Banco LATAM."
    )
    beneficiary: BeneficiaryArgs | None = Field(
        default=None, description="An account at another bank in México, Colombia or Argentina."
    )
    description: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _one_destination(self) -> TransferMoneyArgs:
        given = [self.to_product_id, self.to_account_number, self.beneficiary]
        if sum(x is not None for x in given) != 1:
            raise ValueError(
                "give exactly one destination: to_product_id, to_account_number or beneficiary"
            )
        return self


class PayBillArgs(_Args):
    source_product_id: str = Field(pattern=r"^PRD-[A-Z0-9]+$")
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: Currency | None = None
    barcode: str = Field(description="The bill's barcode: 44 to 48 digits.", max_length=60)
    biller_name: str | None = Field(default=None, max_length=100)
    due_date: Date | None = None


class HandoffArgs(_Args):
    reason: Literal["unrecognized_charge", "debt_arrangement", "follow_up", "customer_request"]
    summary: str = Field(
        min_length=1, max_length=500, description="What the customer needs, for the human agent."
    )
    open_questions: list[str] = Field(default_factory=list, max_length=5)


def to_payment_request(tool: str, args: TransferMoneyArgs | PayBillArgs) -> PaymentRequest:
    if isinstance(args, TransferMoneyArgs):
        b = args.beneficiary
        return PaymentRequest(
            method="transfer",
            source_product_id=args.source_product_id,
            amount=args.amount,
            currency=args.currency,
            description=args.description,
            destination=TransferDestination(
                to_product_id=args.to_product_id,
                to_account_number=args.to_account_number,
                beneficiary=Beneficiary(**b.model_dump()) if b else None,
            ),
        )
    return PaymentRequest(
        method="bill_payment",
        source_product_id=args.source_product_id,
        amount=args.amount,
        currency=args.currency,
        destination=BillDestination(
            barcode=args.barcode, biller_name=args.biller_name, due_date=args.due_date
        ),
    )


# ---------- customer-facing messages (built from Node's figures) ----------

Lang = Literal["es", "pt"]


def money(amount: Decimal, currency: str) -> str:
    """1234.5 → '1.234,50 USD' (ES and PT both use this format)."""
    text = f"{amount:,.2f}".replace(",", "·").replace(".", ",").replace("·", ".")
    return f"{text} {currency}"


_PRODUCT_NAMES = {
    "es": {
        "Cuenta Corriente": "cuenta corriente",
        "Cuenta Ahorro": "cuenta de ahorro",
        "Tarjeta Débito": "tarjeta de débito",
        "Tarjeta Crédito": "tarjeta de crédito",
        "Préstamo Personal": "préstamo personal",
        "Préstamo Hipotecario": "préstamo hipotecario",
    },
    "pt": {
        "Cuenta Corriente": "conta corrente",
        "Cuenta Ahorro": "conta poupança",
        "Tarjeta Débito": "cartão de débito",
        "Tarjeta Crédito": "cartão de crédito",
        "Préstamo Personal": "empréstimo pessoal",
        "Préstamo Hipotecario": "financiamento imobiliário",
    },
}
_DECLINES = {
    "es": {
        "insufficient_funds": "saldo o límite insuficiente",
        "invalid_account": "cuenta o destinatario inválido",
        "do_not_honor": "el banco no la autorizó",
        "expired_card": "tarjeta vencida",
    },
    "pt": {
        "insufficient_funds": "saldo ou limite insuficiente",
        "invalid_account": "conta ou destinatário inválido",
        "do_not_honor": "o banco não autorizou",
        "expired_card": "cartão vencido",
    },
}


_OWN = {
    "es": {k: f"tu {v}" for k, v in _PRODUCT_NAMES["es"].items()},
    "pt": {
        "Cuenta Corriente": "sua conta corrente",
        "Cuenta Ahorro": "sua conta poupança",
        "Tarjeta Débito": "seu cartão de débito",
        "Tarjeta Crédito": "seu cartão de crédito",
        "Préstamo Personal": "seu empréstimo pessoal",
        "Préstamo Hipotecario": "seu financiamento imobiliário",
    },
}


def product_label(product_type: str, number: str | None, lang: Lang) -> str:
    name = _PRODUCT_NAMES[lang].get(product_type, product_type)
    return f"{name} {last4(number)}" if number else name


def _destination(p: PaymentResult, lang: Lang) -> str:
    c = p.counterparty
    if c.type == "bill":
        return (c.biller_name or ("la factura" if lang == "es" else "o boleto")).strip()
    if c.type == "internal" and c.own_product:
        return _OWN[lang].get(c.to_product_type or "", _OWN[lang]["Cuenta Corriente"])
    return c.recipient_name or c.name or ("el destinatario" if lang == "es" else "o destinatário")


def confirmation_summary(p: PaymentResult, source_label: str, lang: Lang) -> str:
    """What the customer approves, from Node's dry run."""
    if p.method == "transfer" and p.transaction_type == "Payment":
        # Paying down one of the customer's debts (card, loan): "pagar 200.000 de tu tarjeta".
        what, to = "Pagar", "de" if lang == "es" else "em"
    else:
        what = "Transferir" if p.method == "transfer" else "Pagar"
        to = "a" if lang == "es" else "para"
    lines = [f"{what} {money(p.amount, p.currency)} {to} {_destination(p, lang)}."]
    source = "Desde" if lang == "es" else "De"
    lines.append(f"{source}: {source_label}.")
    if p.exchange is not None:
        debit = "Se debitarán" if lang == "es" else "Serão debitados"
        lines.append(
            f"{debit} {money(p.source.debited_amount, p.source.currency)} "
            f"({'tipo de cambio' if lang == 'es' else 'câmbio'} {p.exchange.rate})."
        )
    dest = p.counterparty.destination_amount
    if dest is not None:
        gets = "El destinatario recibe" if lang == "es" else "O destinatário recebe"
        lines.append(f"{gets} {money(dest.amount, dest.currency)}.")
    after = "Saldo después" if lang == "es" else "Saldo depois"
    lines.append(f"{after}: {money(p.source.balance_after, p.source.currency)}.")
    ask = "¿Confirmas?" if lang == "es" else "Confirma?"
    return "\n".join(lines) + f"\n{ask}"


def result_message(
    preview: PaymentResult, readback: TransactionDetailPolicyView, lang: Lang
) -> str:
    """The outcome, from Node's read-back only (the preview only names the destination)."""
    status = readback.status
    if status.status == "Approved":
        done = (
            "Listo: la operación fue aprobada."
            if lang == "es"
            else "Pronto: a operação foi aprovada."
        )
        receipt = "Comprobante" if lang == "es" else "Comprovante"
        return (
            f"{done} {money(readback.amount, readback.currency)} → "
            f"{_destination(preview, lang)}. {receipt}: {readback.transaction_id}."
        )
    code = status.reason_code or ""
    reason = _DECLINES[lang].get(code, DECLINE_REASONS.get(code, ""))
    declined = "El banco rechazó la operación" if lang == "es" else "O banco recusou a operação"
    nothing = "No se movió dinero." if lang == "es" else "Nenhum dinheiro foi movimentado."
    return f"{declined}{': ' + reason if reason else ''}. {nothing}"
