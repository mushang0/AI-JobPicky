from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from ...contracts import Page, SavedJobState, SavedJobView
from ..dependencies import JobPoolServiceDependency, RequiredUser

router = APIRouter(prefix="/api/v1/user/saved-jobs", tags=["saved-jobs"])


@router.put("/{job_id}", response_model=SavedJobState)
async def save_job(
    job_id: Annotated[str, Path(min_length=1)],
    user: RequiredUser,
    service: JobPoolServiceDependency,
) -> SavedJobState:
    return await service.set_saved(user.id, job_id, True)


@router.delete("/{job_id}", response_model=SavedJobState)
async def unsave_job(
    job_id: Annotated[str, Path(min_length=1)],
    user: RequiredUser,
    service: JobPoolServiceDependency,
) -> SavedJobState:
    return await service.set_saved(user.id, job_id, False)


@router.get("", response_model=Page[SavedJobView])
async def list_saved_jobs(
    user: RequiredUser,
    service: JobPoolServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> Page[SavedJobView]:
    return await service.list_saved(user.id, page, page_size)


__all__ = ["router"]
