"""Merge migration — reconciles the 003 branch with the 011 main chain.

Revision ID: 012
Revises: 003, 011
Create Date: 2026-05-04 00:00:00.000000

Background
----------
Migration 004 was originally authored with down_revision="002", creating two
Alembic branch heads:

  001 → 002 → 003 (drop legacy user columns)    ← HEAD (orphaned)
           ↘ 004 → 005 → ... → 011              ← HEAD (main)

Databases initialised via the 002→004 path never applied 003 and therefore
still carry the legacy Komoot credential columns. Migration 012 serves as the
merge point that:
  - Declares both 003 and 011 as its parents, collapsing the two heads.
  - Applies the 003 column-drop content (using IF EXISTS — idempotent whether
    003 ran or not).
  - Is therefore safe on ALL databases regardless of which branch they took.

After 012, running `alembic upgrade heads` is equivalent to `alembic upgrade
012` and leaves exactly one head.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "012"
down_revision: Union[str, Sequence[str], None] = ("003", "011")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_COLUMNS = [
    "komoot_email_encrypted",
    "komoot_password_encrypted",
    "komoot_key_version",
    "komoot_user_id",
    "komoot_connected_at",
    "komoot_poll_interval_min",
    "next_komoot_poll_at",
    "last_komoot_poll_at",
    "sync_komoot_to_strava",
    "sync_strava_to_komoot",
    "hide_from_home_default",
    "timezone",
]


def upgrade() -> None:
    # Drop legacy columns using IF EXISTS — idempotent on both branch paths.
    conn = op.get_bind()
    for col in _LEGACY_COLUMNS:
        conn.execute(sa.text(f"ALTER TABLE users DROP COLUMN IF EXISTS {col}"))


def downgrade() -> None:
    # Legacy columns are not restored — they belong to the old per-user
    # credential model superseded by the Connections table.
    pass
