"""add training-profile columns (ftp, hr_max) to users

Unlocks TSS + proper power/HR zones in metric compute. See
docs/GPX_ANALYSIS_PLAN.md (open decision 3).

Revision ID: 018
Revises: 017
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "018"
down_revision: Union[str, Sequence[str], None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ftp", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("hr_max", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "hr_max")
    op.drop_column("users", "ftp")
