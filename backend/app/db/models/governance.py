"""Admin-editable API-management registry and economic-governor config.

Phase 1 (dark): these tables are the source of truth for per-provider capacity and
cost and the governor's economic knobs. Nothing enforces them yet — the limiter and
scheduler start reading from here in later phases. See RATE_LIMIT_ARCHITECTURE.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

UTC = timezone.utc

ROLE_VALUES = ("source", "destination", "both")
AUTH_TYPE_VALUES = ("oauth_pool", "credentials", "api_key")
REFRESH_STRATEGY_VALUES = ("webhook", "poll", "none")


class ProviderPolicy(Base):
    """One row per provider platform. Admin-editable capacity, cost and import policy."""

    __tablename__ = "provider_policy"
    __table_args__ = (
        sa.CheckConstraint(
            f"role IN ({', '.join(repr(v) for v in ROLE_VALUES)})",
            name="ck_provider_policy_role",
        ),
        sa.CheckConstraint(
            f"auth_type IN ({', '.join(repr(v) for v in AUTH_TYPE_VALUES)})",
            name="ck_provider_policy_auth_type",
        ),
        sa.CheckConstraint(
            f"refresh_strategy IN ({', '.join(repr(v) for v in REFRESH_STRATEGY_VALUES)})",
            name="ck_provider_policy_refresh_strategy",
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(sa.String, nullable=False)
    auth_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    supports_webhooks: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    # Human-readable subscription/tier context (e.g. "Standard, self-upgraded to
    # 10 athletes" or "Free / fair-use, no published limit") — the raw numbers
    # below don't explain themselves, this does. Free text, admin-editable.
    tier_label: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # Polling cadence (source platforms)
    default_poll_min: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    min_poll_min: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # Generic per-account / global request budget (non-Strava)
    window_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    window_limit: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    daily_limit: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # Strava dual-bucket per-app defaults (read vs overall)
    read_limit_15min: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    read_limit_daily: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    overall_limit_15min: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    overall_limit_daily: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # Capacity + economics
    athlete_capacity: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    monthly_cost_cents: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # Import policy
    initial_backfill_limit: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    page_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    refresh_strategy: Mapped[str] = mapped_column(sa.String, nullable=False, default="poll")

    # Fairness knobs (percentages)
    headroom_pct: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=10)
    free_reserve_pct: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=20)

    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class GovernorConfig(Base):
    """Singleton (id=1) holding the economic-governor knobs."""

    __tablename__ = "governor_config"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, default=1)
    # Cost must stay <= revenue * coverage_target_pct / 100 before auto-provisioning.
    coverage_target_pct: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=70)
    # Share of capacity + athlete slots reserved for paying users.
    paid_reservation_pct: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=40)
    free_degradation_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    infra_monthly_cost_cents: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
