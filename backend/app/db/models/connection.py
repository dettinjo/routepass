from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

UTC = timezone.utc

PLATFORM_VALUES = (
    "komoot",
    "strava",
    "garmin",
    "polar",
    "wahoo",
    "intervals_icu",
    "runalyze",
    "trainingpeaks",
    "webhook",
)
STATUS_VALUES = ("active", "error", "disconnected")

if TYPE_CHECKING:
    from app.db.models.pipeline import Pipeline
    from app.db.models.user import User


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        sa.CheckConstraint(
            f"platform IN ({', '.join(repr(p) for p in PLATFORM_VALUES)})",
            name="ck_connections_platform",
        ),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in STATUS_VALUES)})",
            name="ck_connections_status",
        ),
        sa.Index("ix_connections_user_platform", "user_id", "platform"),
    )

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(sa.String, nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String, nullable=False, default="")
    credentials_enc: Mapped[Optional[bytes]] = mapped_column(sa.LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="active")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    meta: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="connections")
    source_pipelines: Mapped[list["Pipeline"]] = relationship(
        "Pipeline",
        foreign_keys="Pipeline.source_connection_id",
        back_populates="source_connection",
    )
    dest_pipelines: Mapped[list["Pipeline"]] = relationship(
        "Pipeline",
        foreign_keys="Pipeline.dest_connection_id",
        back_populates="dest_connection",
    )
