from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from catalog.factories import make_job
from matching.factories import make_profile

from jobpicky.contracts import (
    MatchAssessment,
    RecommendationStep,
    RecommendationTaskStatus,
)
from jobpicky.infrastructure.auth_store import USER_ACCOUNT_TABLE
from jobpicky.infrastructure.credit_store import CREDIT_ACCOUNT_TABLE
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.job_catalog import JOB_TABLE, PostgresJobCatalog
from jobpicky.infrastructure.profile_store import PROFILE_TABLE, PostgresProfileStore
from jobpicky.infrastructure.recommendation_store import RECOMMENDATION_TABLE
from jobpicky.matching import BaselineMatchingService
from jobpicky.orchestration import (
    PostgresRecommendationRunStore,
    RecommendationRunService,
)
from jobpicky.orchestration.store import RUN_TABLE

_TEST_DATABASE_URL = os.environ.get("JOBPICKY_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="JOBPICKY_TEST_DATABASE_URL is not set; start the compose db and run migrations",
)

_JOB_IDS = ("itest-run-job-1", "itest-run-job-2")
_PROFILE_ID = "itest-run-profile-1"
_USER_ID = "itest-run-user-1"


def _seed() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    jobs = [
        make_job(
            id="itest-run-job-1",
            title="后端工程师（校招）",
            company_name="示例科技",
            locations=["上海"],
            description="负责 Python 后端服务开发，使用 PostgreSQL。",
        ),
        make_job(
            id="itest-run-job-2",
            title="算法工程师",
            company_name="北京研究院",
            locations=["北京"],
            description="机器学习模型训练与部署。",
        ),
    ]
    profile = make_profile(id=_PROFILE_ID, user_id=_USER_ID)

    async def insert() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        async with factory() as session:
            await session.execute(sa.delete(JOB_TABLE).where(JOB_TABLE.c.id.in_(_JOB_IDS)))
            await session.execute(
                sa.delete(RECOMMENDATION_TABLE).where(RECOMMENDATION_TABLE.c.user_id == _USER_ID)
            )
            await session.execute(sa.delete(PROFILE_TABLE).where(PROFILE_TABLE.c.id == _PROFILE_ID))
            await session.execute(sa.delete(RUN_TABLE).where(RUN_TABLE.c.user_id == _USER_ID))
            await session.execute(
                sa.delete(CREDIT_ACCOUNT_TABLE).where(CREDIT_ACCOUNT_TABLE.c.user_id == _USER_ID)
            )
            await session.execute(
                sa.delete(USER_ACCOUNT_TABLE).where(USER_ACCOUNT_TABLE.c.id == _USER_ID)
            )
            await session.execute(
                sa.insert(USER_ACCOUNT_TABLE).values(
                    id=_USER_ID,
                    email="itest-recommendation-user@example.com",
                    password_hash="test-only-hash",
                    role="USER",
                    status="ACTIVE",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                sa.insert(CREDIT_ACCOUNT_TABLE).values(
                    user_id=_USER_ID,
                    balance=10_000,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.execute(
                sa.insert(JOB_TABLE),
                [
                    {
                        **job.model_dump(),
                        "status": str(job.status),
                        "published_at": job.published_at or now,
                    }
                    for job in jobs
                ],
            )
            await session.execute(sa.insert(PROFILE_TABLE), [profile.model_dump()])
            await session.commit()
        await engine.dispose()

    asyncio.run(insert())


def _service(run_in_background: bool = True) -> RecommendationRunService:
    engine = create_engine(_TEST_DATABASE_URL)
    factory = create_session_factory(engine)
    matching = BaselineMatchingService()

    class FakeEmbedding:
        dimension = 512

        async def embed_query(self, text: str) -> list[float]:
            return [1.0] + [0.0] * 511

        async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0] + [0.0] * 511 for _ in texts]

    class FakeEvaluator:
        async def evaluate(self, profile, jobs, candidates, effective_extra_request=None):
            return [
                MatchAssessment(
                    job_id=candidate.job_id,
                    matched=True,
                    match_score=90,
                    reason="Relevant experience.",
                    matched_strengths=["Python"],
                    gaps=[],
                )
                for candidate in candidates
            ]

    return RecommendationRunService(
        PostgresRecommendationRunStore(factory),
        PostgresProfileStore(factory),
        PostgresJobCatalog(factory, FakeEmbedding()),
        matching,
        FakeEvaluator(),
        matching.config.version,
        run_in_background=run_in_background,
    )


def test_end_to_end_run_persists_results_snapshot() -> None:
    _seed()

    async def check() -> None:
        service = _service()
        accepted = await service.start(_USER_ID, None, "itest-key-1")
        assert accepted.status == RecommendationTaskStatus.PENDING

        view = await service.get_run(_USER_ID, accepted.run_id)
        for _ in range(100):
            if view.status not in {
                RecommendationTaskStatus.PENDING,
                RecommendationTaskStatus.RUNNING,
            }:
                break
            await asyncio.sleep(0.01)
            view = await service.get_run(_USER_ID, accepted.run_id)
        assert view.status == RecommendationTaskStatus.SUCCEEDED
        assert view.current_step == RecommendationStep.COMPLETE
        assert view.progress_percent == 100
        assert view.credits.refunded is False
        assert view.counts["recommended"] >= 1
        assert view.finished_at is not None

        page = await service.get_results(_USER_ID, accepted.run_id, 1, 10)
        # The database may hold other sample rows; assert on the seeded jobs.
        assert page.total >= 1
        by_id = {item.job.id: item for item in page.items}
        assert "itest-run-job-1" in by_id
        assert "itest-run-job-2" not in by_id
        assert by_id["itest-run-job-1"].job.company_name == "示例科技"
        assert by_id["itest-run-job-1"].assessment.match_score == 90
        assert by_id["itest-run-job-1"].is_deleted is False

        replay = await service.start(_USER_ID, None, "itest-key-1")
        assert replay.run_id == accepted.run_id

    asyncio.run(check())
