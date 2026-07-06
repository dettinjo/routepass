"""Add user_audit_log table for compliance / security audit trail

Revision ID: 011
Revises: 010
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_audit_log",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_user_audit_log_user_id", "user_audit_log", ["user_id"])
    op.create_index("ix_user_audit_log_occurred_at", "user_audit_log", ["occurred_at"])
    op.create_index(
        "ix_user_audit_log_user_occurred",
        "user_audit_log",
        ["user_id", "occurred_at"],
    )
    op.create_index("ix_user_audit_log_action", "user_audit_log", ["action"])


def downgrade() -> None:
    op.drop_table("user_audit_log")
