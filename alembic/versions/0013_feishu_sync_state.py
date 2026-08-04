"""add Feishu record-level sync state

Revision ID: 0013_feishu_sync_state
Revises: 0012_recommendation_closure
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_feishu_sync_state"
down_revision: str | None = "0012_recommendation_closure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feishu_sync_state",
        sa.Column("app_token", sa.String(length=100), nullable=False),
        sa.Column("table_id", sa.String(length=50), nullable=False),
        sa.Column("record_id", sa.String(length=100), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("last_modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "app_token",
            "table_id",
            "record_id",
            name="pk_feishu_sync_state",
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'SKIPPED', 'FAILED')",
            name="ck_feishu_sync_state_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("feishu_sync_state")
