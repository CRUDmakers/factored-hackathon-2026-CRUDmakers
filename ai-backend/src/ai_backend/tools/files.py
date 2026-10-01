"""generate_files: the assistant turns data it already has into Excel/CSV files to download.

It reads nothing from the bank and changes nothing there, so the policy engine treats it as a
read (no confirmation). The rows come from earlier tool results; the prompt says so, and the
files are only as good as those results.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_backend.files import service
from ai_backend.files.models import GenerateFilesArgs
from ai_backend.tools.definitions import ToolContext, ToolResult, ToolSpec

DOWNLOAD_NOTE = (
    "The chat shows the customer a download button for each file. Don't write links, URLs or "
    "file IDs; just say which files are ready and what they contain."
)


async def generate_files(ctx: ToolContext, args: GenerateFilesArgs) -> ToolResult:
    if ctx.files is None:
        return ToolResult.error("files_unavailable", "Files can't be generated here.")
    try:
        stored = await service.generate(
            ctx.files,
            args,
            customer_id=ctx.session.customer_id,
            conversation_id=ctx.conversation_id,
            now=datetime.now(UTC),  # real time: the download link lives in real time
            ttl=ctx.file_ttl,
        )
    except ValueError as exc:
        return ToolResult.error("invalid_file", str(exc)[:300])
    data = {
        "files": [
            {"filename": f.filename, "format": f.format, "rows": f.rows, "size_bytes": f.size_bytes}
            for f in stored
        ],
        "note": DOWNLOAD_NOTE,
    }
    return ToolResult(ok=True, data=data, files=[f.ref() for f in stored])


FILE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "generate_files",
        "Create one or more spreadsheet files (Excel .xlsx or .csv) the customer can download "
        "from the chat, e.g. a transaction statement, balances or a spending summary. Fill the "
        "rows only with data from earlier tool results in this conversation (call the read "
        "tools first; never invent rows). Each file has sheets; each sheet has typed columns "
        "and rows (one list of values per row, in column order). Use type money for amounts, "
        "date for dates, and put the currency in its own column. A csv file has one sheet; "
        "use xlsx when the customer wants several tables in one file. Use only when the "
        "customer asks for a file, spreadsheet, Excel, CSV or a download.",
        GenerateFilesArgs,
        "read",
        generate_files,
    ),
)
