from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import ErrorCode, ProfileSnapshot
from ..errors import ApplicationError
from ..profiles.service import (
    ProfileIdempotencyConflictError,
    ProfileSaveCommand,
    plan_profile_save,
)

# Lightweight Core mapping of the profile table; Alembic migrations remain the
# single source of truth for the schema (same pattern as job_catalog.py).
PROFILE_TABLE = sa.table(
    "profile",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("version", sa.Integer),
    sa.column("target_locations", postgresql.ARRAY(sa.String)),
    sa.column("target_roles", postgresql.ARRAY(sa.String)),
    sa.column("recruitment_types", postgresql.ARRAY(sa.String)),
    sa.column("skills", postgresql.ARRAY(sa.String)),
    sa.column("excluded_roles", postgresql.ARRAY(sa.String)),
    sa.column("education", sa.String),
    sa.column("graduation_year", sa.Integer),
    sa.column("expected_salary_min", sa.Integer),
    sa.column("experience_summary", sa.Text),
    sa.column("extra_request", sa.Text),
    sa.column("warnings", postgresql.ARRAY(sa.String)),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

PROFILE_SAVE_REQUEST_TABLE = sa.table(
    "profile_save_request",
    sa.column("user_id", sa.String),
    sa.column("idempotency_key", sa.String),
    sa.column("request_hash", sa.String),
    sa.column("profile_id", sa.String),
    sa.column("profile_version", sa.Integer),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def row_to_profile_snapshot(row: sa.RowMapping) -> ProfileSnapshot:
    return ProfileSnapshot(
        id=row.id,
        user_id=row.user_id,
        version=row.version,
        target_locations=list(row.target_locations),
        target_roles=list(row.target_roles),
        recruitment_types=list(row.get("recruitment_types") or []),
        skills=list(row.skills),
        excluded_roles=list(row.excluded_roles),
        education=row.education,
        graduation_year=row.graduation_year,
        expected_salary_min=row.expected_salary_min,
        experience_summary=row.experience_summary,
        extra_request=row.extra_request,
        warnings=list(row.warnings),
        created_at=row.created_at,
    )


class PostgresProfileStore:
    """PostgreSQL profile reader and atomic versioned-write adapter."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_snapshot(self, user_id: str, profile_id: str) -> ProfileSnapshot:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(PROFILE_TABLE)
                .where(
                    PROFILE_TABLE.c.id == profile_id,
                    PROFILE_TABLE.c.user_id == user_id,
                )
                .order_by(PROFILE_TABLE.c.version.desc())
                .limit(1)
            )
            row = result.mappings().first()
        if row is None:
            raise ApplicationError(
                ErrorCode.NOT_FOUND,
                f"profile {profile_id} not found for user {user_id}",
                status_code=404,
            )
        return row_to_profile_snapshot(row)

    async def get_version(
        self,
        user_id: str,
        profile_id: str,
        version: int,
    ) -> ProfileSnapshot:
        async with self._session_factory() as session:
            snapshot = await _get_version(session, user_id, profile_id, version)
        if snapshot is None:
            raise ApplicationError(
                ErrorCode.NOT_FOUND,
                "profile version not found",
                status_code=404,
            )
        return snapshot

    async def find_current(self, user_id: str) -> ProfileSnapshot | None:
        async with self._session_factory() as session:
            return await _find_current(session, user_id)

    async def get_current(self, user_id: str) -> ProfileSnapshot:
        snapshot = await self.find_current(user_id)
        if snapshot is None:
            raise ApplicationError(
                ErrorCode.PROFILE_NOT_FOUND,
                "profile not found",
                status_code=404,
            )
        return snapshot

    async def save_current(self, command: ProfileSaveCommand) -> ProfileSnapshot:
        async with self._session_factory() as database, database.begin():
            # A transaction-scoped per-user lock also serializes the first save,
            # where no profile row exists yet for SELECT ... FOR UPDATE.
            await database.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:user_id, :namespace_seed))"
                ),
                {"user_id": command.user_id, "namespace_seed": 0x50524F46494C45},
            )
            replay_result = await database.execute(
                sa.select(PROFILE_SAVE_REQUEST_TABLE).where(
                    PROFILE_SAVE_REQUEST_TABLE.c.user_id == command.user_id,
                    PROFILE_SAVE_REQUEST_TABLE.c.idempotency_key == command.idempotency_key,
                )
            )
            replay = replay_result.mappings().one_or_none()
            if replay is not None:
                if replay.request_hash != command.request_hash:
                    raise ProfileIdempotencyConflictError
                snapshot = await _get_version(
                    database,
                    command.user_id,
                    replay.profile_id,
                    replay.profile_version,
                )
                if snapshot is None:
                    raise RuntimeError("profile idempotency result is missing")
                return snapshot

            current = await _find_current(database, command.user_id)
            snapshot = plan_profile_save(current, command)
            if current is None or snapshot.version != current.version:
                await database.execute(sa.insert(PROFILE_TABLE).values(_snapshot_values(snapshot)))
            await database.execute(
                sa.insert(PROFILE_SAVE_REQUEST_TABLE).values(
                    user_id=command.user_id,
                    idempotency_key=command.idempotency_key,
                    request_hash=command.request_hash,
                    profile_id=snapshot.id,
                    profile_version=snapshot.version,
                    created_at=command.created_at,
                )
            )
            return snapshot

    async def save_snapshot(self, snapshot: ProfileSnapshot) -> None:
        """Insert a test/seed snapshot; production writes use save_current."""
        async with self._session_factory() as session:
            await session.execute(sa.insert(PROFILE_TABLE).values(_snapshot_values(snapshot)))
            await session.commit()


async def _find_current(session: AsyncSession, user_id: str) -> ProfileSnapshot | None:
    result = await session.execute(
        sa.select(PROFILE_TABLE)
        .where(PROFILE_TABLE.c.user_id == user_id)
        .order_by(PROFILE_TABLE.c.version.desc())
        .limit(1)
    )
    row = result.mappings().one_or_none()
    return row_to_profile_snapshot(row) if row is not None else None


async def _get_version(
    session: AsyncSession,
    user_id: str,
    profile_id: str,
    version: int,
) -> ProfileSnapshot | None:
    result = await session.execute(
        sa.select(PROFILE_TABLE).where(
            PROFILE_TABLE.c.user_id == user_id,
            PROFILE_TABLE.c.id == profile_id,
            PROFILE_TABLE.c.version == version,
        )
    )
    row = result.mappings().one_or_none()
    return row_to_profile_snapshot(row) if row is not None else None


def _snapshot_values(snapshot: ProfileSnapshot) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "user_id": snapshot.user_id,
        "version": snapshot.version,
        "target_locations": list(snapshot.target_locations),
        "target_roles": list(snapshot.target_roles),
        "recruitment_types": [str(value) for value in snapshot.recruitment_types],
        "skills": list(snapshot.skills),
        "excluded_roles": list(snapshot.excluded_roles),
        "education": str(snapshot.education) if snapshot.education is not None else None,
        "graduation_year": snapshot.graduation_year,
        "expected_salary_min": snapshot.expected_salary_min,
        "experience_summary": snapshot.experience_summary,
        "extra_request": snapshot.extra_request,
        "warnings": list(snapshot.warnings),
        "created_at": snapshot.created_at,
    }


__all__ = [
    "PROFILE_SAVE_REQUEST_TABLE",
    "PROFILE_TABLE",
    "PostgresProfileStore",
    "row_to_profile_snapshot",
]
