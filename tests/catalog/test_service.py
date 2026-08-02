from __future__ import annotations

import asyncio
from collections.abc import Sequence

from catalog.factories import make_job
from jobpicky.catalog.service import JobPoolService
from jobpicky.config import Settings
from jobpicky.contracts import JobFact, JobFilterSource, JobSourceView
from jobpicky.infrastructure.saved_job_store import SavedJobRecord


class _VisibleJobStore:
    def __init__(self, pool: list[tuple[JobFact, JobSourceView]]) -> None:
        self.pool = pool

    async def list_visible(self, limit: int) -> list[tuple[JobFact, JobSourceView]]:
        return self.pool[:limit]

    async def get_job(self, job_id: str) -> tuple[JobFact, JobSourceView] | None:
        return next(((job, source) for job, source in self.pool if job.id == job_id), None)


class _UnusedSavedJobStore:
    async def set_saved(self, user_id: str, job_id: str, is_saved: bool) -> None:
        return None

    async def get_saved_ids(self, user_id: str, job_ids: Sequence[str]) -> set[str]:
        return set()

    async def list_saved(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[SavedJobRecord], int]:
        return [], 0


def test_filter_options_group_sources_by_platform() -> None:
    pool = [
        (
            make_job(id="job-beisen-1", source_id="beisen-a"),
            JobSourceView(id="beisen-a", name="北森"),
        ),
        (
            make_job(id="job-beisen-2", source_id="beisen-b"),
            JobSourceView(id="beisen-b", name="北森"),
        ),
        (
            make_job(id="job-moka-1", source_id="moka-a"),
            JobSourceView(id="moka-a", name="Moka"),
        ),
        (
            make_job(id="job-moka-2", source_id="moka-b"),
            JobSourceView(id="moka-b", name="Moka"),
        ),
    ]
    service = JobPoolService(
        _VisibleJobStore(pool), _UnusedSavedJobStore(), Settings(environment="test")
    )

    options = asyncio.run(service.get_filter_options())

    assert options.sources == [
        JobFilterSource(platform="Moka", source_ids=["moka-a", "moka-b"]),
        JobFilterSource(platform="北森", source_ids=["beisen-a", "beisen-b"]),
    ]
