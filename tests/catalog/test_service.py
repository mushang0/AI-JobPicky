from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from catalog.factories import make_job
from jobpicky.catalog.service import JobPoolService
from jobpicky.config import Settings
from jobpicky.contracts import JobFact, JobFilterSource, JobListQuery, JobSourceView
from jobpicky.infrastructure.saved_job_store import SavedJobRecord


class _VisibleJobStore:
    def __init__(self, pool: list[tuple[JobFact, JobSourceView]]) -> None:
        self.pool = pool

    async def list_visible(self) -> list[tuple[JobFact, JobSourceView]]:
        return self.pool

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


def test_batch_is_exposed_and_filters_raw_batch_without_using_recruitment_type() -> None:
    pool = [
        (
            make_job(
                id="job-early-campus",
                recruitment_type="校招",
                metadata={"batch": "秋招提前批"},
            ),
            JobSourceView(id="source-1", name="飞书招聘"),
        ),
        (
            make_job(
                id="job-summer-intern",
                recruitment_type="实习",
                metadata={"batch": "暑期实习"},
            ),
            JobSourceView(id="source-1", name="飞书招聘"),
        ),
        (
            make_job(id="job-unknown-batch", recruitment_type="社招"),
            JobSourceView(id="source-1", name="Moka"),
        ),
    ]
    service = JobPoolService(
        _VisibleJobStore(pool), _UnusedSavedJobStore(), Settings(environment="test")
    )

    options = asyncio.run(service.get_filter_options())
    filtered = asyncio.run(service.list_jobs("user-1", JobListQuery(batch=["秋招提前批"])))

    assert options.batches == ["暑期实习", "秋招提前批"]
    assert [item.id for item in filtered.items] == ["job-early-campus", "job-unknown-batch"]
    assert filtered.items[0].batch == "秋招提前批"


def test_batch_filter_matches_any_token_in_a_mixed_batch() -> None:
    pool = [
        (
            make_job(id="mixed", metadata={"batch": "实习、春招补录、实习"}),
            JobSourceView(id="source-1", name="飞书招聘"),
        ),
        (
            make_job(id="other", metadata={"batch": "秋招提前批"}),
            JobSourceView(id="source-1", name="飞书招聘"),
        ),
    ]
    service = JobPoolService(
        _VisibleJobStore(pool), _UnusedSavedJobStore(), Settings(environment="test")
    )

    options = asyncio.run(service.get_filter_options())
    filtered = asyncio.run(service.list_jobs("user-1", JobListQuery(batch=["春招补录"])))

    assert options.batches == ["实习", "春招补录", "秋招提前批"]
    assert [item.id for item in filtered.items] == ["mixed"]


def test_company_view_groups_jobs_by_feishu_record() -> None:
    pool = [
        (
            make_job(
                id="job-1",
                company_name="同一公司",
                published_at=datetime.now(UTC),
                metadata={"batch": "秋招", "feishu_record_id": "rec-1"},
            ),
            JobSourceView(id="source-1", name="飞书招聘"),
        ),
        (
            make_job(
                id="job-2",
                company_name="同一公司",
                metadata={"batch": "实习", "feishu_record_id": "rec-1"},
            ),
            JobSourceView(id="source-1", name="飞书招聘"),
        ),
        (
            make_job(
                id="job-3",
                company_name="同一公司",
                metadata={"batch": "秋招", "feishu_record_id": "rec-2"},
            ),
            JobSourceView(id="source-1", name="飞书招聘"),
        ),
    ]
    service = JobPoolService(
        _VisibleJobStore(pool), _UnusedSavedJobStore(), Settings(environment="test")
    )

    page = asyncio.run(service.list_companies("user-1", JobListQuery(page_size=10)))

    assert page.total == 2
    assert page.pool_total == 2
    assert page.items[0].job_count == 2
    assert page.items[0].job_titles == ["后端工程师", "后端工程师"]


def test_published_date_filters_use_published_at_and_keep_unknown_separate() -> None:
    now = datetime.now(UTC)
    pool = [
        (
            make_job(id="recent", published_at=now - timedelta(days=2)),
            JobSourceView(id="a", name="平台"),
        ),
        (
            make_job(id="old", published_at=now - timedelta(days=10)),
            JobSourceView(id="b", name="平台"),
        ),
        (make_job(id="unknown", published_at=None), JobSourceView(id="c", name="平台")),
    ]
    service = JobPoolService(
        _VisibleJobStore(pool), _UnusedSavedJobStore(), Settings(environment="test")
    )

    recent = asyncio.run(service.list_jobs("user-1", JobListQuery(published_within_days=3)))
    unknown = asyncio.run(service.list_jobs("user-1", JobListQuery(published_at_unknown=True)))

    assert [item.id for item in recent.items] == ["recent"]
    assert [item.id for item in unknown.items] == ["unknown"]


def test_job_pool_uses_all_jobs_and_sorts_by_published_at() -> None:
    now = datetime.now(UTC)
    pool = [
        (
            make_job(
                id="older",
                published_at=now - timedelta(days=2),
                last_confirmed_at=now,
            ),
            JobSourceView(id="a", name="平台"),
        ),
        (
            make_job(
                id="newer",
                published_at=now - timedelta(days=1),
                last_confirmed_at=now - timedelta(days=1),
            ),
            JobSourceView(id="b", name="平台"),
        ),
        (
            make_job(id="unknown", published_at=None, last_confirmed_at=now),
            JobSourceView(id="c", name="平台"),
        ),
    ]
    service = JobPoolService(
        _VisibleJobStore(pool), _UnusedSavedJobStore(), Settings(environment="test")
    )

    page = asyncio.run(service.list_jobs("user-1", JobListQuery(page_size=1)))

    assert [item.id for item in page.items] == ["newer"]
    assert page.pool_total == 3


def test_job_pool_is_not_capped_at_five_thousand_jobs() -> None:
    now = datetime.now(UTC)
    pool = [
        (
            make_job(
                id=f"job-{index}",
                published_at=now - timedelta(minutes=index),
            ),
            JobSourceView(id="source-1", name="平台"),
        )
        for index in range(5001)
    ]
    service = JobPoolService(
        _VisibleJobStore(pool), _UnusedSavedJobStore(), Settings(environment="test")
    )

    page = asyncio.run(service.list_jobs("user-1", JobListQuery(page_size=1)))

    assert page.pool_total == 5001
    assert page.total == 5001
    assert page.items[0].id == "job-0"
