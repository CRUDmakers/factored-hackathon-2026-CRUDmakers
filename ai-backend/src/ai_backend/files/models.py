"""The JSON the assistant sends to build spreadsheets, and the record of a generated file.

The same payload is accepted by the `generate_files` tool and by `POST /v1/files`. The schema is
deliberately flat (strings, numbers, small lists) so every provider's tool calling can fill it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, model_validator

FileFormat = Literal["xlsx", "csv"]
# What can be stored and downloaded: the spreadsheets above plus the PDF reports (`reports/`).
StoredFormat = Literal["xlsx", "csv", "pdf"]
ColumnType = Literal["text", "number", "money", "date"]
# A cell as the model writes it. One JSON-schema type list (not anyOf), so the tool schema
# stays simple; `number` columns also accept numbers written as text ("1,234.50" is not one).
Cell = Annotated[
    str | int | float | bool | None,
    WithJsonSchema({"type": ["string", "number", "null"]}),
]

MAX_FILES = 5
MAX_SHEETS = 10
MAX_COLUMNS = 30
MAX_ROWS = 2000
MAX_CELL_TEXT = 1000

MEDIA_TYPES: dict[str, str] = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
}
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_SHEET_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnSpec(_Model):
    header: str = Field(min_length=1, max_length=100)
    type: ColumnType = Field(
        default="text",
        description="text; number; money (2 decimals); date (YYYY-MM-DD or ISO date-time).",
    )


class SheetSpec(_Model):
    name: str = Field(min_length=1, max_length=31, description="Sheet name (xlsx tab).")
    columns: list[ColumnSpec] = Field(min_length=1, max_length=MAX_COLUMNS)
    rows: list[list[Cell]] = Field(
        max_length=MAX_ROWS,
        description="One list per row, values in the same order as `columns`. Use null for "
        "an empty cell.",
    )

    @model_validator(mode="after")
    def _shape(self) -> SheetSpec:
        if _SHEET_FORBIDDEN.search(self.name):
            raise ValueError("sheet name can't contain [ ] : * ? / \\")
        width = len(self.columns)
        for i, row in enumerate(self.rows):
            if len(row) != width:
                raise ValueError(f"row {i} has {len(row)} values; expected {width}, one per column")
            for value in row:
                if isinstance(value, str) and len(value) > MAX_CELL_TEXT:
                    raise ValueError(f"row {i}: a text value is longer than {MAX_CELL_TEXT}")
        return self


class FileSpec(_Model):
    filename: str = Field(
        min_length=1, max_length=80, description="Name without extension, e.g. extracto_junio."
    )
    format: FileFormat = Field(description="xlsx (Excel) or csv.")
    sheets: list[SheetSpec] = Field(
        min_length=1, max_length=MAX_SHEETS, description="A csv file has exactly one sheet."
    )

    @model_validator(mode="after")
    def _csv_one_sheet(self) -> FileSpec:
        if self.format == "csv" and len(self.sheets) != 1:
            raise ValueError("a csv file has exactly one sheet")
        names = [s.name.casefold() for s in self.sheets]
        if len(set(names)) != len(names):
            raise ValueError("sheet names must be unique in a file")
        return self

    def download_name(self) -> str:
        """A filesystem-safe name with the right extension."""
        stem = _UNSAFE_NAME.sub("_", self.filename).strip(" ._") or "archivo"
        stem = re.sub(rf"\.{self.format}$", "", stem, flags=re.IGNORECASE)
        return f"{stem}.{self.format}"


class GenerateFilesArgs(_Model):
    files: list[FileSpec] = Field(min_length=1, max_length=MAX_FILES)


class StoredFile(_Model):
    """A generated file. `content` never goes to the model or into traces."""

    file_id: str
    customer_id: str
    conversation_id: str | None
    filename: str
    format: StoredFormat
    media_type: str
    size_bytes: int
    rows: int  # data rows (spreadsheets) or records listed (PDF reports)
    created_at: datetime
    expires_at: datetime
    content: bytes = Field(repr=False)

    def ref(self) -> dict[str, object]:
        """What the chat response and the model get: everything but the content."""
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "format": self.format,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "rows": self.rows,
            "download_url": f"/v1/files/{self.file_id}",
            "expires_at": self.expires_at.isoformat(),
        }
