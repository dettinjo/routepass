"""Extend synced_activities.source and generalize sync_rules.direction constraint

Revision ID: 010
Revises: 009
Create Date: 2026-05-02

F5: extend source IN (...) to include garmin, polar, wahoo, intervals_icu, runalyze
F2: replace hard-coded direction values with a regex pattern
"""

from __future__ import annotations

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # F5 — allow new platform sources
    op.drop_constraint("ck_synced_activities_source", "synced_activities", type_="check")
    op.create_check_constraint(
        "ck_synced_activities_source",
        "synced_activities",
        "source IN ("
        "'komoot', 'strava', 'garmin', 'polar', 'wahoo', 'intervals_icu', 'runalyze', 'import'"
        ")",
    )

    # F2 — generalise sync_rule direction: must be "both" or match <word>_to_<word>
    op.drop_constraint("ck_sync_rules_direction", "sync_rules", type_="check")
    op.create_check_constraint(
        "ck_sync_rules_direction",
        "sync_rules",
        "direction = 'both' OR direction ~ '^[a-z_]+_to_[a-z_]+$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sync_rules_direction", "sync_rules", type_="check")
    op.create_check_constraint(
        "ck_sync_rules_direction",
        "sync_rules",
        "direction IN ('komoot_to_strava', 'strava_to_komoot', 'both')",
    )

    op.drop_constraint("ck_synced_activities_source", "synced_activities", type_="check")
    op.create_check_constraint(
        "ck_synced_activities_source",
        "synced_activities",
        "source IN ('komoot', 'strava', 'import')",
    )
