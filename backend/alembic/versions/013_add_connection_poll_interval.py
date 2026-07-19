"""add poll_interval_min to connections

Per-source-connection poll cadence. NULL means "use the platform default"
(see app.core.polling).

Revision ID: 013
Revises: 012
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "013"
down_revision: Union[str, Sequence[str], None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("poll_interval_min", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connections", "poll_interval_min")
