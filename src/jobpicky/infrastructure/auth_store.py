from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..auth.service import (
    EmailAlreadyExistsError,
    RotationResult,
    SessionSeed,
    UserRecord,
)
from ..contracts import ErrorCode, UserRole
from ..errors import ApplicationError
from .credit_store import initialize_credits

USER_ACCOUNT_TABLE = sa.table(
    "user_account",
    sa.column("id", sa.String),
    sa.column("email", sa.String),
    sa.column("password_hash", sa.String),
    sa.column("role", sa.String),
    sa.column("status", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    sa.column("last_login_at", sa.DateTime(timezone=True)),
)

REFRESH_SESSION_TABLE = sa.table(
    "refresh_session",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("refresh_token_hash", sa.String),
    sa.column("token_family_id", sa.String),
    sa.column("expires_at", sa.DateTime(timezone=True)),
    sa.column("revoked_at", sa.DateTime(timezone=True)),
    sa.column("rotated_to_id", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("last_used_at", sa.DateTime(timezone=True)),
)

_EMAIL_CONSTRAINT = "uq_user_account_email"


def _constraint_name(exc: IntegrityError) -> str | None:
    direct = getattr(exc.orig, "constraint_name", None)
    if direct:
        return str(direct)
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)


def _row_to_user(row: sa.RowMapping) -> UserRecord:
    return UserRecord(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        role=UserRole(row.role),
        status=row.status,
        created_at=row.created_at,
    )


def _session_values(user_id: str, seed: SessionSeed, now: datetime) -> dict[str, object]:
    return {
        "id": seed.id,
        "user_id": user_id,
        "refresh_token_hash": seed.token_hash,
        "token_family_id": seed.family_id,
        "expires_at": seed.expires_at,
        "revoked_at": None,
        "rotated_to_id": None,
        "created_at": now,
        "last_used_at": None,
    }


class PostgresAuthStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_account_with_bonus(
        self,
        *,
        email: str,
        password_hash: str,
        session: SessionSeed,
        signup_bonus: int,
        now: datetime,
    ) -> UserRecord:
        user = UserRecord(
            id=str(uuid4()),
            email=email,
            password_hash=password_hash,
            role=UserRole.USER,
            status="ACTIVE",
            created_at=now,
        )
        async with self._session_factory() as database:
            try:
                async with database.begin():
                    await database.execute(
                        sa.insert(USER_ACCOUNT_TABLE).values(
                            id=user.id,
                            email=user.email,
                            password_hash=user.password_hash,
                            role=str(user.role),
                            status=user.status,
                            created_at=now,
                            updated_at=now,
                            last_login_at=now,
                        )
                    )
                    await initialize_credits(
                        database,
                        user.id,
                        signup_bonus,
                        now=now,
                    )
                    await database.execute(
                        sa.insert(REFRESH_SESSION_TABLE).values(
                            _session_values(user.id, session, now)
                        )
                    )
            except IntegrityError as exc:
                if _constraint_name(exc) == _EMAIL_CONSTRAINT:
                    raise EmailAlreadyExistsError(email) from exc
                raise
        return user

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(USER_ACCOUNT_TABLE).where(USER_ACCOUNT_TABLE.c.email == email)
            )
            row = result.mappings().one_or_none()
        return _row_to_user(row) if row is not None else None

    async def get_user(self, user_id: str) -> UserRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(USER_ACCOUNT_TABLE).where(USER_ACCOUNT_TABLE.c.id == user_id)
            )
            row = result.mappings().one_or_none()
        return _row_to_user(row) if row is not None else None

    async def create_login_session(
        self,
        user_id: str,
        session: SessionSeed,
        now: datetime,
    ) -> UserRecord:
        async with self._session_factory() as database, database.begin():
            result = await database.execute(
                sa.select(USER_ACCOUNT_TABLE)
                .where(USER_ACCOUNT_TABLE.c.id == user_id)
                .with_for_update()
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise ApplicationError(
                    ErrorCode.AUTHENTICATION_REQUIRED,
                    "account no longer exists",
                    status_code=401,
                )
            await database.execute(
                sa.insert(REFRESH_SESSION_TABLE).values(_session_values(user_id, session, now))
            )
            await database.execute(
                sa.update(USER_ACCOUNT_TABLE)
                .where(USER_ACCOUNT_TABLE.c.id == user_id)
                .values(last_login_at=now, updated_at=now)
            )
        return _row_to_user(row)

    async def find_refresh_family(self, token_hash: str) -> str | None:
        async with self._session_factory() as session:
            return await session.scalar(
                sa.select(REFRESH_SESSION_TABLE.c.token_family_id).where(
                    REFRESH_SESSION_TABLE.c.refresh_token_hash == token_hash
                )
            )

    async def rotate_refresh_session(
        self,
        old_token_hash: str,
        new_session: SessionSeed,
        now: datetime,
    ) -> RotationResult:
        async with self._session_factory() as database, database.begin():
            result = await database.execute(
                sa.select(REFRESH_SESSION_TABLE)
                .where(REFRESH_SESSION_TABLE.c.refresh_token_hash == old_token_hash)
                .with_for_update()
            )
            old = result.mappings().one_or_none()
            if old is None:
                return RotationResult("MISSING")
            if old.revoked_at is not None:
                if old.rotated_to_id is not None:
                    await self._revoke_family(database, old.token_family_id, now)
                    return RotationResult("REUSED")
                return RotationResult("REVOKED")
            if old.expires_at <= now:
                await database.execute(
                    sa.update(REFRESH_SESSION_TABLE)
                    .where(REFRESH_SESSION_TABLE.c.id == old.id)
                    .values(revoked_at=now, last_used_at=now)
                )
                return RotationResult("EXPIRED")

            user_result = await database.execute(
                sa.select(USER_ACCOUNT_TABLE).where(USER_ACCOUNT_TABLE.c.id == old.user_id)
            )
            user_row = user_result.mappings().one_or_none()
            if user_row is None:
                await self._revoke_family(database, old.token_family_id, now)
                return RotationResult("REVOKED")

            rotated = SessionSeed(
                id=new_session.id,
                token_hash=new_session.token_hash,
                family_id=old.token_family_id,
                expires_at=min(old.expires_at, new_session.expires_at),
            )
            await database.execute(
                sa.insert(REFRESH_SESSION_TABLE).values(_session_values(old.user_id, rotated, now))
            )
            await database.execute(
                sa.update(REFRESH_SESSION_TABLE)
                .where(REFRESH_SESSION_TABLE.c.id == old.id)
                .values(
                    revoked_at=now,
                    rotated_to_id=rotated.id,
                    last_used_at=now,
                )
            )
            return RotationResult("ROTATED", _row_to_user(user_row))

    async def revoke_refresh_family(self, token_hash: str, now: datetime) -> None:
        async with self._session_factory() as database, database.begin():
            family_id = await database.scalar(
                sa.select(REFRESH_SESSION_TABLE.c.token_family_id).where(
                    REFRESH_SESSION_TABLE.c.refresh_token_hash == token_hash
                )
            )
            if family_id is not None:
                await self._revoke_family(database, family_id, now)

    @staticmethod
    async def _revoke_family(
        session: AsyncSession,
        family_id: str,
        now: datetime,
    ) -> None:
        await session.execute(
            sa.update(REFRESH_SESSION_TABLE)
            .where(
                REFRESH_SESSION_TABLE.c.token_family_id == family_id,
                REFRESH_SESSION_TABLE.c.revoked_at.is_(None),
            )
            .values(revoked_at=now, last_used_at=now)
        )


__all__ = [
    "PostgresAuthStore",
    "REFRESH_SESSION_TABLE",
    "USER_ACCOUNT_TABLE",
]
