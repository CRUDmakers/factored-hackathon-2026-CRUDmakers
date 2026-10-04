"""generate_report: a PDF from a fixed template; the backend reads the data, not the model.

The model only picks the report and its parameters (`reports/models.py`). Reading changes
nothing at the bank, so the policy engine treats it as a read (no confirmation). A receipt is
about one transaction, so it carries that transaction's policy facts, like get_transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_backend.reports import service
from ai_backend.reports.models import ReportArgs, ReportUnavailable
from ai_backend.tools.definitions import ToolContext, ToolResult, ToolSpec, _transaction_facts

DOWNLOAD_NOTE = (
    "The chat shows the customer a download button for the PDF. Don't write links, URLs or "
    "file IDs, and don't repeat the report's figures unless the customer asks; just say the "
    "PDF is ready and what it covers."
)


async def generate_report(ctx: ToolContext, args: ReportArgs) -> ToolResult:
    if ctx.files is None:
        return ToolResult.error("files_unavailable", "Files can't be generated here.")
    policy_facts = []
    if args.report == "transaction_receipt" and args.transaction_id:
        facts = await _transaction_facts(ctx, args.transaction_id)
        policy_facts = [facts] if facts else []
    try:
        stored = await service.generate(
            ctx.files,
            ctx.bank,
            ctx.session,
            args,
            lang=ctx.language,
            conversation_id=ctx.conversation_id,
            today=ctx.today,
            now=datetime.now(UTC),  # real time: the download link lives in real time
            ttl=ctx.file_ttl,
        )
    except ReportUnavailable as exc:
        result = ToolResult.error(exc.code, exc.message)
        result.policy_facts += policy_facts
        return result
    except ValueError as exc:
        return ToolResult.error("invalid_arguments", str(exc)[:300])
    data = {
        "report": args.report,
        "filename": stored.filename,
        "format": "pdf",
        "records": stored.rows,
        "size_bytes": stored.size_bytes,
        "note": DOWNLOAD_NOTE,
    }
    return ToolResult(ok=True, data=data, policy_facts=policy_facts, files=[stored.ref()])


REPORT_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "generate_report",
        "Create a PDF report the customer can download from the chat. Only these reports "
        "exist: account_statement (transactions of a period, for one account or card or all), "
        "balances (accounts, cards, loans and totals today), spending (spending by month, "
        "category and card), recurring_payments (payments expected this month) and "
        "transaction_receipt (receipt of one transaction). The system reads the data from the "
        "bank itself: you only choose the report and its parameters, so don't read the data "
        "first, except search_transactions to find the transaction_id of a receipt. Use it "
        "when the customer asks for a PDF, a statement or extract document, a receipt or "
        "proof of a transaction. For Excel or CSV use generate_files. If they want a PDF of "
        "something not on this list, say which PDFs you can make.",
        ReportArgs,  # type: ignore[arg-type]
        "read",
        generate_report,
    ),
)
