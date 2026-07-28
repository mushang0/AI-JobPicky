"""enable pgvector and create job table

The job table mirrors the JobFact contract one-to-one. The embedding
column is deliberately deferred: its dimension depends on the embedding
vendor choice (architecture section 7.3), so it arrives with the
semantic-retrieval slice as a separate migration.

Revision ID: 0001_job_table
Revises:
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_job_table"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "job",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("locations", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("detail_url", sa.String(), nullable=True),
        sa.Column("apply_url", sa.String(), nullable=True),
        sa.Column("recruitment_type", sa.String(), nullable=True),
        sa.Column("education_requirement", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fact_version", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("job")
