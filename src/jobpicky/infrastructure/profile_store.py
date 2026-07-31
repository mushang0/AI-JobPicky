from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import ErrorCode, ProfileSnapshot
from ..errors import ApplicationError

# Lightweight Core mapping of the profile table; Alembic migrations remain the
# single source of truth for the schema (same pattern as job_catalog.py).
PROFILE_TABLE = sa.table(
    "profile",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("version", sa.Integer),
    sa.column("target_locations", postgresql.ARRAY(sa.String)),
    sa.column("target_roles", postgresql.ARRAY(sa.String)),
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
    """PostgreSQL implementation of ProfileSnapshotReaderPort.

    Only the read side is a port. save_snapshot exists for seed data and
    tests; the real write path (resume parsing, corrections) belongs to the
    profiles slice and ProfileApplicationPort, which is not implemented yet.
    """

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

    async def get_current(self, user_id: str) -> ProfileSnapshot:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(PROFILE_TABLE)
                .where(PROFILE_TABLE.c.user_id == user_id)
                .order_by(PROFILE_TABLE.c.version.desc())
                .limit(1)
            )
            row = result.mappings().first()
        if row is None:
            raise ApplicationError(
                ErrorCode.PROFILE_NOT_FOUND,
                "profile not found",
                status_code=404,
            )
        return row_to_profile_snapshot(row)

    async def save_snapshot(self, snapshot: ProfileSnapshot) -> None:
        async with self._session_factory() as session:
            await session.execute(
                sa.insert(PROFILE_TABLE),
                [snapshot.model_dump()],
            )
            await session.commit()


__all__ = ["PROFILE_TABLE", "PostgresProfileStore", "row_to_profile_snapshot"]
