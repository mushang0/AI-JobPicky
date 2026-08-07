"""restore the canonical company nature for known source wording

Revision ID: 0016_restore_company_nature
Revises: 0015_canonical_company_group
Create Date: 2026-08-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_restore_company_nature"
down_revision: str | None = "0015_canonical_company_group"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_job_company_nature_normalized", "job", type_="check")
    op.create_check_constraint(
        "ck_job_company_nature_normalized",
        "job",
        "company_nature IS NULL OR company_nature IN ("
        "'央国企', '央企', '国企', '事业单位', '政府/公共机构', "
        "'民营企业', '外资企业', '合资企业', '其他')",
    )
    op.execute(
        """
        UPDATE job
        SET company_nature = '央国企'
        WHERE company_nature IS NULL
          AND metadata -> '_normalization_v1_original' ->> 'company_nature' = '央国企'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE job
        SET company_nature = NULL
        WHERE company_nature = '央国企'
          AND metadata -> '_normalization_v1_original' ->> 'company_nature' = '央国企'
        """
    )
    op.drop_constraint("ck_job_company_nature_normalized", "job", type_="check")
    op.create_check_constraint(
        "ck_job_company_nature_normalized",
        "job",
        "company_nature IS NULL OR company_nature IN ("
        "'央企', '国企', '事业单位', '政府/公共机构', "
        "'民营企业', '外资企业', '合资企业', '其他')",
    )
