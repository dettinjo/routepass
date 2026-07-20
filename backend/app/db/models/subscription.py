from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

UTC = timezone.utc

if TYPE_CHECKING:
    from app.db.models.user import User


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        sa.CheckConstraint(
            "tier IN ('free', 'pro', 'business', 'lifetime')",
            name="ck_subscriptions_tier",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'past_due', 'canceled', 'trialing')",
            name="ck_subscriptions_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(sa.String, unique=True, nullable=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(
        sa.String, unique=True, nullable=True
    )
    stripe_price_id: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    tier: Mapped[str] = mapped_column(sa.String, nullable=False, default="free")
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="active")
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    activities_synced_this_period: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0
    )
    period_reset_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
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
    user: Mapped["User"] = relationship("User", back_populates="subscription")


class ApiKey(Base):
    __tablename__ = "api_keys"

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
    key_hash: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(sa.String, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

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
    url: Mapped[str] = mapped_column(sa.String, nullable=False)
    secret: Mapped[str] = mapped_column(sa.String, nullable=False)
    events: Mapped[list] = mapped_column(sa.JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    failure_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    email_on_sync_error: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    email_on_daily_summary: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    email_on_conflict: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    webhook_on_sync: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)


class LicenseCache(Base):
    __tablename__ = "license_cache"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    license_key: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(sa.String, nullable=False)
    max_users: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    features: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    issued_to_hash: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    validated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    grace_until: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
