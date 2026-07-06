"""Add name column to users table.

Revision ID: 004
Revises: 003
Create Date: 2026-04-25 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "name")
