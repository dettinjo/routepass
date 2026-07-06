from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

UTC = UTC


class UserAuditLog(Base):
    """Compliance / security audit trail for sensitive user-facing actions.

    Rows survive account deletion: the FK is ON DELETE SET NULL, so user_id
    becomes NULL but the row is retained for compliance purposes.
    """

    __tablename__ = "user_audit_log"
    __table_args__ = (sa.Index("ix_user_audit_log_user_occurred", "user_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # action values: account_created, account_deleted, password_changed,
    #   api_key_created, api_key_revoked, strava_connected, strava_disconnected,
    #   komoot_connected, komoot_disconnected, export_requested
    action: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    extra: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
