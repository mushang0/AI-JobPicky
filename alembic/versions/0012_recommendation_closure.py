"""add charged recommendation runs and formal recommendation records

Revision ID: 0012_recommendation_closure
Revises: 0011_profile_application
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_recommendation_closure"
down_revision: str | None = "0011_profile_application"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recommendation_run",
        sa.Column(
            "progress_percent",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "recommendation_run",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "recommendation_run",
        sa.Column("credit_cost", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "recommendation_run",
        sa.Column(
            "credit_refunded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "recommendation_run",
        sa.Column(
            "balance_after_charge",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )

    # Normalize legacy run states before adding the user-facing four-state invariant.
    op.execute(
        sa.text(
            """
            UPDATE recommendation_run
            SET status = 'FAILED',
                finished_at = COALESCE(finished_at, created_at),
                error = COALESCE(
                    error,
                    '{"code":"RECOMMENDATION_FAILED",'
                    '"message":"推荐任务处理失败，已退回本次消耗的积分。",'
                    '"details":{"reason":"legacy_state"}}'::jsonb
                )
            WHERE status NOT IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE recommendation_run
            SET current_step = CASE
                    WHEN status = 'PENDING' THEN 'PENDING'
                    WHEN status = 'SUCCEEDED' THEN 'COMPLETE'
                    ELSE COALESCE(current_step, 'PENDING')
                END,
                progress_percent = CASE
                    WHEN status = 'SUCCEEDED' THEN 100
                    WHEN current_step = 'PROFILE' THEN 10
                    WHEN current_step = 'FILTER' THEN 25
                    WHEN current_step = 'RETRIEVE' THEN 45
                    WHEN current_step = 'EVALUATE' THEN 50
                    WHEN current_step = 'SAVE' THEN 95
                    ELSE 0
                END,
                request_fingerprint = 'legacy:' || md5(recommendation_input::text)
            """
        )
    )
    # A legacy database could contain several in-flight runs. Keep the newest active
    # and close older ones before enforcing the per-user invariant.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT run_id,
                       row_number() OVER (
                           PARTITION BY user_id
                           ORDER BY created_at DESC, run_id ASC
                       ) AS position
                FROM recommendation_run
                WHERE status IN ('PENDING', 'RUNNING')
            )
            UPDATE recommendation_run AS run
            SET status = 'FAILED',
                finished_at = COALESCE(run.finished_at, run.created_at),
                error = COALESCE(
                    run.error,
                    '{"code":"RECOMMENDATION_FAILED",'
                    '"message":"推荐任务处理失败，已退回本次消耗的积分。",'
                    '"details":{"reason":"legacy_active_run"}}'::jsonb
                )
            FROM ranked
            WHERE run.run_id = ranked.run_id AND ranked.position > 1
            """
        )
    )
    op.alter_column("recommendation_run", "current_step", nullable=False)
    op.alter_column("recommendation_run", "request_fingerprint", nullable=False)
    for column_name in (
        "progress_percent",
        "credit_cost",
        "credit_refunded",
        "balance_after_charge",
    ):
        op.alter_column("recommendation_run", column_name, server_default=None)

    op.create_check_constraint(
        "ck_recommendation_run_status",
        "recommendation_run",
        "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
    )
    op.create_check_constraint(
        "ck_recommendation_run_step",
        "recommendation_run",
        "current_step IN "
        "('PENDING', 'PROFILE', 'FILTER', 'RETRIEVE', 'EVALUATE', 'SAVE', 'COMPLETE')",
    )
    op.create_check_constraint(
        "ck_recommendation_run_progress",
        "recommendation_run",
        "progress_percent BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "ck_recommendation_run_complete_progress",
        "recommendation_run",
        "(status = 'SUCCEEDED' AND current_step = 'COMPLETE' AND progress_percent = 100) "
        "OR (status <> 'SUCCEEDED' AND progress_percent < 100)",
    )
    op.create_check_constraint(
        "ck_recommendation_run_credit_values",
        "recommendation_run",
        "credit_cost >= 0 AND balance_after_charge >= 0",
    )
    op.create_check_constraint(
        "ck_recommendation_run_refund_state",
        "recommendation_run",
        "NOT credit_refunded OR (status = 'FAILED' AND credit_cost > 0)",
    )
    op.create_index(
        "uq_recommendation_run_user_active",
        "recommendation_run",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
    )

    op.create_table(
        "recommendation",
        sa.Column("recommendation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("job_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("assessment", postgresql.JSONB(), nullable=False),
        sa.Column("recommended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feedback", sa.String(length=16), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("position >= 1", name="ck_recommendation_position_positive"),
        sa.CheckConstraint(
            "feedback IS NULL OR feedback IN ('LIKE', 'DISLIKE')",
            name="ck_recommendation_feedback",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_recommendation_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["recommendation_run.run_id"],
            name="fk_recommendation_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name="fk_recommendation_job",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("recommendation_id"),
        sa.UniqueConstraint("user_id", "job_id", name="uq_recommendation_user_job"),
        sa.UniqueConstraint("run_id", "job_id", name="uq_recommendation_run_job"),
    )

    # Preserve valid legacy formal results once, choosing the earliest occurrence
    # when old runs recommended the same job more than once.
    op.execute(
        sa.text(
            """
            WITH expanded AS (
                SELECT run.user_id,
                       run.run_id,
                       item.ordinality::integer AS position,
                       item.value->'job' AS job_snapshot,
                       item.value->'assessment' AS assessment,
                       item.value->'job'->>'id' AS job_id,
                       COALESCE(run.finished_at, run.created_at) AS recommended_at
                FROM recommendation_run AS run
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(run.results, '[]'::jsonb)
                ) WITH ORDINALITY AS item(value, ordinality)
                JOIN user_account AS account ON account.id = run.user_id
                JOIN job ON job.id = item.value->'job'->>'id'
                WHERE jsonb_typeof(item.value) = 'object'
                  AND jsonb_typeof(item.value->'job') = 'object'
                  AND jsonb_typeof(item.value->'assessment') = 'object'
                  AND item.value->'assessment'->>'matched' = 'true'
            ), deduplicated AS (
                SELECT expanded.*,
                       row_number() OVER (
                           PARTITION BY user_id, job_id
                           ORDER BY recommended_at ASC, run_id ASC, position ASC
                       ) AS occurrence
                FROM expanded
                WHERE job_id IS NOT NULL
            )
            INSERT INTO recommendation (
                recommendation_id,
                user_id,
                run_id,
                job_id,
                position,
                job_snapshot,
                assessment,
                recommended_at,
                feedback,
                deleted_at
            )
            SELECT 'legacy-' || md5(run_id || ':' || position::text || ':' || job_id),
                   user_id,
                   run_id,
                   job_id,
                   position,
                   job_snapshot,
                   assessment,
                   recommended_at,
                   NULL,
                   NULL
            FROM deduplicated
            WHERE occurrence = 1
            """
        )
    )
    op.create_index(
        "ix_recommendation_user_recent",
        "recommendation",
        ["user_id", sa.text("recommended_at DESC"), "recommendation_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_recommendation_run_position",
        "recommendation",
        ["run_id", "position", "recommendation_id"],
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX ix_recommendation_user_match_score
            ON recommendation (
                user_id,
                ((assessment->>'match_score')::integer) DESC,
                recommendation_id
            )
            WHERE deleted_at IS NULL
            """
        )
    )
    op.drop_column("recommendation_run", "results")


def downgrade() -> None:
    op.add_column(
        "recommendation_run",
        sa.Column(
            "results",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("recommendation_run", "results", server_default=None)
    op.drop_index("ix_recommendation_user_match_score", table_name="recommendation")
    op.drop_index("ix_recommendation_run_position", table_name="recommendation")
    op.drop_index("ix_recommendation_user_recent", table_name="recommendation")
    op.drop_table("recommendation")
    op.drop_index("uq_recommendation_run_user_active", table_name="recommendation_run")
    op.drop_constraint(
        "ck_recommendation_run_refund_state",
        "recommendation_run",
        type_="check",
    )
    op.drop_constraint(
        "ck_recommendation_run_credit_values",
        "recommendation_run",
        type_="check",
    )
    op.drop_constraint(
        "ck_recommendation_run_complete_progress",
        "recommendation_run",
        type_="check",
    )
    op.drop_constraint(
        "ck_recommendation_run_progress",
        "recommendation_run",
        type_="check",
    )
    op.drop_constraint(
        "ck_recommendation_run_step",
        "recommendation_run",
        type_="check",
    )
    op.drop_constraint(
        "ck_recommendation_run_status",
        "recommendation_run",
        type_="check",
    )
    op.alter_column("recommendation_run", "current_step", nullable=True)
    op.drop_column("recommendation_run", "balance_after_charge")
    op.drop_column("recommendation_run", "credit_refunded")
    op.drop_column("recommendation_run", "credit_cost")
    op.drop_column("recommendation_run", "request_fingerprint")
    op.drop_column("recommendation_run", "progress_percent")
