from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

UTC = timezone.utc

if TYPE_CHECKING:
    from app.db.models.connection import Connection
    from app.db.models.sync import SyncedActivity, SyncRule
    from app.db.models.user import User


class Pipeline(Base):
    __tablename__ = "pipelines"

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
    source_connection_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    dest_connection_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
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
    user: Mapped["User"] = relationship("User", back_populates="pipelines")
    source_connection: Mapped["Connection"] = relationship(
        "Connection",
        foreign_keys=[source_connection_id],
        back_populates="source_pipelines",
    )
    dest_connection: Mapped["Connection"] = relationship(
        "Connection",
        foreign_keys=[dest_connection_id],
        back_populates="dest_pipelines",
    )
    sync_rules: Mapped[list["SyncRule"]] = relationship("SyncRule", back_populates="pipeline")
    synced_activities: Mapped[list["SyncedActivity"]] = relationship(
        "SyncedActivity", back_populates="pipeline"
    )
