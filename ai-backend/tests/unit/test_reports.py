"""PDF reports: fixed templates filled from the bank, the tool, and what a report never shows."""

from __future__ import annotations

import base64
import re
import zlib
from datetime import timedelta

import pytest
from pydantic import ValidationError

from ai_backend.files.store import MemoryFileStore
from ai_backend.reports import pdf, service, templates
from ai_backend.reports.layout import Note, Report
from ai_backend.reports.models import CATALOG, ReportArgs, ReportUnavailable
from ai_backend.tools import definitions as d
from ai_backend.tools.registry import get_tool, parameters_schema
from tests.conftest import CUSTOMER_A, NOW


def _text(content: bytes) -> str:
    """The text drawn on the PDF's pages: reportlab writes page streams as ASCII85 of zlib,
    with strings in WinAnsi (latin-1 for the accents used here)."""
    chunks = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", content, re.S):
        raw = stream.strip().removesuffix(b"~>")
        try:
            chunks.append(zlib.decompress(base64.a85decode(raw)).decode("latin-1"))
        except (ValueError, zlib.error):
            continue
    text = " ".join(re.findall(r"\((.*?)\) Tj", "".join(chunks)))
    # PDF string escapes: \ooo octal for accents, \( \) \\ for the rest.
    text = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), text)
    return re.sub(r"\\(.)", r"\1", text)


async def _build(bank, session, lang="es", **args):
    report = await templates.build(bank, session, ReportArgs(**args), NOW.date(), lang)
    content = pdf.render(report, lang=lang, customer_id=CUSTOMER_A, generated_at=NOW)
    return report, content


def test_catalog_covers_every_report_type():
    assert {r.report for r in CATALOG} == set(templates.TEMPLATES)


def test_args_check_what_each_report_needs():
    with pytest.raises(ValidationError, match="transaction_id"):
        ReportArgs(report="transaction_receipt")
    with pytest.raises(ValidationError, match="date_from"):
        ReportArgs(report="spending", date_from="2026-06-10", date_to="2026-06-01")
    with pytest.raises(ValidationError):
        ReportArgs(report="balances", rows=[["made up"]])  # no content from the model


async def test_statement_lists_the_period_masks_numbers_and_sums_only_approved(bank, session_a):
    report, content = await _build(
        bank, session_a, report="account_statement", date_from="2026-05-01"
    )
    assert content.startswith(b"%PDF-")
    assert report.filename == "extracto_2026-05-01_2026-06-18" and report.rows == 6
    text = _text(content)
    assert "Extracto de movimientos" in text and "Cine Premium" in text
    # Approved outflows only: the declined Uber (120) and transfer (300) are listed, not summed.
    assert "1.238,30 USD" in text and "Rechazada" in text
    assert "PRD-" not in text and "1111222233" not in text
    assert "Página 1 de 1" in text and CUSTOMER_A in text


async def test_statement_for_one_product_names_it_by_its_last_digits(bank, session_a):
    report, content = await _build(
        bank,
        session_a,
        "pt",
        report="account_statement",
        date_from="2026-06-01",
        product_id="PRD-ACHK",
    )
    assert report.subtitle.endswith("Conta corrente •••• 2233")
    assert all("Cartão" not in " ".join(r) for s in report.sections for r in getattr(s, "rows", []))


async def test_every_report_renders_in_both_languages(bank, session_a):
    cases = [
        {"report": "account_statement"},
        {"report": "balances"},
        {"report": "spending", "months": 3},
        {"report": "recurring_payments"},
        {"report": "transaction_receipt", "transaction_id": "TRX-A2"},
    ]
    for args in cases:
        for lang in ("es", "pt"):
            report, content = await _build(bank, session_a, lang, **args)
            assert content.startswith(b"%PDF-") and report.title in _text(content)


async def test_receipt_explains_a_decline_in_the_customer_language(bank, session_a):
    _, content = await _build(
        bank, session_a, "pt", report="transaction_receipt", transaction_id="TRX-A2"
    )
    text = _text(content)
    assert "Comprovante de transa" in text and "Recusada" in text
    assert "saldo ou limite insuficiente" in text


