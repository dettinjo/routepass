"""Add per-connection sync watermarks (connection_sync_state table)

Revision ID: 008
Revises: 007
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connection_sync_state",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String, nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_connection_sync_state_connection_id",
        "connection_sync_state",
        ["connection_id"],
    )
    op.create_index(
        "ix_connection_sync_state_user_id",
        "connection_sync_state",
        ["user_id"],
    )
    op.create_unique_constraint(
        "uq_connection_sync_state_connection",
        "connection_sync_state",
        ["connection_id"],
    )


def downgrade() -> None:
    op.drop_table("connection_sync_state")
