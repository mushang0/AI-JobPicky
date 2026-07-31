from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import JobFact, JobSourceView
from .job_catalog import JOB_TABLE, row_to_job_fact
from .source_store import JOB_SOURCE_TABLE


def _source_name(row: sa.RowMapping) -> str:
    return str(row.get("source_name") or row.source_id)


def row_to_source_view(row: sa.RowMapping) -> JobSourceView:
    return JobSourceView(id=row.source_id, name=_source_name(row))


class PostgresJobPoolStore:
    """Read-only job-pool adapter; query rules stay in ``catalog.service``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_visible(
        self,
        limit: int,
    ) -> list[tuple[JobFact, JobSourceView]]:
        rows = await self._job_rows(
            sa.select(JOB_TABLE, JOB_SOURCE_TABLE.c.display_name.label("source_name"))
            .select_from(
                JOB_TABLE.outerjoin(
                    JOB_SOURCE_TABLE, JOB_SOURCE_TABLE.c.id == JOB_TABLE.c.source_id
                )
            )
            .where(JOB_TABLE.c.status == "OPEN")
            .order_by(JOB_TABLE.c.last_confirmed_at.desc(), JOB_TABLE.c.id.asc())
            .limit(limit)
        )
        return [(row_to_job_fact(row), row_to_source_view(row)) for row in rows]

    async def get_job(self, job_id: str) -> tuple[JobFact, JobSourceView] | None:
        rows = await self._job_rows(
            sa.select(JOB_TABLE, JOB_SOURCE_TABLE.c.display_name.label("source_name"))
            .select_from(
                JOB_TABLE.outerjoin(
                    JOB_SOURCE_TABLE, JOB_SOURCE_TABLE.c.id == JOB_TABLE.c.source_id
                )
            )
            .where(JOB_TABLE.c.id == job_id)
            .limit(1)
        )
        if not rows:
            return None
        row = rows[0]
        return row_to_job_fact(row), row_to_source_view(row)

    async def _job_rows(self, statement: sa.Select[tuple[object, ...]]) -> list[sa.RowMapping]:
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return list(result.mappings())


__all__ = ["JOB_SOURCE_TABLE", "PostgresJobPoolStore", "row_to_source_view"]
