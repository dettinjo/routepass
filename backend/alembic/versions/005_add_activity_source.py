"""Add source column to synced_activities, make sync_direction nullable.

Revision ID: 005
Revises: 004
Create Date: 2026-04-26 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add source column (komoot | strava | import)
    op.add_column(
        "synced_activities",
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default="komoot",
        ),
    )

    # 2. Make sync_direction nullable for locally-imported activities
    op.alter_column("synced_activities", "sync_direction", nullable=True)

    # 3. Drop the old CHECK constraint and replace it with one that allows NULL
    op.drop_constraint(
        "ck_synced_activities_sync_direction",
        "synced_activities",
        type_="check",
    )
    op.create_check_constraint(
        "ck_synced_activities_sync_direction",
        "synced_activities",
        "sync_direction IS NULL OR sync_direction IN ('komoot_to_strava', 'strava_to_komoot')",
    )

    # 4. Add CHECK constraint for source column
    op.create_check_constraint(
        "ck_synced_activities_source",
        "synced_activities",
        "source IN ('komoot', 'strava', 'import')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_synced_activities_source", "synced_activities", type_="check")
    op.drop_constraint("ck_synced_activities_sync_direction", "synced_activities", type_="check")
    op.create_check_constraint(
        "ck_synced_activities_sync_direction",
        "synced_activities",
        "sync_direction IN ('komoot_to_strava', 'strava_to_komoot')",
    )
    op.alter_column("synced_activities", "sync_direction", nullable=False)
    op.drop_column("synced_activities", "source")
