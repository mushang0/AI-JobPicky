"""create user authentication and credit tables

Revision ID: 0008_auth_and_credits
Revises: 0007_job_metadata
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_auth_and_credits"
down_revision: str | None = "0007_job_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("email = lower(btrim(email))", name="ck_user_account_email_normalized"),
        sa.CheckConstraint("role IN ('USER', 'ADMIN')", name="ck_user_account_role"),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_user_account_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_user_account_email"),
    )
    op.create_table(
        "refresh_session",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_family_id", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_to_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rotated_to_id"],
            ["refresh_session.id"],
            name="fk_refresh_session_rotated_to",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_refresh_session_token_hash"),
    )
    op.create_index(
        "ix_refresh_session_family",
        "refresh_session",
        ["token_family_id"],
    )
    op.create_index(
        "ix_refresh_session_user_expires",
        "refresh_session",
        ["user_id", "expires_at"],
    )
    op.create_table(
        "credit_account",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("balance >= 0", name="ck_credit_account_balance_non_negative"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=True),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount <> 0", name="ck_credit_ledger_amount_non_zero"),
        sa.CheckConstraint("balance_after >= 0", name="ck_credit_ledger_balance_non_negative"),
        sa.CheckConstraint(
            "entry_type IN ('SIGNUP_BONUS', 'RECOMMENDATION_DEBIT', 'RECOMMENDATION_REFUND')",
            name="ck_credit_ledger_entry_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_credit_ledger_user_created",
        "credit_ledger",
        ["user_id", "created_at"],
    )
    op.create_index(
        "uq_credit_ledger_signup_bonus",
        "credit_ledger",
        ["user_id", "entry_type"],
        unique=True,
        postgresql_where=sa.text("entry_type = 'SIGNUP_BONUS'"),
    )
    op.create_index(
        "uq_credit_ledger_reference_entry",
        "credit_ledger",
        ["user_id", "reference_id", "entry_type"],
        unique=True,
        postgresql_where=sa.text("reference_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("credit_ledger")
    op.drop_table("credit_account")
    op.drop_table("refresh_session")
    op.drop_table("user_account")
