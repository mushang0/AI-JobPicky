"""add salary and graduation year columns to job

Mirrors the contract change: salary range plus graduation-year
restriction on JobFact/CollectedJob. All columns are nullable (or
default-empty) because jobs without these facts must never be excluded
by hard filters (R2).

Revision ID: 0002_job_salary_graduation
Revises: 0001_job_table
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_job_salary_graduation"
down_revision: str | None = "0001_job_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("salary_min", sa.Integer(), nullable=True))
    op.add_column("job", sa.Column("salary_max", sa.Integer(), nullable=True))
    op.add_column("job", sa.Column("salary_months", sa.Integer(), nullable=True))
    op.add_column(
        "job",
        sa.Column(
            "graduation_years",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_check_constraint(
        "ck_job_salary_range",
        "job",
        "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_salary_range", "job", type_="check")
    op.drop_column("job", "graduation_years")
    op.drop_column("job", "salary_months")
    op.drop_column("job", "salary_max")
    op.drop_column("job", "salary_min")
