from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..catalog.query_terms import extract_terms
from ..contracts import (
    CompanyListItem,
    CompanyPoolPage,
    EducationLevel,
    FilterOptionsLimits,
    JobFact,
    JobFilterOptions,
    JobFilterSource,
    JobListQuery,
    JobSourceView,
    RecruitmentType,
    normalize_city,
)
from .job_catalog import JOB_TABLE, row_to_job_fact
from .source_store import JOB_SOURCE_TABLE


def _source_name(row: sa.RowMapping) -> str:
    return _display_source_name(row.source_id, row.get("source_name"))


def _display_source_name(source_id: str, stored_name: object) -> str:
    name = str(stored_name or "").strip()
    return name or str(source_id).strip() or "公开招聘公告"


def row_to_source_view(row: sa.RowMapping) -> JobSourceView:
    return JobSourceView(id=row.source_id, name=_source_name(row))


class PostgresJobPoolStore:
    """PostgreSQL adapter for list queries; detail reads remain full-fact reads."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_visible(
        self,
    ) -> list[tuple[JobFact, JobSourceView]]:
        rows = await self._job_rows(
            sa.select(JOB_TABLE, JOB_SOURCE_TABLE.c.display_name.label("source_name"))
            .select_from(
                JOB_TABLE.outerjoin(
                    JOB_SOURCE_TABLE, JOB_SOURCE_TABLE.c.id == JOB_TABLE.c.source_id
                )
            )
            .where(JOB_TABLE.c.status == "OPEN")
            .order_by(
                JOB_TABLE.c.published_at.desc().nulls_last(),
                JOB_TABLE.c.last_confirmed_at.desc(),
                JOB_TABLE.c.id.asc(),
            )
        )
        return [(row_to_job_fact(row), row_to_source_view(row)) for row in rows]

    async def list_page(
        self,
        query: JobListQuery,
        preview_length: int,
    ) -> tuple[list[tuple[JobFact, JobSourceView]], int, int]:
        conditions = _where_conditions(query)
        list_statement = (
            sa.select(
                *_list_columns(preview_length),
                JOB_SOURCE_TABLE.c.display_name.label("source_name"),
            )
            .select_from(
                JOB_TABLE.outerjoin(
                    JOB_SOURCE_TABLE, JOB_SOURCE_TABLE.c.id == JOB_TABLE.c.source_id
                )
            )
            .where(*conditions)
            .order_by(*_order_by(query))
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        total_statement = sa.select(sa.func.count()).select_from(
            sa.select(JOB_TABLE.c.id).where(*conditions).subquery()
        )
        pool_total_statement = (
            sa.select(sa.func.count()).select_from(JOB_TABLE).where(JOB_TABLE.c.status == "OPEN")
        )
        async with self._session_factory() as session:
            rows = list((await session.execute(list_statement)).mappings())
            total = int((await session.execute(total_statement)).scalar_one())
            pool_total = int((await session.execute(pool_total_statement)).scalar_one())
        return (
            [(row_to_job_fact(row), row_to_source_view(row)) for row in rows],
            total,
            pool_total,
        )

    async def list_companies(self, query: JobListQuery) -> CompanyPoolPage:
        ranked = _company_ranked_query(query).subquery("matching_jobs")
        latest_published_at = sa.func.max(ranked.c.published_at).label("latest_published_at")
        grouped = (
            sa.select(
                ranked.c.company_group_key.label("group_id"),
                sa.func.min(ranked.c.company_name).label("company_name"),
                sa.func.min(ranked.c.company_nature).label("company_nature"),
                sa.func.count().label("job_count"),
                latest_published_at,
                sa.func.array_agg(
                    postgresql.aggregate_order_by(ranked.c.title, ranked.c.title_rank)
                )
                .filter(ranked.c.title_rank <= 3)
                .label("job_titles"),
            )
            .group_by(ranked.c.company_group_key)
            .order_by(latest_published_at.desc().nulls_last(), ranked.c.company_group_key.asc())
        )
        total_statement = sa.select(sa.func.count()).select_from(grouped.subquery())
        pool_total_statement = sa.select(
            sa.func.count(sa.distinct(JOB_TABLE.c.company_group_key))
        ).where(JOB_TABLE.c.status == "OPEN")
        page_statement = grouped.offset((query.page - 1) * query.page_size).limit(query.page_size)

        async with self._session_factory() as session:
            rows = list((await session.execute(page_statement)).mappings())
            total = int((await session.execute(total_statement)).scalar_one())
            pool_total = int((await session.execute(pool_total_statement)).scalar_one())

        items = [
            CompanyListItem(
                group_id=row.group_id,
                company_name=row.company_name,
                company_nature=row.company_nature,
                job_titles=list(row.job_titles or [])[:3],
                job_count=row.job_count,
                latest_published_at=row.latest_published_at,
            )
            for row in rows
        ]
        return CompanyPoolPage(
            items=items,
            total=total,
            page=query.page,
            page_size=query.page_size,
            pool_total=pool_total,
        )

    async def get_filter_options(self, limits: FilterOptionsLimits) -> JobFilterOptions:
        visible = JOB_TABLE.c.status == "OPEN"
        city_statement = sa.select(sa.distinct(sa.func.unnest(JOB_TABLE.c.locations))).where(
            visible
        )
        nature_statement = sa.select(sa.distinct(JOB_TABLE.c.company_nature)).where(
            visible, JOB_TABLE.c.company_nature.is_not(None)
        )
        batch_statement = sa.select(sa.distinct(sa.func.unnest(JOB_TABLE.c.batch_tokens))).where(
            visible
        )
        graduation_statement = sa.select(
            sa.distinct(sa.func.unnest(JOB_TABLE.c.graduation_years))
        ).where(visible)
        source_statement = (
            sa.select(JOB_TABLE.c.source_id, JOB_SOURCE_TABLE.c.display_name.label("source_name"))
            .select_from(
                JOB_TABLE.outerjoin(
                    JOB_SOURCE_TABLE, JOB_SOURCE_TABLE.c.id == JOB_TABLE.c.source_id
                )
            )
            .where(visible)
            .group_by(JOB_TABLE.c.source_id, JOB_SOURCE_TABLE.c.display_name)
        )
        async with self._session_factory() as session:
            cities = list((await session.execute(city_statement)).scalars())
            natures = list((await session.execute(nature_statement)).scalars())
            batches = list((await session.execute(batch_statement)).scalars())
            graduation_years = list((await session.execute(graduation_statement)).scalars())
            sources = list((await session.execute(source_statement)).mappings())

        grouped_sources: dict[str, set[str]] = {}
        for row in sources:
            source_id = str(row.source_id)
            name = _display_source_name(source_id, row.get("source_name"))
            grouped_sources.setdefault(name, set()).add(source_id)
        return JobFilterOptions(
            cities=sorted(
                {canonical for value in cities if (canonical := normalize_city(str(value)))}
            ),
            company_natures=sorted(str(value) for value in natures if value),
            sources=[
                JobFilterSource(platform=name, source_ids=sorted(source_ids))
                for name, source_ids in sorted(grouped_sources.items())
            ],
            batches=sorted(str(value) for value in batches if value),
            recruitment_types=list(RecruitmentType),
            educations=list(EducationLevel),
            graduation_years=sorted(int(value) for value in graduation_years if value is not None),
            limits=limits,
        )

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


def _list_columns(preview_length: int) -> list[sa.ColumnElement[object]]:
    return [
        JOB_TABLE.c.id,
        JOB_TABLE.c.source_id,
        JOB_TABLE.c.company_name,
        JOB_TABLE.c.company_nature,
        JOB_TABLE.c.title,
        JOB_TABLE.c.locations,
        sa.func.left(JOB_TABLE.c.description, preview_length + 1).label("description"),
        JOB_TABLE.c.metadata,
        JOB_TABLE.c.detail_url,
        JOB_TABLE.c.apply_url,
        JOB_TABLE.c.recruitment_type,
        JOB_TABLE.c.education_requirement,
        JOB_TABLE.c.salary_min,
        JOB_TABLE.c.salary_max,
        JOB_TABLE.c.salary_months,
        JOB_TABLE.c.graduation_years,
        JOB_TABLE.c.status,
        JOB_TABLE.c.fact_version,
        JOB_TABLE.c.published_at,
        JOB_TABLE.c.deadline_at,
        JOB_TABLE.c.first_seen_at,
        JOB_TABLE.c.last_confirmed_at,
        JOB_TABLE.c.updated_at,
    ]


def _where_conditions(query: JobListQuery) -> list[sa.ColumnElement[bool]]:
    conditions: list[sa.ColumnElement[bool]] = [JOB_TABLE.c.status == "OPEN"]
    if query.company_group_id:
        conditions.append(JOB_TABLE.c.company_group_key == query.company_group_id)
    if query.published_at_unknown:
        conditions.append(JOB_TABLE.c.published_at.is_(None))
    elif query.published_within_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=query.published_within_days)
        conditions.append(JOB_TABLE.c.published_at >= cutoff)
    if query.city:
        conditions.append(
            sa.or_(
                sa.func.cardinality(JOB_TABLE.c.locations) == 0,
                JOB_TABLE.c.locations.overlap(query.city),
            )
        )
    if query.company_nature:
        conditions.append(
            sa.or_(
                JOB_TABLE.c.company_nature.is_(None),
                JOB_TABLE.c.company_nature.in_(query.company_nature),
            )
        )
    if query.source_id:
        conditions.append(JOB_TABLE.c.source_id.in_(query.source_id))
    if query.batch:
        conditions.append(
            sa.or_(
                sa.func.cardinality(JOB_TABLE.c.batch_tokens) == 0,
                JOB_TABLE.c.batch_tokens.overlap(query.batch),
            )
        )
    if query.recruitment_type:
        conditions.append(
            sa.or_(
                JOB_TABLE.c.recruitment_type.is_(None),
                JOB_TABLE.c.recruitment_type.in_(query.recruitment_type),
            )
        )
    if query.education:
        conditions.append(
            sa.or_(
                JOB_TABLE.c.education_requirement.is_(None),
                JOB_TABLE.c.education_requirement.in_(query.education),
            )
        )
    if query.graduation_year:
        conditions.append(
            sa.or_(
                sa.func.cardinality(JOB_TABLE.c.graduation_years) == 0,
                JOB_TABLE.c.graduation_years.overlap(query.graduation_year),
            )
        )
    if query.salary_min is not None:
        conditions.append(
            sa.or_(JOB_TABLE.c.salary_max.is_(None), JOB_TABLE.c.salary_max >= query.salary_min)
        )
    if query.salary_max is not None:
        conditions.append(
            sa.or_(JOB_TABLE.c.salary_min.is_(None), JOB_TABLE.c.salary_min <= query.salary_max)
        )
    terms = _search_terms(query.q)
    if terms:
        haystack = _search_haystack()
        conditions.append(sa.or_(*(haystack.like(f"%{term}%") for term in terms)))
    return conditions


def _company_ranked_query(query: JobListQuery) -> sa.Select[tuple[object, ...]]:
    return sa.select(
        JOB_TABLE.c.company_group_key,
        JOB_TABLE.c.company_name,
        JOB_TABLE.c.company_nature,
        JOB_TABLE.c.title,
        JOB_TABLE.c.id,
        JOB_TABLE.c.published_at,
        sa.func.row_number()
        .over(
            partition_by=JOB_TABLE.c.company_group_key,
            order_by=(
                JOB_TABLE.c.published_at.desc().nulls_last(),
                JOB_TABLE.c.title.asc(),
                JOB_TABLE.c.id.asc(),
            ),
        )
        .label("title_rank"),
    ).where(*_where_conditions(query))


def _order_by(query: JobListQuery) -> list[sa.ColumnElement[object]]:
    terms = _search_terms(query.q)
    if not terms:
        return [
            JOB_TABLE.c.published_at.desc().nulls_last(),
            JOB_TABLE.c.last_confirmed_at.desc(),
            JOB_TABLE.c.id.asc(),
        ]
    haystack = _search_haystack()
    score = sum(
        (sa.case((haystack.like(f"%{term}%"), 1), else_=0) for term in terms),
        sa.literal(0),
    )
    return [
        score.desc(),
        JOB_TABLE.c.published_at.desc().nulls_last(),
        JOB_TABLE.c.last_confirmed_at.desc(),
        JOB_TABLE.c.id.asc(),
    ]


def _search_haystack() -> sa.ColumnElement[str]:
    return sa.func.lower(
        sa.func.concat_ws(
            " ",
            JOB_TABLE.c.title,
            JOB_TABLE.c.company_name,
            sa.func.array_to_string(JOB_TABLE.c.locations, " "),
            JOB_TABLE.c.description,
        )
    )


def _search_terms(query: str | None) -> list[str]:
    if not query:
        return []
    terms = extract_terms(query)
    return terms or [query.casefold()]


__all__ = ["JOB_SOURCE_TABLE", "PostgresJobPoolStore", "row_to_source_view"]
