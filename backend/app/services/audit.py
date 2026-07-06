"""Lightweight helper for writing UserAuditLog entries.

Call `await audit(db, user_id, action, request)` from any endpoint that
performs a sensitive action.  The helper never raises — a failed audit
write is logged but does not abort the primary operation.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import UserAuditLog

_logger = logging.getLogger(__name__)


async def write_audit(
    db: AsyncSession,
    user_id: UUID | None,
    action: str,
    request: Request | None = None,
    extra: dict | None = None,
) -> None:
    """Append one UserAuditLog row.  Flushes but does NOT commit — the caller
    owns the transaction and will commit after the primary write."""
    try:
        ip = None
        ua = None
        if request is not None:
            forwarded = request.headers.get("X-Forwarded-For")
            ip = (
                (forwarded.split(",")[0].strip() if forwarded else None) or request.client.host
                if request.client
                else None
            )
            ua = request.headers.get("User-Agent")

        db.add(
            UserAuditLog(
                user_id=user_id,
                action=action,
                ip_address=ip,
                user_agent=ua,
                extra=extra,
            )
        )
        await db.flush()
    except Exception as exc:
        _logger.warning("write_audit failed (action=%s user=%s): %s", action, user_id, exc)
