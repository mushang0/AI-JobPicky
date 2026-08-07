"""group jobs by canonical company identity instead of source record

Revision ID: 0015_canonical_company_group
Revises: 0014_job_pool_query_fields
Create Date: 2026-08-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_canonical_company_group"
down_revision: str | None = "0014_job_pool_query_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        UPDATE job
        SET company_group_key = CASE
            WHEN nullif(btrim(metadata ->> 'company_group'), '') IS NOT NULL
                THEN 'company:' || lower(regexp_replace(
                    btrim(metadata ->> 'company_group'), E'\\s+', '', 'g'
                ))
            WHEN nullif(btrim(company_name), '') IS NOT NULL
                THEN 'name:' || lower(regexp_replace(btrim(company_name), E'\\s+', '', 'g'))
            ELSE 'name:unknown'
        END
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        UPDATE job
        SET company_group_key = CASE
            WHEN nullif(btrim(metadata ->> 'feishu_record_id'), '') IS NOT NULL
                THEN 'feishu:' || btrim(metadata ->> 'feishu_record_id')
            WHEN nullif(btrim(metadata ->> 'table_row_number'), '') IS NOT NULL
                THEN 'row:' || source_id || ':' || btrim(metadata ->> 'table_row_number')
            ELSE 'job:' || id
        END
        """
    )
