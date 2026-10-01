"""Turns the assistant's JSON into stored, downloadable files (tool and HTTP share it)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from ai_backend.files import generator
from ai_backend.files.models import MEDIA_TYPES, GenerateFilesArgs, StoredFile
from ai_backend.files.store import FileStore


async def generate(
    store: FileStore,
    args: GenerateFilesArgs,
    *,
    customer_id: str,
    conversation_id: str | None,
    now: datetime,
    ttl: timedelta,
) -> list[StoredFile]:
    """Build every file first, then save them: a payload that fails stores nothing."""
    built = [
        StoredFile(
            file_id=f"fil_{uuid.uuid4().hex}",
            customer_id=customer_id,
            conversation_id=conversation_id,
            filename=spec.download_name(),
            format=spec.format,
            media_type=MEDIA_TYPES[spec.format],
            size_bytes=len(content),
            rows=rows,
            created_at=now,
            expires_at=now + ttl,
            content=content,
        )
        for spec in args.files
        for content, rows in (generator.build(spec),)
    ]
    for file in built:
        await store.save(file)
    return built
