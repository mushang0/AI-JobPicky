from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from ...contracts import JobDetailView, JobFilterOptions, JobListQuery, JobPoolPage
from ..dependencies import JobPoolServiceDependency, OptionalUser

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/filter-options", response_model=JobFilterOptions)
async def filter_options(
    response: Response,
    service: JobPoolServiceDependency,
) -> JobFilterOptions:
    response.headers["Cache-Control"] = "public, max-age=300"
    return await service.get_filter_options()


@router.get("", response_model=JobPoolPage)
async def list_jobs(
    query: Annotated[JobListQuery, Depends()],
    user: OptionalUser,
    service: JobPoolServiceDependency,
) -> JobPoolPage:
    return await service.list_jobs(user.id if user else None, query)


@router.get("/{job_id}", response_model=JobDetailView)
async def get_job(
    job_id: str,
    user: OptionalUser,
    service: JobPoolServiceDependency,
) -> JobDetailView:
    return await service.get_job(user.id if user else None, job_id)


__all__ = ["router"]
