"""Builds a report from the bank and stores it as a downloadable PDF (tool and HTTP share it)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from ai_backend.auth.session import Session
from ai_backend.bank.client import BankClient
from ai_backend.files.models import MEDIA_TYPES, StoredFile
from ai_backend.files.store import FileStore
from ai_backend.reports import pdf, templates
from ai_backend.reports.models import ReportArgs, ReportLang


async def generate(
    store: FileStore,
    bank: BankClient,
    session: Session,
    args: ReportArgs,
    *,
    lang: ReportLang,
    conversation_id: str | None,
    today: date,
    now: datetime,
    ttl: timedelta,
) -> StoredFile:
    """Read, lay out, store. Bank errors and `ReportUnavailable` propagate; nothing is stored."""
    report = await templates.build(bank, session, args, today, lang)
    content = pdf.render(report, lang=lang, customer_id=session.customer_id, generated_at=now)
    file = StoredFile(
        file_id=f"fil_{uuid.uuid4().hex}",
        customer_id=session.customer_id,
        conversation_id=conversation_id,
        filename=f"{report.filename}.pdf",
        format="pdf",
        media_type=MEDIA_TYPES["pdf"],
        size_bytes=len(content),
        rows=report.rows,
        created_at=now,
        expires_at=now + ttl,
        content=content,
    )
    await store.save(file)
    return file
