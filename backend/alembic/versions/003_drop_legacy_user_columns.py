from __future__ import annotations

"""Drop legacy komoot credential columns and sync preference columns from users table.

Revision ID: 003
Revises: 002
Create Date: 2026-04-19 00:00:00.000000

Run scripts/migrate_credentials.py BEFORE applying this migration to ensure
all credential data has been copied to the connections table.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Columns being dropped — captured here so downgrade can recreate them.
_KOMOOT_COLS = [
    ("komoot_email_encrypted", sa.LargeBinary()),
    ("komoot_password_encrypted", sa.LargeBinary()),
    ("komoot_key_version", sa.Integer()),
    ("komoot_user_id", sa.String()),
    ("komoot_connected_at", sa.DateTime(timezone=True)),
    ("komoot_poll_interval_min", sa.Integer()),
    ("next_komoot_poll_at", sa.DateTime(timezone=True)),
    ("last_komoot_poll_at", sa.DateTime(timezone=True)),
]
_PREF_COLS = [
    ("sync_komoot_to_strava", sa.Boolean()),
    ("sync_strava_to_komoot", sa.Boolean()),
    ("hide_from_home_default", sa.Boolean()),
    ("timezone", sa.String()),
]


def upgrade() -> None:
    # Use IF EXISTS so this is idempotent when columns were already removed
    # by a later clean-up migration (e.g. 012 on branches that skipped 003).
    conn = op.get_bind()
    for col_name, _ in _KOMOOT_COLS + _PREF_COLS:
        conn.execute(sa.text(f"ALTER TABLE users DROP COLUMN IF EXISTS {col_name}"))


def downgrade() -> None:
    for col_name, col_type in reversed(_PREF_COLS):
        op.add_column("users", sa.Column(col_name, col_type, nullable=True))
    for col_name, col_type in reversed(_KOMOOT_COLS):
        op.add_column("users", sa.Column(col_name, col_type, nullable=True))
