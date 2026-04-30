from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

UTC = UTC

if TYPE_CHECKING:
    from app.db.models.pipeline import Pipeline
    from app.db.models.user import User


class SyncedActivity(Base):
    __tablename__ = "synced_activities"
    __table_args__ = (
        sa.CheckConstraint(
            "sync_direction IS NULL OR sync_direction IN ("
            "'komoot_to_strava', 'strava_to_komoot',"
            "'komoot_to_intervals_icu', 'komoot_to_runalyze',"
            "'strava_to_intervals_icu', 'strava_to_runalyze',"
            "'import_to_strava', 'import_to_komoot'"
            ")",
            name="ck_synced_activities_sync_direction",
        ),
        sa.CheckConstraint(
            "sync_status IN ('pending', 'processing', 'completed', 'failed', 'conflict')",
            name="ck_synced_activities_sync_status",
        ),
        sa.CheckConstraint(
            "source IN ('komoot', 'strava', 'import', 'garmin', 'polar', 'wahoo')",
            name="ck_synced_activities_source",
        ),
        # Composite unique: one row per (user, komoot_tour, destination_platform).
        # NULL komoot_tour_id is fine — SQL NULL != NULL so Strava-native and Garmin
        # activities are not constrained by this. Each source handler handles its own dedup.
        sa.UniqueConstraint(
            "user_id",
            "komoot_tour_id",
            "destination_platform",
            name="uq_synced_activities_user_komoot_dest",
        ),
        sa.UniqueConstraint(
            "user_id", "strava_activity_id", name="uq_synced_activities_user_strava"
        ),
        sa.Index("ix_synced_activities_user_synced_at", "user_id", "synced_at"),
        sa.Index("ix_synced_activities_dest_platform", "destination_platform"),
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
    komoot_tour_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    strava_activity_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # Hub destination fields — set when an activity is pushed to an external platform.
    destination_platform: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    destination_activity_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    sync_direction: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    source: Mapped[str] = mapped_column(sa.String, nullable=False, default="komoot")
    synced_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    sync_status: Mapped[str] = mapped_column(sa.String, nullable=False, default="completed")
    activity_name: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    sport_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    elevation_up_m: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    conflict_reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    gpx_data: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)
    pipeline_id: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("pipelines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="synced_activities")
    pipeline: Mapped[Pipeline | None] = relationship("Pipeline", back_populates="synced_activities")


class UserSyncState(Base):
    __tablename__ = "user_sync_state"

    user_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_komoot_sync_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_strava_sync_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    total_synced_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class SyncRule(Base):
    __tablename__ = "sync_rules"
    __table_args__ = (
        sa.CheckConstraint(
            "direction IN ('komoot_to_strava', 'strava_to_komoot', 'both')",
            name="ck_sync_rules_direction",
        ),
        sa.Index("ix_sync_rules_user_order", "user_id", "rule_order"),
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
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    direction: Mapped[str] = mapped_column(sa.String, nullable=False)
    rule_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    conditions: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    actions: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    pipeline_id: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("pipelines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sync_rules")
    pipeline: Mapped[Pipeline | None] = relationship("Pipeline", back_populates="sync_rules")


class JobAuditLog(Base):
    __tablename__ = "job_audit_log"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    job_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=5)
    enqueued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    retry_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    payload: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
