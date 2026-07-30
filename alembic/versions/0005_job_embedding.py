"""add the local BGE job embedding column and cosine index

The migration only changes the schema.  Model loading and backfill are
explicit application operations so a database upgrade never performs network,
hardware, or business-data work.

Revision ID: 0005_job_embedding
Revises: 0004_profile_and_run
Create Date: 2026-07-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0005_job_embedding"
down_revision: str | None = "0004_profile_and_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_job_embedding_hnsw_cosine"


def upgrade() -> None:
    op.add_column("job", sa.Column("embedding", Vector(512), nullable=True))
    op.execute(
        sa.text(
            "CREATE INDEX " + _INDEX_NAME + " ON job USING hnsw (embedding vector_cosine_ops) "
            "WHERE embedding IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="job")
    op.drop_column("job", "embedding")
