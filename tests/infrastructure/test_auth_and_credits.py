from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from jobpicky.auth import AccessTokenCodec, AuthService
from jobpicky.config import Settings
from jobpicky.contracts import ErrorCode, RegisterRequest
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.auth_store import (
    REFRESH_SESSION_TABLE,
    USER_ACCOUNT_TABLE,
    PostgresAuthStore,
)
from jobpicky.infrastructure.credit_store import (
    CREDIT_ACCOUNT_TABLE,
    CREDIT_LEDGER_TABLE,
    PostgresCreditStore,
)
from jobpicky.infrastructure.database import create_engine, create_session_factory

_TEST_DATABASE_URL = os.environ.get("JOBPICKY_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="JOBPICKY_TEST_DATABASE_URL is not set; start the compose db and run migrations",
)

_KEY = "integration-signing-key-that-is-longer-than-32-bytes"
_PASSWORD = "int-pass"


def test_registration_rotation_reuse_and_credit_ledger_roundtrip() -> None:
    async def check() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        settings = Settings(
            environment="test",
            jwt_signing_key=_KEY,
            refresh_cookie_secure=False,
        )
        auth = AuthService(
            PostgresAuthStore(factory),
            settings,
            AccessTokenCodec(_KEY, settings),
        )
        credits = PostgresCreditStore(factory)
        email = f"itest-{uuid4()}@example.com"

        try:
            registered = await auth.register(RegisterRequest(email=email, password=_PASSWORD))
            user_id = registered.response.user.id
            async with factory() as session:
                user = (
                    (
                        await session.execute(
                            sa.select(USER_ACCOUNT_TABLE).where(USER_ACCOUNT_TABLE.c.id == user_id)
                        )
                    )
                    .mappings()
                    .one()
                )
                session_rows = (
                    (
                        await session.execute(
                            sa.select(REFRESH_SESSION_TABLE).where(
                                REFRESH_SESSION_TABLE.c.user_id == user_id
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                ledger = (
                    (
                        await session.execute(
                            sa.select(CREDIT_LEDGER_TABLE).where(
                                CREDIT_LEDGER_TABLE.c.user_id == user_id
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
            assert user.password_hash.startswith("$argon2id$")
            assert user.password_hash != _PASSWORD
            assert all(row.refresh_token_hash != registered.refresh_token for row in session_rows)
            assert [(row.entry_type, row.amount) for row in ledger] == [("SIGNUP_BONUS", 10_000)]
            assert await credits.get_balance(user_id) == 10_000

            refreshed = await auth.refresh(registered.refresh_token)
            with pytest.raises(ApplicationError) as reuse:
                await auth.refresh(registered.refresh_token)
            assert reuse.value.code == str(ErrorCode.SESSION_EXPIRED)
            with pytest.raises(ApplicationError):
                await auth.refresh(refreshed.refresh_token)

            debit = await credits.charge_recommendation(user_id, "run-itest", 100)
            repeated_debit = await credits.charge_recommendation(user_id, "run-itest", 100)
            assert debit == repeated_debit
            assert await credits.get_balance(user_id) == 9_900
            refund = await credits.refund_recommendation(user_id, "run-itest", 100)
            repeated_refund = await credits.refund_recommendation(user_id, "run-itest", 100)
            assert refund == repeated_refund
            assert await credits.get_balance(user_id) == 10_000

            with pytest.raises(ApplicationError) as duplicate:
                await auth.register(RegisterRequest(email=email.upper(), password=_PASSWORD))
            assert duplicate.value.code == str(ErrorCode.EMAIL_ALREADY_REGISTERED)
            async with factory() as session:
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(CREDIT_ACCOUNT_TABLE)
                        .where(CREDIT_ACCOUNT_TABLE.c.user_id == user_id)
                    )
                    == 1
                )
        finally:
            async with factory() as session, session.begin():
                await session.execute(
                    sa.delete(USER_ACCOUNT_TABLE).where(USER_ACCOUNT_TABLE.c.email == email)
                )
            await engine.dispose()

    asyncio.run(check())
