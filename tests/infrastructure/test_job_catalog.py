from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from catalog.factories import make_job, make_spec

from jobpicky.contracts import (
    CollectionBatch,
    ErrorCode,
    FilterReasonCode,
    RetrievalChannel,
)
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.job_catalog import JOB_TABLE, PostgresJobCatalog

_TEST_DATABASE_URL = os.environ.get("JOBPICKY_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="JOBPICKY_TEST_DATABASE_URL is not set; start the compose db and run migrations",
)

_JOB_IDS = ("itest-job-1", "itest-job-2", "itest-job-3", "itest-job-4")


class FixedEmbedding:
    dimension = 512

    async def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 511

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 511 for _ in texts]


def _catalog(
    embedding: FixedEmbedding | None = None,
    *,
    semantic_limit: int = 50,
) -> PostgresJobCatalog:
    engine = create_engine(_TEST_DATABASE_URL)
    return PostgresJobCatalog(
        create_session_factory(engine),
        embedding,
        semantic_limit=semantic_limit,
    )


def _seed() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        make_job(
            id="itest-job-1",
            title="后端工程师（校招）",
            company_name="示例科技",
            locations=["上海"],
            description="负责 Python 后端服务开发，使用 PostgreSQL。",
        ),
        make_job(
            id="itest-job-2",
            title="算法工程师",
            company_name="北京研究院",
            locations=["北京"],
            description="机器学习模型训练与部署。",
        ),
        make_job(
            id="itest-job-3",
            title="后端工程师",
            company_name="已关闭公司",
            locations=["上海"],
            status="CLOSED",
        ),
        make_job(
            id="itest-job-4",
            title="平台工程师",
            company_name="同分公司",
            locations=["上海"],
            description="平台服务开发。",
        ),
    ]
    embeddings = {
        "itest-job-1": [1.0] + [0.0] * 511,
        "itest-job-2": [0.8, 0.6] + [0.0] * 510,
        "itest-job-4": [1.0] + [0.0] * 511,
    }

    async def insert() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        async with factory() as session:
            await session.execute(sa.delete(JOB_TABLE).where(JOB_TABLE.c.id.in_(_JOB_IDS)))
            await session.execute(
                sa.insert(JOB_TABLE),
                [
                    {
                        **job.model_dump(),
                        "status": str(job.status),
                        "published_at": job.published_at or now,
                        "embedding": embeddings.get(job.id),
                    }
                    for job in rows
                ],
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(insert())


def test_get_jobs_maps_rows_and_preserves_order() -> None:
    _seed()

    async def check() -> None:
        jobs = await _catalog().get_jobs(["itest-job-2", "itest-job-1", "missing"])
        assert [job.id for job in jobs] == ["itest-job-2", "itest-job-1"]
        assert jobs[0].company_name == "北京研究院"
        assert jobs[0].locations == ["北京"]
        assert jobs[0].graduation_years == [2027]

    asyncio.run(check())


def test_hard_filter_partitions_real_rows() -> None:
    _seed()
    spec = make_spec(target_locations=["上海"])

    async def check() -> None:
        result = await _catalog().hard_filter(spec)
        # The database may hold other sample rows; assert on the seeded jobs.
        assert "itest-job-1" in result.eligible_job_ids
        assert not {"itest-job-2", "itest-job-3"} & set(result.eligible_job_ids)
        reasons = {item.job_id: item.reason_code for item in result.excluded}
        assert reasons["itest-job-2"] == FilterReasonCode.LOCATION_MISMATCH
        assert reasons["itest-job-3"] == FilterReasonCode.JOB_NOT_OPEN

    asyncio.run(check())


def test_keyword_search_ranks_hits_within_eligible_set() -> None:
    _seed()

    async def check() -> None:
        hits = await _catalog().keyword_search(
            "后端工程师\nPython\n机器学习",
            ["itest-job-1", "itest-job-2"],
        )
        assert [hit.job_id for hit in hits] == ["itest-job-1", "itest-job-2"]
        assert hits[0].score == 2 / 3
        assert hits[1].score == 1 / 3
        assert all(hit.channel == RetrievalChannel.KEYWORD for hit in hits)

    asyncio.run(check())


def test_keyword_search_empty_terms_returns_no_hits() -> None:
    _seed()

    async def check() -> None:
        assert await _catalog().keyword_search("  ", ["itest-job-1"]) == []
        assert await _catalog().keyword_search("后端工程师", []) == []

    asyncio.run(check())


def test_semantic_search_uses_pgvector_distance_and_constraints() -> None:
    _seed()

    async def check() -> None:
        hits = await _catalog(FixedEmbedding(), semantic_limit=2).semantic_search(
            "后端工程师",
            ["itest-job-3", "itest-job-4", "itest-job-2", "itest-job-1"],
        )
        assert [hit.job_id for hit in hits] == ["itest-job-1", "itest-job-4"]
        assert hits[0].score == pytest.approx(1.0)
        assert hits[1].score == pytest.approx(1.0)
        assert all(hit.channel == RetrievalChannel.SEMANTIC for hit in hits)

        restricted = await _catalog(FixedEmbedding()).semantic_search(
            "后端工程师",
            ["itest-job-2", "itest-job-3"],
        )
        assert [hit.job_id for hit in restricted] == ["itest-job-2"]
        assert restricted[0].score == pytest.approx(0.8)

    asyncio.run(check())


def test_unimplemented_methods_fail_explicitly() -> None:
    _seed()

    async def check() -> None:
        catalog = _catalog()
        with pytest.raises(ApplicationError) as semantic_error:
            await catalog.semantic_search("后端工程师", ["itest-job-1"])
        assert semantic_error.value.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE)

        batch = CollectionBatch(
            source_id="source-1",
            items=[],
            complete=True,
            method="test",
            warnings=[],
        )
        with pytest.raises(ApplicationError) as ingest_error:
            await catalog.ingest("run-1", batch)
        assert ingest_error.value.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE)

    asyncio.run(check())
