"""merge job embedding and ingestion migrations

Revision ID: 0006_merge_job_heads
Revises: 0005_job_embedding, 0005_job_ingestion_identity
Create Date: 2026-07-30

"""

from collections.abc import Sequence

revision: str = "0006_merge_job_heads"
down_revision: tuple[str, str] = (
    "0005_job_embedding",
    "0005_job_ingestion_identity",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
