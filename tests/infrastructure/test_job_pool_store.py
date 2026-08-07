from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from catalog.factories import make_job
from sqlalchemy.dialects import postgresql

from jobpicky.contracts import FilterOptionsLimits, JobListQuery
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.job_catalog import JOB_TABLE
from jobpicky.infrastructure.job_pool_store import PostgresJobPoolStore
from jobpicky.infrastructure.source_store import JOB_SOURCE_TABLE

_TEST_DATABASE_URL = os.environ.get("JOBPICKY_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="JOBPICKY_TEST_DATABASE_URL is not set; start the compose db and run migrations",
)

_IDS = ("jobpool-itest-1", "jobpool-itest-2", "jobpool-itest-3")


def _store() -> PostgresJobPoolStore:
    return PostgresJobPoolStore(create_session_factory(create_engine(_TEST_DATABASE_URL)))


def _seed() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    jobs = [
        make_job(
            id=_IDS[0],
            source_id="source-jobpool-itest",
            company_name="聚合公司",
            title="后端工程师",
            description="Python 服务开发",
            published_at=now.replace(hour=2),
            metadata={"batch": "实习、春招补录", "feishu_record_id": "rec-1"},
        ),
        make_job(
            id=_IDS[1],
            source_id="source-jobpool-itest",
            company_name="聚合公司",
            title="算法工程师",
            description="模型训练",
            published_at=now.replace(hour=1),
            metadata={"batch": "实习、春招补录", "feishu_record_id": "rec-1"},
        ),
        make_job(
            id=_IDS[2],
            source_id="source-jobpool-itest",
            company_name="另一家公司",
            title="产品经理",
            description="产品规划",
            published_at=now.replace(day=2),
            metadata={"batch": "秋招提前批", "feishu_record_id": "rec-2"},
        ),
    ]

    async def insert() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        async with factory() as session:
            await session.execute(sa.delete(JOB_TABLE).where(JOB_TABLE.c.id.in_(_IDS)))
            await session.execute(
                postgresql.insert(JOB_SOURCE_TABLE)
                .values(
                    id="source-jobpool-itest",
                    display_name="飞书招聘",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={"display_name": "飞书招聘", "updated_at": now},
                )
            )
            await session.execute(
                sa.insert(JOB_TABLE),
                [
                    {
                        **job.model_dump(),
                        "status": str(job.status),
                        "batch_tokens": ["实习", "春招补录"]
                        if job.id != _IDS[2]
                        else ["秋招提前批"],
                        "company_group_key": "name:聚合公司"
                        if job.id != _IDS[2]
                        else "name:另一家公司",
                    }
                    for job in jobs
                ],
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(insert())


def test_store_pushes_page_batch_and_company_queries_to_postgres() -> None:
    _seed()

    async def check() -> None:
        store = _store()
        scoped_query = JobListQuery(page_size=1, source_id=["source-jobpool-itest"])
        page_items, total, pool_total = await store.list_page(scoped_query, 120)
        assert [job.id for job, _ in page_items] == [_IDS[2]]
        assert total == 3
        assert pool_total >= 3

        filtered, filtered_total, _ = await store.list_page(
            JobListQuery(batch=["春招补录"], source_id=["source-jobpool-itest"], page_size=10), 120
        )
        assert {job.id for job, _ in filtered} == {_IDS[0], _IDS[1]}
        assert filtered_total == 2

        options = await store.get_filter_options(
            FilterOptionsLimits(
                default_page_size=12, public_page_size_max=30, authenticated_page_size_max=100
            )
        )
        assert {"实习", "春招补录", "秋招提前批"}.issubset(options.batches)

        companies = await store.list_companies(
            JobListQuery(page_size=10, source_id=["source-jobpool-itest"])
        )
        assert companies.total == 2
        grouped_company = next(item for item in companies.items if item.job_count == 2)
        assert grouped_company.job_titles == ["后端工程师", "算法工程师"]
        assert grouped_company.batches == ["实习", "春招补录"]
        assert grouped_company.group_id == "name:聚合公司"

    try:
        asyncio.run(check())
    finally:

        async def cleanup() -> None:
            engine = create_engine(_TEST_DATABASE_URL)
            factory = create_session_factory(engine)
            async with factory() as session:
                await session.execute(sa.delete(JOB_TABLE).where(JOB_TABLE.c.id.in_(_IDS)))
                await session.commit()
            await engine.dispose()

        asyncio.run(cleanup())
