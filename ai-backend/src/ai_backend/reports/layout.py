"""What a report says, already localised and formatted: the templates (`templates.py`) fill it
from bank data and the renderer (`pdf.py`) only lays it out. Every value is display text."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Align = Literal["L", "R"]


@dataclass(frozen=True)
class Table:
    title: str
    headers: list[str]
    rows: list[list[str]]
    align: list[Align]
    widths: list[float]  # relative; the renderer scales them to the page
    total: list[str] | None = None  # a bold last row
    empty: str = ""  # shown instead of the table when it has no rows


@dataclass(frozen=True)
class Fields:
    """Label/value pairs, two per line (a receipt, a summary)."""

    title: str
    items: list[tuple[str, str]]


@dataclass(frozen=True)
class Bars:
    """A horizontal bar per item, scaled to the largest value."""

    title: str
    items: list[tuple[str, Decimal, str]]  # label, value, value as shown


@dataclass(frozen=True)
class Note:
    text: str


Section = Table | Fields | Bars | Note


@dataclass(frozen=True)
class Report:
    filename: str  # without extension
    title: str
    subtitle: str  # period, scope
    highlights: list[tuple[str, str]] = field(default_factory=list)  # big figures on top
    sections: list[Section] = field(default_factory=list)
    rows: int = 0  # records listed, for the file reference
