"""add internal job ingestion identity

Revision ID: 0005_job_ingestion_identity
Revises: 0004_profile_and_run
Create Date: 2026-07-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_job_ingestion_identity"
down_revision: str | None = "0004_profile_and_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("identity_key", sa.String(), nullable=True))
    op.add_column("job", sa.Column("source_job_id", sa.String(), nullable=True))
    op.add_column("job", sa.Column("content_hash", sa.String(), nullable=True))
    op.add_column("job", sa.Column("last_seen_run_id", sa.String(), nullable=True))
    op.create_index("uq_job_identity_key", "job", ["identity_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_job_identity_key", table_name="job")
    op.drop_column("job", "last_seen_run_id")
    op.drop_column("job", "content_hash")
    op.drop_column("job", "source_job_id")
    op.drop_column("job", "identity_key")
