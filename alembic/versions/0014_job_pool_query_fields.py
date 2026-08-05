"""add searchable batch and company grouping facts to the job pool

Revision ID: 0014_job_pool_query_fields
Revises: 0013_feishu_sync_state
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_job_pool_query_fields"
down_revision: str | None = "0013_feishu_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job",
        sa.Column(
            "batch_tokens",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar[]"),
        ),
    )
    op.add_column("job", sa.Column("company_group_key", sa.String(), nullable=True))
    op.execute(
        r"""
        WITH batch_parts AS (
            SELECT
                job.id,
                ARRAY(
                    SELECT part
                    FROM (
                        SELECT btrim(piece) AS part, min(ordinality) AS first_position
                        FROM regexp_split_to_table(
                            coalesce(job.metadata ->> 'batch', ''),
                            E'[,，、;/；|\n\r]+'
                        ) WITH ORDINALITY AS pieces(piece, ordinality)
                        WHERE btrim(piece) <> ''
                        GROUP BY btrim(piece)
                    ) AS values_by_position
                    ORDER BY first_position
                )::varchar[] AS tokens
            FROM job
        )
        UPDATE job
        SET
            batch_tokens = coalesce(batch_parts.tokens, ARRAY[]::varchar[]),
            company_group_key = CASE
                WHEN nullif(btrim(job.metadata ->> 'feishu_record_id'), '') IS NOT NULL
                    THEN 'feishu:' || btrim(job.metadata ->> 'feishu_record_id')
                WHEN nullif(btrim(job.metadata ->> 'table_row_number'), '') IS NOT NULL
                    THEN 'row:' || job.source_id || ':'
                        || btrim(job.metadata ->> 'table_row_number')
                ELSE 'job:' || job.id
            END
        FROM batch_parts
        WHERE job.id = batch_parts.id
        """
    )
    op.alter_column("job", "batch_tokens", server_default=None)
    op.alter_column("job", "company_group_key", nullable=False)

    op.drop_index("ix_job_visible_pool_order", table_name="job")
    op.execute(
        "CREATE INDEX ix_job_visible_published_order ON job "
        "(status, published_at DESC NULLS LAST, last_confirmed_at DESC, id ASC)"
    )
    op.create_index("ix_job_company_group_key", "job", ["company_group_key"])
    op.execute("CREATE INDEX ix_job_batch_tokens_gin ON job USING gin (batch_tokens)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_job_batch_tokens_gin")
    op.drop_index("ix_job_company_group_key", table_name="job")
    op.execute("DROP INDEX IF EXISTS ix_job_visible_published_order")
    op.execute(
        "CREATE INDEX ix_job_visible_pool_order ON job (status, last_confirmed_at DESC, id ASC)"
    )
    op.drop_column("job", "company_group_key")
    op.drop_column("job", "batch_tokens")
