from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

UTC = UTC

if TYPE_CHECKING:
    from app.db.models.connection import Connection
    from app.db.models.pipeline import Pipeline
    from app.db.models.subscription import Subscription


class StravaApp(Base):
    __tablename__ = "strava_apps"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False)
    client_secret: Mapped[bytes] = mapped_column(sa.LargeBinary, nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    daily_requests: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    daily_reset_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    # Per-app capacity + cost (admin-editable; see RATE_LIMIT_ARCHITECTURE.md).
    athlete_cap: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=10)
    monthly_cost_cents: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1199)
    read_limit_15min: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=200)
    read_limit_daily: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=2000)
    # Defaults match Strava's "self-upgraded" (10-athlete) Standard tier, which is
    # what every real production app ends up on — not the 1-athlete "single-player"
    # defaults for a freshly created, unconfigured app. Kept in sync automatically
    # per-app by RateLimiter._maybe_sync_live_limits from Strava's response headers.
    overall_limit_15min: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=400)
    overall_limit_daily: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=4000)


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    email: Mapped[str] = mapped_column(
        sa.String,
        unique=True,
        nullable=False,
        index=True,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    password_hash: Mapped[str | None] = mapped_column(sa.String, nullable=True)
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
    last_login_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    name: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    # Training profile — unlocks TSS + proper power/HR zones in metric compute.
    ftp: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    hr_max: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # Relationships
    subscription: Mapped[Subscription] = relationship(
        "Subscription", back_populates="user", uselist=False
    )
    strava_token: Mapped[StravaToken] = relationship(
        "StravaToken", back_populates="user", uselist=False
    )
    sync_rules: Mapped[list] = relationship("SyncRule", back_populates="user")
    synced_activities: Mapped[list] = relationship("SyncedActivity", back_populates="user")
    connections: Mapped[list[Connection]] = relationship("Connection", back_populates="user")
    pipelines: Mapped[list[Pipeline]] = relationship("Pipeline", back_populates="user")


class StravaToken(Base):
    __tablename__ = "strava_tokens"

    user_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    strava_app_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        sa.ForeignKey("strava_apps.id"),
        nullable=True,
    )
    strava_athlete_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        unique=True,
        nullable=False,
        index=True,
    )
    access_token: Mapped[bytes] = mapped_column(sa.LargeBinary, nullable=False)
    refresh_token: Mapped[bytes] = mapped_column(sa.LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    scope: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        default="activity:write,activity:read_all",
    )
    connected_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="strava_token")
