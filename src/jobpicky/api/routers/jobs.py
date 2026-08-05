from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from ...contracts import (
    CompanyPoolPage,
    EducationLevel,
    JobDetailView,
    JobFilterOptions,
    JobListQuery,
    JobPoolPage,
    RecruitmentType,
)
from ...contracts.common import NonEmptyStr, NonNegativeInt
from ..dependencies import JobPoolServiceDependency, OptionalUser

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def job_list_query(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
    q: Annotated[str | None, Query(max_length=200)] = None,
    city: Annotated[list[NonEmptyStr] | None, Query(max_length=50)] = None,
    company_nature: Annotated[list[NonEmptyStr] | None, Query(max_length=50)] = None,
    source_id: Annotated[list[NonEmptyStr] | None, Query(max_length=50)] = None,
    batch: Annotated[list[NonEmptyStr] | None, Query(max_length=50)] = None,
    recruitment_type: Annotated[list[RecruitmentType] | None, Query(max_length=50)] = None,
    education: Annotated[list[EducationLevel] | None, Query(max_length=50)] = None,
    graduation_year: Annotated[list[int] | None, Query(max_length=50)] = None,
    salary_min: Annotated[NonNegativeInt | None, Query()] = None,
    salary_max: Annotated[NonNegativeInt | None, Query()] = None,
    published_within_days: Annotated[int | None, Query(ge=1, le=3650)] = None,
    published_at_unknown: Annotated[bool, Query()] = False,
    company_group_id: Annotated[NonEmptyStr | None, Query(max_length=200)] = None,
) -> JobListQuery:
    return JobListQuery(
        page=page,
        page_size=page_size,
        q=q,
        city=city or [],
        company_nature=company_nature or [],
        source_id=source_id or [],
        batch=batch or [],
        recruitment_type=recruitment_type or [],
        education=education or [],
        graduation_year=graduation_year or [],
        salary_min=salary_min,
        salary_max=salary_max,
        published_within_days=published_within_days,
        published_at_unknown=published_at_unknown,
        company_group_id=company_group_id,
    )


@router.get("/filter-options", response_model=JobFilterOptions)
async def filter_options(
    response: Response,
    service: JobPoolServiceDependency,
) -> JobFilterOptions:
    response.headers["Cache-Control"] = "public, max-age=300"
    return await service.get_filter_options()


@router.get("", response_model=JobPoolPage)
async def list_jobs(
    query: Annotated[JobListQuery, Depends(job_list_query)],
    user: OptionalUser,
    service: JobPoolServiceDependency,
) -> JobPoolPage:
    return await service.list_jobs(user.id if user else None, query)


@router.get("/companies", response_model=CompanyPoolPage)
async def list_companies(
    query: Annotated[JobListQuery, Depends(job_list_query)],
    user: OptionalUser,
    service: JobPoolServiceDependency,
) -> CompanyPoolPage:
    return await service.list_companies(user.id if user else None, query)


@router.get("/{job_id}", response_model=JobDetailView)
async def get_job(
    job_id: str,
    user: OptionalUser,
    service: JobPoolServiceDependency,
) -> JobDetailView:
    return await service.get_job(user.id if user else None, job_id)


__all__ = ["router"]
