"""allow 'lifetime' in subscriptions.tier check constraint

The Stripe webhook (checkout.session.completed, mode=payment) has always set
sub.tier = "lifetime" for one-time Lifetime purchases, but the CHECK constraint
only allowed ('free', 'pro', 'business') — a completed Lifetime purchase would
have raised an IntegrityError. Widen the constraint to match actual usage.

Revision ID: 015
Revises: 014
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "015"
down_revision: Union[str, Sequence[str], None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_subscriptions_tier", "subscriptions", type_="check")
    op.create_check_constraint(
        "ck_subscriptions_tier",
        "subscriptions",
        "tier IN ('free', 'pro', 'business', 'lifetime')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_subscriptions_tier", "subscriptions", type_="check")
    op.create_check_constraint(
        "ck_subscriptions_tier",
        "subscriptions",
        "tier IN ('free', 'pro', 'business')",
    )
