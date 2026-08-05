from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from ..config import Settings
from ..contracts import (
    CompanyListItem,
    CompanyPoolPage,
    EducationLevel,
    ErrorCode,
    FilterOptionsLimits,
    JobDetailView,
    JobFact,
    JobFilterOptions,
    JobFilterSource,
    JobListItem,
    JobListQuery,
    JobPoolPage,
    JobSourceView,
    Page,
    RecruitmentType,
    SavedJobItem,
    SavedJobState,
    SavedJobView,
)
from ..contracts.normalization import (
    normalize_city,
    normalize_company_nature,
    normalize_education,
    normalize_recruitment_type,
    split_batch_values,
)
from ..errors import ApplicationError
from ..infrastructure.saved_job_store import SavedJobRecord
from .query_terms import extract_terms

_SPACE_RE = re.compile(r"\s+")


def _job_sort_key(job: JobFact) -> tuple[bool, float, float, str]:
    return (
        job.published_at is None,
        -(job.published_at.timestamp() if job.published_at else 0.0),
        -job.last_confirmed_at.timestamp(),
        job.id,
    )


class JobPoolStore(Protocol):
    async def list_visible(self) -> list[tuple[JobFact, JobSourceView]]: ...

    async def get_job(self, job_id: str) -> tuple[JobFact, JobSourceView] | None: ...


class SavedJobStore(Protocol):
    async def set_saved(self, user_id: str, job_id: str, is_saved: bool) -> None: ...

    async def get_saved_ids(self, user_id: str, job_ids: Sequence[str]) -> set[str]: ...

    async def list_saved(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[SavedJobRecord], int]: ...


@dataclass(frozen=True, slots=True)
class _FilterCache:
    expires_at: float
    value: JobFilterOptions


