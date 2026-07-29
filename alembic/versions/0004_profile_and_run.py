"""create profile and recommendation_run tables

profile mirrors the immutable ProfileSnapshot contract: (id, version) is the
identity, list fields are ARRAYs, snapshots are never updated in place.

recommendation_run persists one recommendation run: frozen input
(recommendation_input JSONB), lifecycle timestamps, counts/warnings, a
sanitized error, and the results snapshot (full JobFact + fusion score at
completion time, R7 — later job changes never rewrite history). Idempotency
is per-user: a partial unique index on (user_id, idempotency_key) so NULL
keys never collide and different users' keys stay isolated (R8).

Revision ID: 0004_profile_and_run
Revises: 0003_job_company_nature
Create Date: 2026-07-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_profile_and_run"
down_revision: str | None = "0003_job_company_nature"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_locations", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("target_roles", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("skills", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("excluded_roles", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("education", sa.String(), nullable=True),
        sa.Column("graduation_year", sa.Integer(), nullable=True),
        sa.Column("expected_salary_min", sa.Integer(), nullable=True),
        sa.Column("experience_summary", sa.Text(), nullable=True),
        sa.Column("extra_request", sa.Text(), nullable=True),
        sa.Column("warnings", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "version"),
    )
    op.create_table(
        "recommendation_run",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_step", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counts", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("recommendation_input", postgresql.JSONB(), nullable=False),
        sa.Column("model_config_version", sa.String(), nullable=False),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "uq_recommendation_run_user_idempotency",
        "recommendation_run",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("recommendation_run")
    op.drop_table("profile")
