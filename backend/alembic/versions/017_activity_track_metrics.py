"""add computed track-metric columns to synced_activities

Aggregate scalars (queryable for overview stats) + metrics_detail JSON (zones,
splits) + gzipped downsampled per-point series for charts. Populated by the
backfill cron (app.jobs). See docs/GPX_ANALYSIS_PLAN.md.

Revision ID: 017
Revises: 016
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "017"
down_revision: Union[str, Sequence[str], None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ("metrics_computed_at", sa.DateTime(timezone=True)),
    ("moving_time_s", sa.Integer()),
    ("elevation_down_m", sa.Float()),
    ("calories", sa.Float()),
    ("avg_speed_ms", sa.Float()),
    ("avg_hr", sa.Float()),
    ("max_hr", sa.Float()),
    ("avg_power", sa.Float()),
    ("max_power", sa.Float()),
    ("normalized_power", sa.Float()),
    ("tss", sa.Float()),
    ("avg_cadence", sa.Float()),
    ("metrics_available", sa.JSON()),
    ("metrics_detail", sa.JSON()),
    ("track_gz", sa.LargeBinary()),
]


def upgrade() -> None:
    for name, coltype in _COLUMNS:
        op.add_column("synced_activities", sa.Column(name, coltype, nullable=True))
    op.create_index(
        "ix_synced_activities_metrics_computed_at",
        "synced_activities",
        ["metrics_computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_synced_activities_metrics_computed_at", table_name="synced_activities")
    for name, _ in reversed(_COLUMNS):
        op.drop_column("synced_activities", name)
