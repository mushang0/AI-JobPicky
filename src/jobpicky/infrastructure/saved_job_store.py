from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import ErrorCode, JobFact, JobSourceView
from ..errors import ApplicationError
from .job_catalog import JOB_TABLE, row_to_job_fact
from .job_pool_store import row_to_source_view
from .source_store import JOB_SOURCE_TABLE

SAVED_JOB_TABLE = sa.table(
    "saved_job",
    sa.column("user_id", sa.String),
    sa.column("job_id", sa.String),
    sa.column("saved_at", sa.DateTime(timezone=True)),
)


@dataclass(frozen=True, slots=True)
class SavedJobRecord:
    saved_at: datetime
    job: JobFact
    source: JobSourceView


class PostgresSavedJobStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def set_saved(self, user_id: str, job_id: str, is_saved: bool) -> None:
        async with self._session_factory() as session, session.begin():
            exists = await session.scalar(
                sa.select(sa.literal(True)).where(JOB_TABLE.c.id == job_id).limit(1)
            )
            if not exists:
                raise ApplicationError(
                    ErrorCode.NOT_FOUND,
                    "job not found",
                    status_code=404,
                )
            if is_saved:
                statement = postgresql.insert(SAVED_JOB_TABLE).values(
                    user_id=user_id,
                    job_id=job_id,
                    saved_at=sa.func.now(),
                )
                await session.execute(
                    statement.on_conflict_do_nothing(index_elements=["user_id", "job_id"])
                )
            else:
                await session.execute(
                    sa.delete(SAVED_JOB_TABLE).where(
                        SAVED_JOB_TABLE.c.user_id == user_id,
                        SAVED_JOB_TABLE.c.job_id == job_id,
                    )
                )

    async def get_saved_ids(self, user_id: str, job_ids: Sequence[str]) -> set[str]:
        if not job_ids:
            return set()
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(SAVED_JOB_TABLE.c.job_id).where(
                    SAVED_JOB_TABLE.c.user_id == user_id,
                    SAVED_JOB_TABLE.c.job_id.in_(job_ids),
                )
            )
            return {str(job_id) for job_id in result.scalars()}

    async def list_saved(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[SavedJobRecord], int]:
        join = SAVED_JOB_TABLE.join(
            JOB_TABLE, JOB_TABLE.c.id == SAVED_JOB_TABLE.c.job_id
        ).outerjoin(JOB_SOURCE_TABLE, JOB_SOURCE_TABLE.c.id == JOB_TABLE.c.source_id)
        async with self._session_factory() as session:
            total = await session.scalar(
                sa.select(sa.func.count())
                .select_from(join)
                .where(SAVED_JOB_TABLE.c.user_id == user_id)
            )
            result = await session.execute(
                sa.select(
                    SAVED_JOB_TABLE.c.saved_at,
                    JOB_TABLE,
                    JOB_SOURCE_TABLE.c.display_name.label("source_name"),
                )
                .select_from(join)
                .where(SAVED_JOB_TABLE.c.user_id == user_id)
                .order_by(
                    SAVED_JOB_TABLE.c.saved_at.desc(),
                    JOB_TABLE.c.id.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            records = [
                SavedJobRecord(
                    saved_at=row.saved_at,
                    job=row_to_job_fact(row),
                    source=row_to_source_view(row),
                )
                for row in result.mappings()
            ]
        return records, int(total or 0)


__all__ = ["PostgresSavedJobStore", "SAVED_JOB_TABLE", "SavedJobRecord"]
