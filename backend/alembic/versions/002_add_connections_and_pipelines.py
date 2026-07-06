from __future__ import annotations

"""Add connections and pipelines tables; add nullable pipeline_id FK to sync tables.

Revision ID: 002
Revises: 001
Create Date: 2026-04-19 00:00:00.000000

Additive-only migration — no existing columns are dropped or altered.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False, server_default=""),
        sa.Column("credentials_enc", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "platform IN ("
            "'komoot','strava','garmin','polar','wahoo',"
            "'intervals_icu','runalyze','trainingpeaks','webhook'"
            ")",
            name="ck_connections_platform",
        ),
        sa.CheckConstraint(
            "status IN ('active','error','disconnected')",
            name="ck_connections_status",
        ),
    )
    op.create_index("ix_connections_user_id", "connections", ["user_id"])
    op.create_index("ix_connections_user_platform", "connections", ["user_id", "platform"])

    op.create_table(
        "pipelines",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_connection_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dest_connection_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_pipelines_user_id", "pipelines", ["user_id"])

    # Add nullable pipeline_id FK to sync_rules and synced_activities
    op.add_column(
        "sync_rules",
        sa.Column(
            "pipeline_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("pipelines.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_sync_rules_pipeline_id", "sync_rules", ["pipeline_id"])

    op.add_column(
        "synced_activities",
        sa.Column(
            "pipeline_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("pipelines.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_synced_activities_pipeline_id", "synced_activities", ["pipeline_id"])


def downgrade() -> None:
    op.drop_index("ix_synced_activities_pipeline_id", table_name="synced_activities")
    op.drop_column("synced_activities", "pipeline_id")

    op.drop_index("ix_sync_rules_pipeline_id", table_name="sync_rules")
    op.drop_column("sync_rules", "pipeline_id")

    op.drop_index("ix_pipelines_user_id", table_name="pipelines")
    op.drop_table("pipelines")

    op.drop_index("ix_connections_user_platform", table_name="connections")
    op.drop_index("ix_connections_user_id", table_name="connections")
    op.drop_table("connections")
