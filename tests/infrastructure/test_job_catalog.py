from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from catalog.factories import make_job, make_spec

from jobpicky.contracts import (
    CollectedJob,
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


def test_missing_embedding_dependency_fails_explicitly() -> None:
    _seed()

    async def check() -> None:
        catalog = _catalog()
        with pytest.raises(ApplicationError) as semantic_error:
            await catalog.semantic_search("后端工程师", ["itest-job-1"])
        assert semantic_error.value.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE)

    asyncio.run(check())


def _batch(
    source_id: str,
    *items: CollectedJob,
    complete: bool = False,
) -> CollectionBatch:
    return CollectionBatch(
        source_id=source_id,
        items=list(items),
        complete=complete,
        method="integration-test",
        warnings=[],
    )


def _collected(source_id: str, **overrides: object) -> CollectedJob:
    values: dict[str, object] = {
        "source_id": source_id,
        "source_job_id": "external-1",
        "company_name": "入库测试公司",
        "title": "后端工程师",
        "locations": ["上海"],
        "description": "初版 JD",
        "detail_url": "https://jobs.example.com/detail/1",
        "apply_url": "https://jobs.example.com/apply/1",
        "graduation_years": [2027],
    }
    values.update(overrides)
    return CollectedJob(**values)  # type: ignore[arg-type]


def test_ingest_is_idempotent_updates_and_protects_history() -> None:
    source_id = "itest-ingest-source"
    other_source_id = "itest-ingest-other"

    async def check() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        catalog = PostgresJobCatalog(factory)
        async with factory() as session:
            await session.execute(
                sa.delete(JOB_TABLE).where(JOB_TABLE.c.source_id.in_([source_id, other_source_id]))
            )
            await session.commit()

        original = _collected(
            source_id,
            metadata={"collection_mode": "TABLE_FALLBACK", "quality_reasons": ["PARSER_FAILED"]},
        )
        first = await catalog.ingest("ingest-run-1", _batch(source_id, original, complete=True))
        assert (first.created_count, first.updated_count, first.unchanged_count) == (1, 0, 0)
        assert first.closed_count == 0
        assert first.close_skipped is True
        assert first.complete_accepted is False
        assert "pagination completeness" in first.warnings[-1]
        job_id = first.job_ids[0]

        async with factory() as session:
            first_row = (
                (await session.execute(sa.select(JOB_TABLE).where(JOB_TABLE.c.id == job_id)))
                .mappings()
                .one()
            )
        assert first_row.status == "OPEN"
        assert first_row.source_job_id == "external-1"
        assert first_row.metadata == {
            "collection_mode": "TABLE_FALLBACK",
            "quality_reasons": ["PARSER_FAILED"],
        }
        assert first_row.fact_version
        assert first_row.first_seen_at.tzinfo is not None

        async with factory() as session:
            await session.execute(
                sa.update(JOB_TABLE)
                .where(JOB_TABLE.c.id == job_id)
                .values(embedding=[1.0] + [0.0] * 511)
            )
            await session.commit()
        await asyncio.sleep(0.001)
        second = await catalog.ingest("ingest-run-2", _batch(source_id, original))
        assert second.job_ids == [job_id]
        assert (second.created_count, second.updated_count, second.unchanged_count) == (0, 0, 1)
        async with factory() as session:
            second_row = (
                (await session.execute(sa.select(JOB_TABLE).where(JOB_TABLE.c.id == job_id)))
                .mappings()
                .one()
            )
        assert second_row.first_seen_at == first_row.first_seen_at
        assert second_row.last_confirmed_at > first_row.last_confirmed_at
        assert second_row.updated_at == first_row.updated_at
        assert second_row.fact_version == first_row.fact_version
        assert second_row.embedding is not None

        changed = original.model_copy(update={"description": "修改后的 JD"})
        third = await catalog.ingest("ingest-run-3", _batch(source_id, changed))
        assert third.job_ids == [job_id]
        assert (third.created_count, third.updated_count, third.unchanged_count) == (0, 1, 0)
        async with factory() as session:
            changed_row = (
                (await session.execute(sa.select(JOB_TABLE).where(JOB_TABLE.c.id == job_id)))
                .mappings()
                .one()
            )
            await session.execute(
                sa.update(JOB_TABLE)
                .where(JOB_TABLE.c.id == job_id)
                .values(status="CLOSED", embedding=[1.0] + [0.0] * 511)
            )
            await session.commit()
        assert changed_row.description == "修改后的 JD"
        assert changed_row.fact_version != first_row.fact_version
        assert changed_row.embedding is None

        reopened = await catalog.ingest("ingest-run-4", _batch(source_id, changed))
        assert reopened.updated_count == 1
        async with factory() as session:
            reopened_row = (
                (await session.execute(sa.select(JOB_TABLE).where(JOB_TABLE.c.id == job_id)))
                .mappings()
                .one()
            )
        assert reopened_row.status == "OPEN"
        assert reopened_row.embedding is not None

        same_external_id = _collected(other_source_id)
        other = await catalog.ingest("ingest-run-5", _batch(other_source_id, same_external_id))
        assert other.created_count == 1
        assert other.job_ids[0] != job_id

        historical = _collected(
            source_id,
            source_job_id="historical",
            title="历史岗位",
            detail_url="https://jobs.example.com/detail/historical",
        )
        historical_result = await catalog.ingest("ingest-run-6", _batch(source_id, historical))
        await catalog.ingest("ingest-run-7", _batch(source_id, changed, complete=False))
        async with factory() as session:
            historical_status = await session.scalar(
                sa.select(JOB_TABLE.c.status).where(JOB_TABLE.c.id == historical_result.job_ids[0])
            )
        assert historical_status == "OPEN"
        await engine.dispose()

    asyncio.run(check())


