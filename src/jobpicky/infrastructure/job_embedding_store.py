from __future__ import annotations

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import ErrorCode, JobFact
from ..errors import ApplicationError
from ..ports import JobEmbeddingStorePort
from .job_catalog import JOB_TABLE, row_to_job_fact


class PostgresJobEmbeddingStore(JobEmbeddingStorePort):
    """PostgreSQL adapter for explicit, repeatable job embedding backfills."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_jobs_without_embeddings(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[JobFact]:
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must be non-negative")
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(JOB_TABLE)
                .where(JOB_TABLE.c.embedding.is_(None))
                .order_by(JOB_TABLE.c.id.asc())
                .offset(offset)
                .limit(limit)
            )
            return [row_to_job_fact(row) for row in result.mappings()]

    async def save_embeddings(self, embeddings: Mapping[str, Sequence[float]]) -> None:
        if not embeddings:
            return
        rows: list[dict[str, object]] = []
        for job_id, vector in embeddings.items():
            values = [float(value) for value in vector]
            if len(values) != 512:
                raise ApplicationError(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    "cannot persist an embedding with an invalid dimension",
                    status_code=503,
                    details={"dependency": "embedding", "job_id": job_id},
                )
            rows.append({"job_id": job_id, "embedding": values})

        async with self._session_factory() as session:
            await session.execute(
                sa.update(JOB_TABLE)
                .where(JOB_TABLE.c.id == sa.bindparam("job_id"))
                .values(
                    embedding=sa.bindparam(
                        "embedding_value",
                        type_=JOB_TABLE.c.embedding.type,
                    )
                ),
                [{"job_id": row["job_id"], "embedding_value": row["embedding"]} for row in rows],
            )
            await session.commit()


__all__ = ["PostgresJobEmbeddingStore"]
