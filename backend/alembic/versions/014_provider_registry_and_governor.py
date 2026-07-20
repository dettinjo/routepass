"""provider registry, governor config, strava_apps cost/capacity columns

Phase 1 of the API limit management system (dark — nothing enforces these yet).
See RATE_LIMIT_ARCHITECTURE.md.

Revision ID: 014
Revises: 013
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "014"
down_revision: Union[str, Sequence[str], None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_policy",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("auth_type", sa.String(), nullable=False),
        sa.Column("supports_webhooks", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("default_poll_min", sa.Integer(), nullable=True),
        sa.Column("min_poll_min", sa.Integer(), nullable=True),
        sa.Column("window_seconds", sa.Integer(), nullable=True),
        sa.Column("window_limit", sa.Integer(), nullable=True),
        sa.Column("daily_limit", sa.Integer(), nullable=True),
        sa.Column("read_limit_15min", sa.Integer(), nullable=True),
        sa.Column("read_limit_daily", sa.Integer(), nullable=True),
        sa.Column("overall_limit_15min", sa.Integer(), nullable=True),
        sa.Column("overall_limit_daily", sa.Integer(), nullable=True),
        sa.Column("athlete_capacity", sa.Integer(), nullable=True),
        sa.Column("monthly_cost_cents", sa.Integer(), nullable=False),
        sa.Column("initial_backfill_limit", sa.Integer(), nullable=True),
        sa.Column("page_size", sa.Integer(), nullable=True),
        sa.Column("refresh_strategy", sa.String(), nullable=False),
        sa.Column("headroom_pct", sa.Integer(), nullable=False),
        sa.Column("free_reserve_pct", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('source', 'destination', 'both')", name="ck_provider_policy_role"
        ),
        sa.CheckConstraint(
            "auth_type IN ('oauth_pool', 'credentials', 'api_key')",
            name="ck_provider_policy_auth_type",
        ),
        sa.CheckConstraint(
            "refresh_strategy IN ('webhook', 'poll', 'none')",
            name="ck_provider_policy_refresh_strategy",
        ),
        sa.UniqueConstraint("platform", name="uq_provider_policy_platform"),
    )
    op.create_index("ix_provider_policy_platform", "provider_policy", ["platform"])

    op.create_table(
        "governor_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("coverage_target_pct", sa.Integer(), nullable=False),
        sa.Column("paid_reservation_pct", sa.Integer(), nullable=False),
        sa.Column("free_degradation_enabled", sa.Boolean(), nullable=False),
        sa.Column("infra_monthly_cost_cents", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # strava_apps: per-app cost/capacity. server_default backfills existing rows.
    op.add_column(
        "strava_apps", sa.Column("athlete_cap", sa.Integer(), nullable=False, server_default="10")
    )
    op.add_column(
        "strava_apps",
        sa.Column("monthly_cost_cents", sa.Integer(), nullable=False, server_default="1199"),
    )
    op.add_column(
        "strava_apps",
        sa.Column("read_limit_15min", sa.Integer(), nullable=False, server_default="200"),
    )
    op.add_column(
        "strava_apps",
        sa.Column("read_limit_daily", sa.Integer(), nullable=False, server_default="2000"),
    )
    op.add_column(
        "strava_apps",
        sa.Column("overall_limit_15min", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "strava_apps",
        sa.Column("overall_limit_daily", sa.Integer(), nullable=False, server_default="1000"),
    )
    # Rows are seeded idempotently by app.core.registry.ensure_registry_seeded() on
    # startup (and in tests), so the schema-only migration works with create_all too.


def downgrade() -> None:
    for col in (
        "overall_limit_daily",
        "overall_limit_15min",
        "read_limit_daily",
        "read_limit_15min",
        "monthly_cost_cents",
        "athlete_cap",
    ):
        op.drop_column("strava_apps", col)
    op.drop_table("governor_config")
    op.drop_index("ix_provider_policy_platform", table_name="provider_policy")
    op.drop_table("provider_policy")
