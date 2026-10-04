"""Lays a `Report` out as an A4 PDF. Pure: same report and time, same bytes (reportlab's
invariant mode drops the random document ID and the creation timestamp).

All text is escaped before it reaches reportlab's paragraph markup: merchant names and
descriptions come from bank records, not from code we trust.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
from reportlab.platypus import (
    Table as RLTable,
)
from reportlab.platypus import (
    TableStyle as RLTableStyle,
)

from ai_backend.reports.layout import Bars, Fields, Note, Report, Section, Table
from ai_backend.reports.models import ReportLang

BRAND = "Banco LATAM"
NAVY = colors.HexColor("#1F3A68")
ACCENT = colors.HexColor("#2E6FD8")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
STRIPE = colors.HexColor("#F5F7FB")
CARD = colors.HexColor("#EEF3FB")
MARGIN = 16 * mm
HEADER_H = 26 * mm
WIDTH = A4[0] - 2 * MARGIN

FOOTER = {
    "es": "Documento informativo generado por el asistente virtual de {brand}. "
    "Cliente {customer} · Emitido el {at} · Página {page} de {pages}",
    "pt": "Documento informativo gerado pelo assistente virtual do {brand}. "
    "Cliente {customer} · Emitido em {at} · Página {page} de {pages}",
}

_BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=8.5, leading=11)
STYLES = {
    "title": ParagraphStyle("title", _BASE, fontName="Helvetica-Bold", fontSize=17, leading=21),
    "subtitle": ParagraphStyle("subtitle", _BASE, fontSize=9.5, textColor=MUTED, leading=13),
    "h2": ParagraphStyle(
        "h2", _BASE, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=NAVY
    ),
    "cell": _BASE,
    "cell_r": ParagraphStyle("cell_r", _BASE, alignment=TA_RIGHT),
    "head": ParagraphStyle("head", _BASE, fontName="Helvetica-Bold", textColor=colors.white),
    "head_r": ParagraphStyle(
        "head_r", _BASE, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_RIGHT
    ),
    "bold": ParagraphStyle("bold", _BASE, fontName="Helvetica-Bold"),
    "bold_r": ParagraphStyle("bold_r", _BASE, fontName="Helvetica-Bold", alignment=TA_RIGHT),
    "label": ParagraphStyle("label", _BASE, fontSize=7.5, textColor=MUTED, leading=9.5),
    "figure": ParagraphStyle(
        "figure", _BASE, fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=NAVY
    ),
    "note": ParagraphStyle("note", _BASE, fontSize=7.5, textColor=MUTED, leading=10),
}


def render(report: Report, *, lang: ReportLang, customer_id: str, generated_at: datetime) -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=HEADER_H + 10 * mm,
        bottomMargin=MARGIN + 6 * mm,
        title=report.title,
        author=BRAND,
        subject=report.subtitle,
        creator=BRAND,
        invariant=1,
    )
    footer = {
        "brand": BRAND,
        "customer": customer_id,
        "at": generated_at.strftime("%d/%m/%Y %H:%M UTC"),
    }
    story: list = [
        Paragraph(_text(report.title), STYLES["title"]),
        Spacer(0, 1.5 * mm),
        Paragraph(_text(report.subtitle), STYLES["subtitle"]),
        Spacer(0, 5 * mm),
    ]
    if report.highlights:
        story += [_highlights(report.highlights), Spacer(0, 6 * mm)]
    for section in report.sections:
        story += _section(section)
    doc.build(story, canvasmaker=_canvas(FOOTER[lang], footer))
    return out.getvalue()


def _text(value: str) -> str:
    return escape(value)


# ---------- page furniture ----------


def _canvas(template: str, values: dict[str, str]) -> type[Canvas]:
    """A canvas that draws the header band and a 'page X of Y' footer on every page."""

    class _Canvas(Canvas):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self) -> None:  # noqa: N802 (reportlab's name)
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            for number, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                self._furniture(number, len(self._pages))
                super().showPage()
            super().save()

        def _furniture(self, page: int, pages: int) -> None:
            width, height = A4
            self.saveState()
            self.setFillColor(NAVY)
            self.rect(0, height - HEADER_H, width, HEADER_H, stroke=0, fill=1)
            self.setFillColor(ACCENT)
            self.rect(0, height - HEADER_H - 1.2 * mm, width, 1.2 * mm, stroke=0, fill=1)
            self.setFillColor(colors.white)
            self.setFont("Helvetica-Bold", 15)
            self.drawString(MARGIN, height - HEADER_H / 2 - 5, BRAND)
            self.setStrokeColor(LINE)
            self.line(MARGIN, MARGIN + 3 * mm, width - MARGIN, MARGIN + 3 * mm)
            self.setFillColor(MUTED)
            self.setFont("Helvetica", 7)
            self.drawString(MARGIN, MARGIN, template.format(page=page, pages=pages, **values))
            self.restoreState()

    return _Canvas


# ---------- blocks ----------


def _highlights(items: list[tuple[str, str]]) -> RLTable:
    cells = [
        [Paragraph(_text(label), STYLES["label"]), Paragraph(_text(value), STYLES["figure"])]
        for label, value in items
    ]
    gap = 3 * mm
    width = (WIDTH - gap * (len(items) - 1)) / len(items)
    inner = [RLTable([[c[0]], [c[1]]], colWidths=[width], style=_card_style()) for c in cells]
    row: list = []
    widths: list[float] = []
    for i, card in enumerate(inner):
        if i:
            row.append("")
            widths.append(gap)
        row.append(card)
        widths.append(width)
    table = RLTable([row], colWidths=widths)
    table.setStyle(
        RLTableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)])
    )
    return table


def _card_style() -> RLTableStyle:
    return RLTableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, -1), CARD),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACCENT),
        ]
    )


def _section(section: Section) -> list:
    if isinstance(section, Note):
        return [Paragraph(_text(section.text), STYLES["note"]), Spacer(0, 4 * mm)]
    heading = [Paragraph(_text(section.title), STYLES["h2"]), Spacer(0, 2 * mm)]
    if isinstance(section, Table):
        if not section.rows:
            body = Paragraph(_text(section.empty), STYLES["note"])
            return [KeepTogether([*heading, body]), Spacer(0, 6 * mm)]
        table = _table(section)
        # Keep the heading with the first rows; long tables still split across pages.
        return [*heading, table, Spacer(0, 6 * mm)]
    if isinstance(section, Fields):
        return [KeepTogether([*heading, _fields(section)]), Spacer(0, 6 * mm)]
    return [KeepTogether([*heading, _bars(section)]), Spacer(0, 6 * mm)]


def _table(t: Table) -> RLTable:
    scale = WIDTH / sum(t.widths)

    def styled(values: list[str], kind: str) -> list[Paragraph]:
        return [
            Paragraph(_text(v), STYLES[kind + ("_r" if a == "R" else "")])
            for v, a in zip(values, t.align, strict=True)
        ]

    data = [styled(t.headers, "head"), *(styled(r, "cell") for r in t.rows)]
    if t.total:
        data.append(styled(t.total, "bold"))
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
    ]
    style += [("BACKGROUND", (0, i), (-1, i), STRIPE) for i in range(2, len(t.rows) + 1, 2)]
    if t.total:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 1, NAVY))
    return RLTable(
        data,
        colWidths=[w * scale for w in t.widths],
        repeatRows=1,
        style=RLTableStyle(style),
    )


def _fields(f: Fields) -> RLTable:
    pairs = [
        [Paragraph(_text(label), STYLES["label"]), Paragraph(_text(value), STYLES["bold"])]
        for label, value in f.items
    ]
    rows = []
    for i in range(0, len(pairs), 2):
        right = pairs[i + 1] if i + 1 < len(pairs) else ["", ""]
        rows.append([*pairs[i], *right])
    half = WIDTH / 2
    return RLTable(
        rows,
        colWidths=[half * 0.38, half * 0.62, half * 0.38, half * 0.62],
        style=RLTableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ]
        ),
    )


def _bars(b: Bars) -> RLTable:
    largest = max((v for _, v, _ in b.items), default=Decimal(0)) or Decimal(1)
    bar_width = WIDTH * 0.45
    rows = []
    for label, value, shown in b.items:
        drawing = Drawing(bar_width, 9)
        drawing.add(Rect(0, 1, bar_width, 7, fillColor=STRIPE, strokeColor=None))
        filled = float(max(value, Decimal(0)) / largest) * bar_width
        drawing.add(Rect(0, 1, filled, 7, fillColor=ACCENT, strokeColor=None))
        rows.append(
            [
                Paragraph(_text(label), STYLES["cell"]),
                drawing,
                Paragraph(_text(shown), STYLES["cell_r"]),
            ]
        )
    return RLTable(
        rows,
        colWidths=[WIDTH * 0.22, bar_width + 6, WIDTH * 0.33 - 6],
        style=RLTableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        ),
    )
