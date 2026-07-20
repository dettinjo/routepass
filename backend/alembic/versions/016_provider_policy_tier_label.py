"""add tier_label and notes to provider_policy

Human-readable subscription/tier context per provider (e.g. "Standard,
self-upgraded to 10 athletes") shown alongside the raw limit numbers in the
admin dashboard's provider overview.

Revision ID: 016
Revises: 015
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "016"
down_revision: Union[str, Sequence[str], None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("provider_policy", sa.Column("tier_label", sa.String(), nullable=True))
    op.add_column("provider_policy", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("provider_policy", "notes")
    op.drop_column("provider_policy", "tier_label")
