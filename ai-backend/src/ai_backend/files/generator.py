"""Builds xlsx and csv files from a `FileSpec`. Pure: same spec, same bytes (no I/O, no clock).

Values are typed by their column (money and numbers become real numbers, dates real dates), so
the customer can sum and filter them in Excel. Text that a spreadsheet would run as a formula
(`=`, `+`, `-`, `@` at the start) is always written as text: cell values come from bank records
and the model, never from code we trust.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ai_backend.files.models import ColumnSpec, FileSpec, SheetSpec

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
NUMBER_FORMATS = {
    "money": "#,##0.00",
    "number": "General",
    "date": "yyyy-mm-dd",
    "datetime": "yyyy-mm-dd hh:mm",
}
HEADER_FILL = PatternFill("solid", fgColor="1F3A68")
HEADER_FONT = Font(bold=True, color="FFFFFF")
MAX_WIDTH = 50


def build(spec: FileSpec) -> tuple[bytes, int]:
    """The file's bytes and its number of data rows (all sheets)."""
    rows = sum(len(s.rows) for s in spec.sheets)
    if spec.format == "csv":
        return _csv(spec.sheets[0]), rows
    return _xlsx(spec), rows


def typed(value: Any, column: ColumnSpec) -> Any:
    """The cell's value for its column type; anything that doesn't parse stays as given."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if column.type in ("number", "money") and not isinstance(value, bool):
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            return value
        if not number.is_finite():
            return value
        return number.quantize(Decimal("0.01")) if column.type == "money" else number
    if column.type == "date" and isinstance(value, str):
        text = value.strip()
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return value
        if len(text) <= 10:
            return moment.date()
        return moment.replace(tzinfo=None)  # spreadsheets have no time zones
    return value


# ---------- xlsx ----------


def _xlsx(spec: FileSpec) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in spec.sheets:
        ws = wb.create_sheet(sheet.name)
        widths = [len(c.header) for c in sheet.columns]
        for col, column in enumerate(sheet.columns, start=1):
            cell = ws.cell(row=1, column=col, value=_clean(column.header))
            _as_text(cell)
            cell.fill, cell.font = HEADER_FILL, HEADER_FONT
            cell.alignment = Alignment(vertical="center")
        for r, row in enumerate(sheet.rows, start=2):
            for col, (raw, column) in enumerate(zip(row, sheet.columns, strict=True), start=1):
                value = typed(raw, column)
                if isinstance(value, str):
                    value = _clean(value)
                cell = ws.cell(row=r, column=col, value=value)
                if isinstance(value, str):
                    _as_text(cell)
                elif isinstance(value, datetime):
                    cell.number_format = NUMBER_FORMATS["datetime"]
                elif isinstance(value, date):
                    cell.number_format = NUMBER_FORMATS["date"]
                elif column.type in NUMBER_FORMATS and value is not None:
                    cell.number_format = NUMBER_FORMATS[column.type]
                widths[col - 1] = max(widths[col - 1], len(_display(value)))
        for col, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col)].width = min(width + 2, MAX_WIDTH)
        ws.freeze_panes = "A2"
        if sheet.rows:
            ws.auto_filter.ref = ws.dimensions
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _clean(text: str) -> str:
    # Control characters make an invalid xlsx; they carry nothing a customer needs.
    return ILLEGAL_CHARACTERS_RE.sub("", text)


def _as_text(cell: Any) -> None:
    # openpyxl turns any string starting with "=" into a formula; force it back to text.
    if cell.data_type == "f":
        cell.data_type = "s"


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return "yyyy-mm-dd hh:mm"
    if isinstance(value, date):
        return "yyyy-mm-dd"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


# ---------- csv ----------


def _csv(sheet: SheetSpec) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([_csv_text(c.header) for c in sheet.columns])
    for row in sheet.rows:
        writer.writerow([_csv_value(typed(v, c)) for v, c in zip(row, sheet.columns, strict=True)])
    # UTF-8 with BOM: Excel opens accents (ñ, ç, á) correctly only with it.
    return out.getvalue().encode("utf-8-sig")


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal | int | float) and not isinstance(value, bool):
        return str(value)
    return _csv_text(str(value))


def _csv_text(text: str) -> str:
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text
