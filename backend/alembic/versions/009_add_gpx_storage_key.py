"""Add gpx_storage_key column to synced_activities for object storage

Revision ID: 009
Revises: 008
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "synced_activities",
        sa.Column("gpx_storage_key", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_synced_activities_gpx_storage_key",
        "synced_activities",
        ["gpx_storage_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_synced_activities_gpx_storage_key", table_name="synced_activities")
    op.drop_column("synced_activities", "gpx_storage_key")
