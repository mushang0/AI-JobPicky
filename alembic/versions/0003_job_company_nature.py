"""add company_nature column to job

Mirrors the contract change: company nature (民企/央国企/事业单位 etc.)
on CollectedJob/JobFact. Nullable — jobs without this fact must never
be penalized (R2).

Revision ID: 0003_job_company_nature
Revises: 0002_job_salary_graduation
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_job_company_nature"
down_revision: str | None = "0002_job_salary_graduation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("company_nature", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("job", "company_nature")
