"""Multi-destination sync schema

- Drop uq_synced_activities_user_komoot (blocks same tour → multiple destinations)
- Add destination_platform column
- Add destination_activity_id column
- Extend sync_direction check constraint
- Add composite unique (user_id, komoot_tour_id, destination_platform)
- Backfill existing strava-destined rows

Revision ID: 007
Revises: 006
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALID_DIRECTIONS = (
    "komoot_to_strava",
    "strava_to_komoot",
    "komoot_to_intervals_icu",
    "komoot_to_runalyze",
    "strava_to_intervals_icu",
    "strava_to_runalyze",
    "import_to_strava",
    "import_to_komoot",
)


def upgrade() -> None:
    # 1. Drop old blocking unique constraint that prevented one Komoot tour
    #    from being pushed to multiple destination platforms.
    op.drop_constraint(
        "uq_synced_activities_user_komoot",
        "synced_activities",
        type_="unique",
    )

    # 2. Add new columns
    op.add_column(
        "synced_activities",
        sa.Column("destination_platform", sa.String(), nullable=True),
    )
    op.add_column(
        "synced_activities",
        sa.Column("destination_activity_id", sa.String(), nullable=True),
    )

    # 3. Drop old sync_direction check constraint and replace with extended one
    op.drop_constraint(
        "ck_synced_activities_sync_direction",
        "synced_activities",
        type_="check",
    )
    valid_str = ", ".join(f"'{d}'" for d in _VALID_DIRECTIONS)
    op.create_check_constraint(
        "ck_synced_activities_sync_direction",
        "synced_activities",
        f"sync_direction IS NULL OR sync_direction IN ({valid_str})",
    )

    # 4. Backfill: existing strava-destined rows from komoot/import sources
    op.execute("""
        UPDATE synced_activities
        SET destination_platform    = 'strava',
            destination_activity_id = strava_activity_id
        WHERE strava_activity_id IS NOT NULL
          AND source IN ('komoot', 'import')
    """)

    # 5. New composite unique: one row per (user, komoot_tour, destination)
    #    NULL komoot_tour_id is allowed (Strava-native activities).
    op.create_unique_constraint(
        "uq_synced_activities_user_komoot_dest",
        "synced_activities",
        ["user_id", "komoot_tour_id", "destination_platform"],
    )

    # 6. Index on destination_platform for pipeline queries
    op.create_index(
        "ix_synced_activities_dest_platform",
        "synced_activities",
        ["destination_platform"],
    )


def downgrade() -> None:
    op.drop_index("ix_synced_activities_dest_platform", "synced_activities")
    op.drop_constraint(
        "uq_synced_activities_user_komoot_dest",
        "synced_activities",
        type_="unique",
    )
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
    op.drop_column("synced_activities", "destination_activity_id")
    op.drop_column("synced_activities", "destination_platform")
    op.create_unique_constraint(
        "uq_synced_activities_user_komoot",
        "synced_activities",
        ["user_id", "komoot_tour_id"],
    )