class JobPoolService:
    def __init__(
        self,
        jobs: JobPoolStore,
        saved_jobs: SavedJobStore,
        settings: Settings,
    ) -> None:
        self._jobs = jobs
        self._saved_jobs = saved_jobs
        self._settings = settings
        self._filter_cache: _FilterCache | None = None
        self._filter_cache_lock = asyncio.Lock()

    async def list_jobs(self, user_id: str | None, query: JobListQuery) -> JobPoolPage:
        self._authorize_pool_query(user_id, query)
        optimized = getattr(self._jobs, "list_page", None)
        if callable(optimized):
            page_items, total, pool_total = await optimized(
                query, self._settings.job_description_preview_length
            )
            return await self._build_job_page(
                user_id,
                query,
                page_items,
                total=total,
                pool_total=pool_total,
            )

        pool = await self._jobs.list_visible()
        filtered = [(job, source) for job, source in pool if self._matches(job, query)]
        terms = _search_terms(query.q)
        if terms:
            ranked = [
                (sum(term in _haystack(job) for term in terms), job, source)
                for job, source in filtered
            ]
            ranked = [item for item in ranked if item[0] > 0]
            ranked.sort(key=lambda item: (-item[0], *_job_sort_key(item[1])))
            filtered = [(job, source) for _, job, source in ranked]
        else:
            filtered.sort(key=lambda item: _job_sort_key(item[0]))

        start = (query.page - 1) * query.page_size
        page_items = filtered[start : start + query.page_size]
        return await self._build_job_page(
            user_id,
            query,
            page_items,
            total=len(filtered),
            pool_total=len(pool),
        )

    async def _build_job_page(
        self,
        user_id: str | None,
        query: JobListQuery,
        page_items: list[tuple[JobFact, JobSourceView]],
        *,
        total: int,
        pool_total: int,
    ) -> JobPoolPage:
        saved_ids = (
            await self._saved_jobs.get_saved_ids(user_id, [job.id for job, _ in page_items])
            if user_id
            else set()
        )
        return JobPoolPage(
            items=[
                _to_list_item(
                    job,
                    source,
                    is_saved=(job.id in saved_ids) if user_id else None,
                    preview_length=self._settings.job_description_preview_length,
                )
                for job, source in page_items
            ],
            total=total,
            page=query.page,
            page_size=query.page_size,
            pool_total=pool_total,
        )

    async def list_companies(self, user_id: str | None, query: JobListQuery) -> CompanyPoolPage:
        self._authorize_pool_query(user_id, query)
        optimized = getattr(self._jobs, "list_companies", None)
        if callable(optimized):
            return await optimized(query)

        pool = await self._jobs.list_visible()
        matching = [(job, source) for job, source in pool if self._matches(job, query)]
        terms = _search_terms(query.q)
        if terms:
            matching = [
                item for item in matching if any(term in _haystack(item[0]) for term in terms)
            ]
            matching.sort(
                key=lambda item: (
                    -sum(term in _haystack(item[0]) for term in terms),
                    *_job_sort_key(item[0]),
                )
            )
        else:
            matching.sort(key=lambda item: _job_sort_key(item[0]))

        groups: dict[str, list[JobFact]] = {}
        for job, _ in matching:
            groups.setdefault(_company_group_key(job), []).append(job)
        ordered_groups = sorted(
            groups.items(),
            key=lambda item: _job_sort_key(item[1][0]),
        )
        pool_groups: set[str] = set()
        for job, _ in pool:
            pool_groups.add(_company_group_key(job))
        start = (query.page - 1) * query.page_size
        items = [
            CompanyListItem(
                group_id=group_id,
                company_name=jobs[0].company_name,
                company_nature=next(
                    (job.company_nature for job in jobs if job.company_nature), None
                ),
                job_titles=[job.title for job in jobs[:3]],
                job_count=len(jobs),
                latest_published_at=jobs[0].published_at,
            )
            for group_id, jobs in ordered_groups[start : start + query.page_size]
        ]
        return CompanyPoolPage(
            items=items,
            total=len(ordered_groups),
            page=query.page,
            page_size=query.page_size,
            pool_total=len(pool_groups),
        )

    async def get_job(self, user_id: str | None, job_id: str) -> JobDetailView:
        record = await self._jobs.get_job(job_id)
        if record is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "job not found", status_code=404)
        job, source = record
        is_saved = (
            job_id in await self._saved_jobs.get_saved_ids(user_id, [job_id]) if user_id else None
        )
        return _to_detail_view(job, source, is_saved=is_saved)

    async def get_filter_options(self) -> JobFilterOptions:
        now = time.monotonic()
        cached = self._filter_cache
        if cached is not None and cached.expires_at > now:
            return cached.value
        async with self._filter_cache_lock:
            now = time.monotonic()
            cached = self._filter_cache
            if cached is not None and cached.expires_at > now:
                return cached.value
            limits = FilterOptionsLimits(
                default_page_size=self._settings.job_pool_default_page_size,
                public_page_size_max=self._settings.job_pool_public_page_size_max,
                authenticated_page_size_max=self._settings.job_pool_authenticated_page_size_max,
            )
            optimized = getattr(self._jobs, "get_filter_options", None)
            if callable(optimized):
                value = await optimized(limits)
                self._filter_cache = _FilterCache(expires_at=now + 300, value=value)
                return value
            pool = await self._jobs.list_visible()
            value = JobFilterOptions(
                cities=sorted(
                    {
                        city
                        for job, _ in pool
                        for location in job.locations
                        if (city := normalize_city(location)) is not None
                    }
                ),
                company_natures=sorted(
                    {
                        nature
                        for job, _ in pool
                        if (nature := normalize_company_nature(job.company_nature)) is not None
                    }
                ),
                sources=_group_filter_sources(pool),
                batches=sorted({batch for job, _ in pool for batch in _batch_values(job)}),
                recruitment_types=list(RecruitmentType),
                educations=list(EducationLevel),
                graduation_years=sorted({year for job, _ in pool for year in job.graduation_years}),
                limits=limits,
            )
            self._filter_cache = _FilterCache(expires_at=now + 300, value=value)
            return value

    async def set_saved(self, user_id: str, job_id: str, is_saved: bool) -> SavedJobState:
        await self._saved_jobs.set_saved(user_id, job_id, is_saved)
        return SavedJobState(job_id=job_id, is_saved=is_saved)

    async def list_saved(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> Page[SavedJobView]:
        if page < 1 or not 1 <= page_size <= self._settings.saved_jobs_page_size_max:
            raise ApplicationError(
                ErrorCode.VALIDATION_ERROR,
                "invalid pagination",
                status_code=422,
            )
        records, total = await self._saved_jobs.list_saved(user_id, page, page_size)
        return Page[SavedJobView](
            items=[
                SavedJobView(
                    saved_at=record.saved_at,
                    job=SavedJobItem(
                        **_to_list_item(
                            record.job,
                            record.source,
                            is_saved=True,
                            preview_length=self._settings.job_description_preview_length,
                        ).model_dump(),
                        status=record.job.status,
                    ),
                )
                for record in records
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def _authorize_pool_query(self, user_id: str | None, query: JobListQuery) -> None:
        if query.page_size > self._settings.job_pool_authenticated_page_size_max:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "invalid page size", status_code=422)
        if user_id is not None:
            return
        has_filter = any(
            (
                query.city,
                query.company_nature,
                query.source_id,
                query.batch,
                query.recruitment_type,
                query.education,
                query.graduation_year,
                query.salary_min is not None,
                query.salary_max is not None,
                query.published_within_days is not None,
                query.published_at_unknown,
            )
        )
        if (
            query.page >= 2
            or query.q is not None
            or has_filter
            or query.page_size > self._settings.job_pool_public_page_size_max
        ):
            raise ApplicationError(
                ErrorCode.AUTHENTICATION_REQUIRED,
                "authentication required",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

    @staticmethod
    def _matches(job: JobFact, query: JobListQuery) -> bool:
        if query.published_at_unknown:
            if job.published_at is not None:
                return False
        elif query.published_within_days is not None:
            if job.published_at is None:
                return False
            cutoff = datetime.now(UTC) - timedelta(days=query.published_within_days)
            if job.published_at < cutoff:
                return False
        if query.city:
            known_locations = {
                canonical
                for location in job.locations
                if (canonical := normalize_city(location)) is not None
            }
            if known_locations and not known_locations.intersection(query.city):
                return False
        if query.company_nature:
            nature = normalize_company_nature(job.company_nature)
            if nature is not None and nature not in query.company_nature:
                return False
        if query.source_id and job.source_id not in query.source_id:
            return False
        if query.company_group_id and _company_group_key(job) != query.company_group_id:
            return False
        if query.batch:
            batches = _batch_values(job)
            if batches and not set(batches).intersection(query.batch):
                return False
        if query.recruitment_type:
            recruitment_type = normalize_recruitment_type(job.recruitment_type)
            if recruitment_type is not None and recruitment_type not in query.recruitment_type:
                return False
        if query.education:
            education = normalize_education(job.education_requirement)
            if education is not None and education not in query.education:
                return False
        if (
            query.graduation_year
            and job.graduation_years
            and not set(query.graduation_year).intersection(job.graduation_years)
        ):
            return False
        if (
            query.salary_min is not None
            and job.salary_max is not None
            and job.salary_max < query.salary_min
        ):
            return False
        return not (
            query.salary_max is not None
            and job.salary_min is not None
            and job.salary_min > query.salary_max
        )


def _group_filter_sources(
    pool: Sequence[tuple[JobFact, JobSourceView]],
) -> list[JobFilterSource]:
    grouped: dict[str, set[str]] = {}
    for _, source in pool:
        grouped.setdefault(source.name, set()).add(source.id)
    return [
        JobFilterSource(platform=platform, source_ids=sorted(source_ids))
        for platform, source_ids in sorted(grouped.items())
    ]


def _batch_value(job: JobFact) -> str | None:
    value = job.metadata.get("batch")
    if not isinstance(value, str):
        return None
    batch = value.strip()
    return batch or None


def _batch_values(job: JobFact) -> list[str]:
    return split_batch_values(_batch_value(job))


def _company_group_key(job: JobFact) -> str:
    record_id = job.metadata.get("feishu_record_id")
    if isinstance(record_id, str) and record_id.strip():
        return f"feishu:{record_id.strip()}"
    row_number = job.metadata.get("table_row_number")
    if isinstance(row_number, (int, float)) or (
        isinstance(row_number, str) and row_number.strip().isdigit()
    ):
        return f"row:{job.source_id}:{str(row_number).strip()}"
    return f"job:{job.id}"


def _search_terms(query: str | None) -> list[str]:
    if not query:
        return []
    terms = extract_terms(query)
    return terms or [query.casefold()]


def _haystack(job: JobFact) -> str:
    return " ".join([job.title, job.company_name, *job.locations, job.description or ""]).casefold()


def _preview(description: str | None, limit: int) -> str | None:
    if not description:
        return None
    text = _SPACE_RE.sub(" ", description).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def _to_list_item(
    job: JobFact,
    source: JobSourceView,
    *,
    is_saved: bool | None,
    preview_length: int,
) -> JobListItem:
    return JobListItem(
        id=job.id,
        title=job.title,
        company_name=job.company_name,
        company_nature=job.company_nature,
        locations=job.locations,
        source=source,
        batch=_batch_value(job),
        recruitment_type=_recruitment_enum(job.recruitment_type),
        education_requirement=job.education_requirement,
        graduation_years=job.graduation_years,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_months=job.salary_months,
        description_preview=_preview(job.description, preview_length),
        published_at=job.published_at,
        last_confirmed_at=job.last_confirmed_at,
        is_saved=is_saved,
    )


def _to_detail_view(job: JobFact, source: JobSourceView, *, is_saved: bool | None) -> JobDetailView:
    return JobDetailView(
        id=job.id,
        title=job.title,
        company_name=job.company_name,
        company_nature=job.company_nature,
        locations=job.locations,
        source=source,
        batch=_batch_value(job),
        recruitment_type=_recruitment_enum(job.recruitment_type),
        education_requirement=job.education_requirement,
        graduation_years=job.graduation_years,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_months=job.salary_months,
        description=job.description,
        detail_url=job.detail_url,
        apply_url=job.apply_url,
        status=job.status,
        published_at=job.published_at,
        deadline_at=job.deadline_at,
        first_seen_at=job.first_seen_at,
        last_confirmed_at=job.last_confirmed_at,
        updated_at=job.updated_at,
        is_saved=is_saved,
    )


def _recruitment_enum(value: str | None) -> RecruitmentType | None:
    try:
        return RecruitmentType(value) if value else None
    except ValueError:
        return None


__all__ = ["JobPoolService", "JobPoolStore", "SavedJobStore"]
