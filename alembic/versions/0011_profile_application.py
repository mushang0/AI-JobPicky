"""add editable profile application fields and save idempotency

Revision ID: 0011_profile_application
Revises: 0010_normalize_job_filter_facts
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_profile_application"
down_revision: str | None = "0010_normalize_job_filter_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profile",
        sa.Column(
            "recruitment_types",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.alter_column("profile", "recruitment_types", server_default=None)
    op.create_check_constraint(
        "ck_profile_version_positive",
        "profile",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_profile_recruitment_types_normalized",
        "profile",
        "recruitment_types <@ ARRAY['校招', '社招', '实习']::varchar[]",
    )
    op.create_index(
        "uq_profile_user_version",
        "profile",
        ["user_id", "version"],
        unique=True,
    )
    op.create_table(
        "profile_save_request",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_profile_save_request_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "profile_version"],
            ["profile.id", "profile.version"],
            name="fk_profile_save_request_snapshot",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "idempotency_key",
            name="pk_profile_save_request",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128",
            name="ck_profile_save_request_key_length",
        ),
    )


def downgrade() -> None:
    op.drop_table("profile_save_request")
    op.drop_index("uq_profile_user_version", table_name="profile")
    op.drop_constraint(
        "ck_profile_recruitment_types_normalized",
        "profile",
        type_="check",
    )
    op.drop_constraint("ck_profile_version_positive", "profile", type_="check")
    op.drop_column("profile", "recruitment_types")