async def test_no_receipt_for_a_transaction_under_fraud_review(bank, session_a):
    with pytest.raises(ReportUnavailable) as exc:
        await _build(bank, session_a, report="transaction_receipt", transaction_id="TRX-A4")
    assert exc.value.code == "under_review"


async def test_bank_text_cannot_inject_markup(bank, session_a):
    report = Report(
        filename="x",
        title="<b>Título</b> & co",
        subtitle="<font color='red'>x</font>",
        sections=[Note("<para>nota</para>")],
    )
    content = pdf.render(report, lang="es", customer_id=CUSTOMER_A, generated_at=NOW)
    # Shown as written: escaped, so reportlab drew the tags instead of applying them.
    text = _text(content).replace(" ", "")
    assert "<b>Título</b>&co" in text and "<fontcolor='red'>x</font>" in text


async def test_same_report_same_bytes(bank, session_a):
    _, first = await _build(bank, session_a, report="balances")
    _, second = await _build(bank, session_a, report="balances")
    assert first == second


# ---------- the tool ----------


@pytest.fixture
def ctx(bank, session_a):
    return d.ToolContext(
        bank=bank,
        session=session_a,
        today=NOW.date(),
        files=MemoryFileStore(),
        conversation_id="conv_1",
        language="pt",
    )


def test_tool_schema_takes_parameters_not_content():
    schema = parameters_schema(get_tool("generate_report"))
    assert schema["required"] == ["report"] and schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "report",
        "date_from",
        "date_to",
        "months",
        "product_id",
        "transaction_id",
    }
    assert "anyOf" not in str(schema) and "$ref" not in str(schema)


async def test_tool_stores_a_pdf_for_the_session_customer(ctx):
    result = await get_tool("generate_report").run(ctx, {"report": "spending"})
    assert result.ok and result.data["format"] == "pdf"
    assert result.data["filename"].startswith("gastos_")
    assert "file_id" not in str(result.data)  # the model gets no IDs or links
    [ref] = result.files
    assert ref["format"] == "pdf" and ref["media_type"] == "application/pdf"
    stored = await ctx.files.get(ref["file_id"])
    assert stored.customer_id == CUSTOMER_A and stored.conversation_id == "conv_1"
    assert "Relatório de gastos" in _text(stored.content)


async def test_tool_receipt_carries_the_transaction_policy_facts(ctx):
    ok = await get_tool("generate_report").run(
        ctx, {"report": "transaction_receipt", "transaction_id": "TRX-A2"}
    )
    assert ok.ok and ok.policy_facts[0]["transaction_id"] == "TRX-A2"

    refused = await get_tool("generate_report").run(
        ctx, {"report": "transaction_receipt", "transaction_id": "TRX-A4"}
    )
    assert refused.error_code == "under_review" and not refused.files
    assert refused.policy_facts[0]["flagged_as_fraud"] is True


async def test_tool_errors_go_back_to_the_model(ctx):
    tool = get_tool("generate_report")
    missing = await tool.run(ctx, {"report": "transaction_receipt"})
    assert missing.error_code == "invalid_arguments"
    unknown = await tool.run(ctx, {"report": "transaction_receipt", "transaction_id": "TRX-B1"})
    assert unknown.error_code == "not_found"
    future = await tool.run(ctx, {"report": "account_statement", "date_from": "2027-01-01"})
    assert future.error_code == "invalid_arguments"


async def test_tool_without_a_store_says_so(bank, session_a):
    ctx = d.ToolContext(bank=bank, session=session_a, today=NOW.date())
    result = await get_tool("generate_report").run(ctx, {"report": "balances"})
    assert result.error_code == "files_unavailable"


async def test_service_sets_expiry(bank, session_a):
    store = MemoryFileStore()
    stored = await service.generate(
        store,
        bank,
        session_a,
        ReportArgs(report="recurring_payments"),
        lang="es",
        conversation_id=None,
        today=NOW.date(),
        now=NOW,
        ttl=timedelta(hours=2),
    )
    assert stored.expires_at == NOW + timedelta(hours=2)
    assert stored.filename == "pagos_previstos_2026-06.pdf"
