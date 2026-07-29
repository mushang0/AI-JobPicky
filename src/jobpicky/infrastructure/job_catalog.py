from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..catalog import apply_filter, extract_terms, term_hit_score
from ..contracts import (
    CollectionBatch,
    ErrorCode,
    FilterResult,
    HardFilterSpec,
    IngestionResult,
    JobFact,
    RetrievalChannel,
    SearchHit,
)
from ..errors import ApplicationError

# Lightweight Core mapping of the job table for read queries. The Alembic
# migrations remain the single source of truth for the schema (plan 003).
JOB_TABLE = sa.table(
    "job",
    sa.column("id", sa.String),
    sa.column("source_id", sa.String),
    sa.column("company_name", sa.String),
    sa.column("company_nature", sa.String),
    sa.column("title", sa.String),
    sa.column("locations", postgresql.ARRAY(sa.String)),
    sa.column("description", sa.Text),
    sa.column("detail_url", sa.String),
    sa.column("apply_url", sa.String),
    sa.column("recruitment_type", sa.String),
    sa.column("education_requirement", sa.String),
    sa.column("salary_min", sa.Integer),
    sa.column("salary_max", sa.Integer),
    sa.column("salary_months", sa.Integer),
    sa.column("graduation_years", postgresql.ARRAY(sa.Integer)),
    sa.column("status", sa.String),
    sa.column("fact_version", sa.String),
    sa.column("published_at", sa.DateTime(timezone=True)),
    sa.column("deadline_at", sa.DateTime(timezone=True)),
    sa.column("first_seen_at", sa.DateTime(timezone=True)),
    sa.column("last_confirmed_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def row_to_job_fact(row: sa.RowMapping) -> JobFact:
    return JobFact(
        id=row.id,
        source_id=row.source_id,
        company_name=row.company_name,
        company_nature=row.company_nature,
        title=row.title,
        locations=list(row.locations),
        description=row.description,
        detail_url=row.detail_url,
        apply_url=row.apply_url,
        recruitment_type=row.recruitment_type,
        education_requirement=row.education_requirement,
        salary_min=row.salary_min,
        salary_max=row.salary_max,
        salary_months=row.salary_months,
        graduation_years=list(row.graduation_years or []),
        status=row.status,
        fact_version=row.fact_version,
        published_at=row.published_at,
        deadline_at=row.deadline_at,
        first_seen_at=row.first_seen_at,
        last_confirmed_at=row.last_confirmed_at,
        updated_at=row.updated_at,
    )


class PostgresJobCatalog:
    """PostgreSQL implementation of the search side of JobCatalogPort.

    Rows are read into JobFact contracts and all judgement happens in the
    pure catalog functions: the data volume is campus-sample scale, so a
    single source of deterministic, offline-testable logic beats SQL pushdown
    (plan 003, decision 2).

    ingest belongs to the collection slice and semantic_search waits on the
    embedding vendor decision (architecture section 7.3); both fail
    explicitly instead of faking capability.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ingest(self, run_id: str, batch: CollectionBatch) -> IngestionResult:
        raise ApplicationError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "job ingestion is not implemented yet; it belongs to the collection slice",
            status_code=503,
        )

    async def get_jobs(self, job_ids: Sequence[str]) -> list[JobFact]:
        if not job_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(sa.select(JOB_TABLE).where(JOB_TABLE.c.id.in_(job_ids)))
            by_id = {row.id: row_to_job_fact(row) for row in result.mappings()}
        return [by_id[job_id] for job_id in job_ids if job_id in by_id]

    async def hard_filter(self, spec: HardFilterSpec) -> FilterResult:
        async with self._session_factory() as session:
            result = await session.execute(sa.select(JOB_TABLE))
            jobs = [row_to_job_fact(row) for row in result.mappings()]
        return apply_filter(spec, jobs)

    async def keyword_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        terms = extract_terms(query_text)
        if not terms or not eligible_job_ids:
            return []
        jobs = await self.get_jobs(eligible_job_ids)
        hits = [
            SearchHit(
                job_id=job.id,
                score=term_hit_score(terms, job),
                channel=RetrievalChannel.KEYWORD,
            )
            for job in jobs
        ]
        positive = [hit for hit in hits if hit.score > 0]
        return sorted(positive, key=lambda hit: (-hit.score, hit.job_id))

    async def semantic_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        raise ApplicationError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "semantic search is not available: embedding vendor is not selected "
            "and the job.embedding column does not exist yet",
            status_code=503,
        )


__all__ = ["JOB_TABLE", "PostgresJobCatalog", "row_to_job_fact"]
