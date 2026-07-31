"""add source directory, job-pool indexes, and saved jobs

Revision ID: 0009_job_pool_and_saved_jobs
Revises: 0008_auth_and_credits
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_job_pool_and_saved_jobs"
down_revision: str | None = "0008_auth_and_credits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_source",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "btrim(display_name) <> ''",
            name="ck_job_source_display_name_not_empty",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Existing source IDs predate the source directory. Prefer a single
    # confirmed platform name, then a single company name, and finally the
    # opaque source ID. No missing display fact is guessed.
    op.execute(
        """
        WITH source_facts AS (
            SELECT
                source_id,
                array_remove(
                    array_agg(
                        DISTINCT CASE
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) = 'MOKA'
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE '%mokahr.com%'
                                THEN 'Moka'
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) IN ('FEISHU', 'FEISHU_RECRUITMENT')
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE '%jobs.feishu.cn%'
                                THEN '飞书招聘'
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) = 'BEISEN'
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE ANY (ARRAY['%beisen.com%', '%zhiye.com%'])
                                THEN '北森'
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) = 'HOTJOB'
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE '%hotjob.cn%'
                                THEN 'HotJob'
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) = 'ZHAOPIN'
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE '%zhaopin.com%'
                                THEN '智联招聘'
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) = 'JOB_51'
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE '%51job.com%'
                                THEN '前程无忧'
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) = 'GUOPIN'
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE '%iguopin.com%'
                                THEN '国聘'
                            WHEN upper(coalesce(
                                metadata ->> 'platform',
                                metadata ->> 'fallback_link_type',
                                ''
                            )) = 'WECHAT'
                                OR lower(coalesce(detail_url, '') || ' ' || coalesce(apply_url, ''))
                                    LIKE '%weixin.qq.com%'
                                THEN '微信公众号'
                            WHEN upper(coalesce(metadata ->> 'platform', '')) = 'PUBLIC_WEB'
                                THEN '公开网页'
                            ELSE NULL
                        END
                    ),
                    NULL
                ) AS known_names,
                count(DISTINCT nullif(btrim(company_name), '')) AS company_count,
                min(nullif(btrim(company_name), '')) AS company_name,
                min(first_seen_at) AS created_at,
                max(updated_at) AS updated_at
            FROM job
            GROUP BY source_id
        )
        INSERT INTO job_source (id, display_name, created_at, updated_at)
        SELECT
            source_id,
            CASE
                WHEN cardinality(known_names) = 1 THEN known_names[1]
                WHEN company_count = 1 THEN company_name
                ELSE source_id
            END,
            coalesce(created_at, CURRENT_TIMESTAMP),
            coalesce(updated_at, CURRENT_TIMESTAMP)
        FROM source_facts
        """
    )

    op.create_foreign_key(
        "fk_job_job_source",
        "job",
        "job_source",
        ["source_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_job_source_id", "job", ["source_id"])
    op.execute(
        "CREATE INDEX ix_job_visible_pool_order ON job (status, last_confirmed_at DESC, id ASC)"
    )

    op.create_table(
        "saved_job",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_saved_job_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name="fk_saved_job_job",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", "job_id", name="pk_saved_job"),
    )
    op.execute(
        "CREATE INDEX ix_saved_job_user_saved_at ON saved_job (user_id, saved_at DESC, job_id ASC)"
    )


def downgrade() -> None:
    op.drop_index("ix_saved_job_user_saved_at", table_name="saved_job")
    op.drop_table("saved_job")
    op.drop_index("ix_job_visible_pool_order", table_name="job")
    op.drop_index("ix_job_source_id", table_name="job")
    op.drop_constraint("fk_job_job_source", "job", type_="foreignkey")
    op.drop_table("job_source")