def test_ingest_identity_fallbacks_and_batch_deduplication() -> None:
    source_id = "itest-ingest-fallback"

    async def check() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        catalog = PostgresJobCatalog(factory)
        async with factory() as session:
            await session.execute(sa.delete(JOB_TABLE).where(JOB_TABLE.c.source_id == source_id))
            await session.commit()

        by_url = _collected(
            source_id,
            source_job_id=None,
            detail_url="https://JOBS.example.com/detail/2/?b=2&a=1#top",
            apply_url=None,
        )
        equivalent_url = by_url.model_copy(
            update={"detail_url": "https://jobs.example.com/detail/2?a=1&b=2"}
        )
        first = await catalog.ingest("fallback-1", _batch(source_id, by_url))
        second = await catalog.ingest("fallback-2", _batch(source_id, equivalent_url))
        assert first.job_ids == second.job_ids
        assert second.updated_count == 1

        by_facts = _collected(
            source_id,
            source_job_id=None,
            detail_url=None,
            apply_url=None,
            company_name=" 示例 公司 ",
            title="数据  工程师",
            locations=["北京", "上海"],
        )
        equivalent_facts = by_facts.model_copy(
            update={
                "company_name": "示例 公司",
                "title": "数据 工程师",
                "locations": ["上海", "北京"],
            }
        )
        facts_first = await catalog.ingest("fallback-3", _batch(source_id, by_facts, by_facts))
        facts_second = await catalog.ingest("fallback-4", _batch(source_id, equivalent_facts))
        assert facts_first.created_count == 1
        assert len(facts_first.job_ids) == 1
        assert facts_first.job_ids == facts_second.job_ids

        conflict = by_facts.model_copy(update={"description": "冲突 JD"})
        with pytest.raises(ApplicationError) as error:
            await catalog.ingest("fallback-5", _batch(source_id, by_facts, conflict))
        assert error.value.code == str(ErrorCode.CONFLICT)
        await engine.dispose()

    asyncio.run(check())
