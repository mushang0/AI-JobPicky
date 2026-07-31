from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from catalog.factories import make_job
from matching.factories import make_profile

from jobpicky.contracts import (
    Candidate,
    CollectionBatch,
    ErrorCode,
    Feedback,
    FilterResult,
    HardFilterSpec,
    IngestionResult,
    JobFact,
    MatchAssessment,
    ProfileSnapshot,
    RecommendationRunInput,
    RecommendationSort,
    RecommendationTaskStatus,
    RetrievalChannel,
    SearchHit,
)
from jobpicky.errors import ApplicationError
from jobpicky.matching import BaselineMatchingService
from jobpicky.orchestration import (
    CreateRunResult,
    RecommendationProjection,
    RecommendationRecord,
    RecommendationRunService,
    RunRecord,
    assemble_candidates,
    plan_run_input,
)

T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class InMemoryRunStore:
    def __init__(self) -> None:
        self.records: dict[str, RunRecord] = {}
        self.recommendations: dict[str, RecommendationRecord] = {}
        self.balance = 10_000
        self.charge_count = 0
        self.refund_count = 0
        self.progress: list[tuple[str, int]] = []
        self.saved_job_ids: set[str] = set()

    async def find_by_idempotency(self, user_id: str, key: str) -> RunRecord | None:
        return next(
            (
                record
                for record in self.records.values()
                if record.user_id == user_id and record.idempotency_key == key
            ),
            None,
        )

    async def create_charged_run(self, record: RunRecord) -> CreateRunResult:
        existing = await self.find_by_idempotency(
            record.user_id,
            record.idempotency_key or "",
        )
        if existing is not None:
            return CreateRunResult(existing, False)
        active = next(
            (
                item
                for item in self.records.values()
                if item.user_id == record.user_id
                and item.status
                in {RecommendationTaskStatus.PENDING, RecommendationTaskStatus.RUNNING}
            ),
            None,
        )
        if active is not None:
            raise ApplicationError(ErrorCode.CONFLICT, "active run", status_code=409)
        if self.balance < record.credit_cost:
            raise ApplicationError(
                ErrorCode.INSUFFICIENT_CREDITS,
                "insufficient credits",
                status_code=409,
            )
        self.balance -= record.credit_cost
        self.charge_count += 1
        charged = replace(record, balance_after_charge=self.balance)
        self.records[record.run_id] = charged
        return CreateRunResult(charged, True)

    async def save_progress(self, record: RunRecord) -> None:
        self.records[record.run_id] = record
        self.progress.append((str(record.current_step), record.progress_percent))

    async def complete_run(
        self,
        record: RunRecord,
        recommendations: list[RecommendationRecord],
    ) -> None:
        self.records[record.run_id] = record
        self.recommendations.update({item.recommendation_id: item for item in recommendations})

    async def fail_and_refund(
        self,
        user_id: str,
        run_id: str,
        error,
        finished_at: datetime,
    ) -> None:
        record = self.records[run_id]
        if record.credit_refunded or record.status == RecommendationTaskStatus.SUCCEEDED:
            return
        self.balance += record.credit_cost
        self.refund_count += 1
        self.records[run_id] = replace(
            record,
            status=RecommendationTaskStatus.FAILED,
            finished_at=finished_at,
            error=error,
            credit_refunded=True,
        )

    async def get(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)

    async def list_by_user(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RunRecord], int]:
        owned = [record for record in self.records.values() if record.user_id == user_id]
        owned.sort(key=lambda record: (-record.created_at.timestamp(), record.run_id))
        start = (page - 1) * page_size
        return owned[start : start + page_size], len(owned)

    async def successful_job_ids(self, user_id: str) -> set[str]:
        return {item.job_id for item in self.recommendations.values() if item.user_id == user_id}

    async def list_recommendations(
        self,
        user_id: str,
        page: int,
        page_size: int,
        sort: RecommendationSort,
    ) -> tuple[list[RecommendationProjection], int]:
        items = [
            item
            for item in self.recommendations.values()
            if item.user_id == user_id and item.deleted_at is None
        ]
        if sort == RecommendationSort.MATCH_SCORE_DESC:
            items.sort(key=lambda item: (-item.assessment.match_score, item.recommendation_id))
        else:
            items.sort(key=lambda item: (-item.recommended_at.timestamp(), item.recommendation_id))
        start = (page - 1) * page_size
        return [self._projection(item) for item in items[start : start + page_size]], len(items)

    async def list_run_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RecommendationProjection], int]:
        items = [
            item
            for item in self.recommendations.values()
            if item.user_id == user_id and item.run_id == run_id
        ]
        items.sort(key=lambda item: (item.position, item.recommendation_id))
        start = (page - 1) * page_size
        return [self._projection(item) for item in items[start : start + page_size]], len(items)

    async def set_feedback(
        self,
        user_id: str,
        recommendation_id: str,
        feedback: Feedback | None,
    ) -> bool:
        item = self.recommendations.get(recommendation_id)
        if item is None or item.user_id != user_id:
            return False
        self.recommendations[recommendation_id] = replace(item, feedback=feedback)
        return True

    async def soft_delete(
        self,
        user_id: str,
        recommendation_id: str,
        deleted_at: datetime,
    ) -> bool:
        item = self.recommendations.get(recommendation_id)
        if item is None or item.user_id != user_id:
            return False
        self.recommendations[recommendation_id] = replace(
            item,
            deleted_at=item.deleted_at or deleted_at,
        )
        return True

    def _projection(self, item: RecommendationRecord) -> RecommendationProjection:
        return RecommendationProjection(item, item.job_id in self.saved_job_ids)


class FakeProfileReader:
    def __init__(self, *profiles: ProfileSnapshot) -> None:
        self.profiles = list(profiles)
        self.current_calls = 0

    async def get_snapshot(self, user_id: str, profile_id: str) -> ProfileSnapshot:
        return next(
            profile
            for profile in self.profiles
            if profile.user_id == user_id and profile.id == profile_id
        )

    async def get_current(self, user_id: str) -> ProfileSnapshot:
        self.current_calls += 1
        owned = [profile for profile in self.profiles if profile.user_id == user_id]
        if not owned:
            raise ApplicationError(
                ErrorCode.PROFILE_NOT_FOUND,
                "profile not found",
                status_code=404,
            )
        return max(owned, key=lambda profile: profile.version)


class FakeCatalog:
    def __init__(
        self,
        jobs: Sequence[JobFact] = (),
        eligible_job_ids: Sequence[str] | None = None,
        hits: Sequence[SearchHit] = (),
        semantic_hits: Sequence[SearchHit] = (),
        error: Exception | None = None,
    ) -> None:
        self.jobs = {job.id: job for job in jobs}
        self.eligible = list(eligible_job_ids) if eligible_job_ids is not None else list(self.jobs)
        self.hits = list(hits)
        self.semantic_hits = list(semantic_hits)
        self.error = error

    async def ingest(self, run_id: str, batch: CollectionBatch) -> IngestionResult:
        raise NotImplementedError

    async def get_jobs(self, job_ids: Sequence[str]) -> list[JobFact]:
        return [self.jobs[job_id] for job_id in job_ids if job_id in self.jobs]

    async def hard_filter(self, spec: HardFilterSpec) -> FilterResult:
        if self.error is not None:
            raise self.error
        return FilterResult(eligible_job_ids=self.eligible, excluded=[])

    async def keyword_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        eligible = set(eligible_job_ids)
        return [hit for hit in self.hits if hit.job_id in eligible]

    async def semantic_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        eligible = set(eligible_job_ids)
        return [hit for hit in self.semantic_hits if hit.job_id in eligible]


class FakeEvaluator:
    def __init__(self, *, matched: bool = True, score: int = 88) -> None:
        self.matched = matched
        self.score = score
        self.evaluated_job_ids: list[str] = []

    async def evaluate(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        effective_extra_request: str | None = None,
    ) -> list[MatchAssessment]:
        self.evaluated_job_ids.extend(candidate.job_id for candidate in candidates)
        return [
            MatchAssessment(
                job_id=candidate.job_id,
                matched=self.matched,
                match_score=self.score,
                reason="岗位与画像匹配。",
                matched_strengths=["具有相关经验"],
                gaps=[],
                evidence=["画像技能与岗位要求一致"],
            )
            for candidate in candidates
        ]


def make_service(
    *,
    profiles: Sequence[ProfileSnapshot] = (),
    profile_reader: FakeProfileReader | None = None,
    catalog: FakeCatalog | None = None,
    store: InMemoryRunStore | None = None,
    evaluator: FakeEvaluator | None = None,
    evaluation_batch_size: int = 10,
    candidate_limit: int = 50,
    run_in_background: bool = False,
) -> RecommendationRunService:
    return RecommendationRunService(
        store or InMemoryRunStore(),
        profile_reader or FakeProfileReader(*(profiles or [make_profile()])),
        catalog or FakeCatalog(),
        BaselineMatchingService(),
        evaluator or FakeEvaluator(),
        "recommendation-v1",
        recommendation_cost=100,
        candidate_limit=candidate_limit,
        evaluation_batch_size=evaluation_batch_size,
        run_in_background=run_in_background,
    )


def _hit(job_id: str, score: float = 0.8) -> SearchHit:
    return SearchHit(job_id=job_id, score=score, channel=RetrievalChannel.KEYWORD)


def _historical_recommendation(
    job: JobFact,
    *,
    deleted: bool = False,
) -> RecommendationRecord:
    return RecommendationRecord(
        recommendation_id=f"rec-{job.id}",
        user_id="user-1",
        run_id="old-run",
        job_id=job.id,
        position=1,
        job_snapshot=job,
        assessment=MatchAssessment(
            job_id=job.id,
            matched=True,
            match_score=80,
            reason="历史推荐",
            matched_strengths=[],
            gaps=[],
        ),
        recommended_at=datetime(2026, 1, 1, tzinfo=UTC),
        deleted_at=datetime(2026, 1, 2, tzinfo=UTC) if deleted else None,
    )


def test_plan_run_input_freezes_latest_profile_and_merged_request() -> None:
    profile = make_profile(version=3, extra_request="想远程")
    assert plan_run_input(profile, "只要外企") == RecommendationRunInput(
        profile_id=profile.id,
        profile_version=3,
        effective_extra_request="想远程\n\n只要外企",
    )


def test_assemble_candidates_keeps_order_and_skips_missing_jobs() -> None:
    jobs = [make_job(id="job-1"), make_job(id="job-2", title="算法工程师")]
    candidates = [
        Candidate(job_id="job-2", retrieval_score=0.9, sources=[RetrievalChannel.KEYWORD]),
        Candidate(job_id="gone", retrieval_score=0.7, sources=[RetrievalChannel.KEYWORD]),
        Candidate(job_id="job-1", retrieval_score=0.5, sources=[RetrievalChannel.KEYWORD]),
    ]
    assert [item.job.id for item in assemble_candidates(candidates, jobs)] == [
        "job-2",
        "job-1",
    ]


def test_start_uses_current_profile_charges_once_and_reports_real_progress() -> None:
    old = make_profile(id="profile-1", version=1)
    current = make_profile(id="profile-1", version=2, extra_request="画像要求")
    reader = FakeProfileReader(old, current)
    store = InMemoryRunStore()
    service = make_service(store=store, profile_reader=reader)

    accepted = run(service.start("user-1", "本次要求", "key-1"))
    record = store.records[accepted.run_id]

    assert accepted.status == RecommendationTaskStatus.SUCCEEDED
    assert accepted.credits_charged == 100
    assert accepted.balance_after == 9900
    assert record.recommendation_input.profile_version == 2
    assert record.recommendation_input.effective_extra_request == "画像要求\n\n本次要求"
    assert record.progress_percent == 100
    assert ("PROFILE", 10) in store.progress
    assert ("SAVE", 95) in store.progress
    assert store.charge_count == 1


def test_idempotent_replay_does_not_rebind_profile_or_charge_again() -> None:
    reader = FakeProfileReader(make_profile(version=1))
    store = InMemoryRunStore()
    service = make_service(store=store, profile_reader=reader)
    first = run(service.start("user-1", None, "key-1"))
    reader.profiles.append(make_profile(version=2))
    second = run(service.start("user-1", None, "key-1"))

    assert second.run_id == first.run_id
    assert reader.current_calls == 1
    assert store.charge_count == 1
    assert store.records[first.run_id].recommendation_input.profile_version == 1


def test_same_idempotency_key_with_different_request_conflicts() -> None:
    service = make_service()
    run(service.start("user-1", "只要外企", "key-1"))
    with pytest.raises(ApplicationError) as error:
        run(service.start("user-1", "只要国企", "key-1"))
    assert error.value.code == str(ErrorCode.IDEMPOTENCY_CONFLICT)


def test_missing_profile_and_insufficient_balance_create_no_run_or_charge() -> None:
    no_profile_store = InMemoryRunStore()
    no_profile = make_service(
        store=no_profile_store,
        profile_reader=FakeProfileReader(),
    )
    with pytest.raises(ApplicationError) as profile_error:
        run(no_profile.start("user-1", None, "key-1"))
    assert profile_error.value.code == str(ErrorCode.PROFILE_NOT_FOUND)
    assert no_profile_store.records == {}

    poor_store = InMemoryRunStore()
    poor_store.balance = 99
    with pytest.raises(ApplicationError) as credit_error:
        run(make_service(store=poor_store).start("user-1", None, "key-1"))
    assert credit_error.value.code == str(ErrorCode.INSUFFICIENT_CREDITS)
    assert poor_store.records == {}
    assert poor_store.charge_count == 0


def test_existing_active_run_blocks_a_different_request() -> None:
    store = InMemoryRunStore()
    store.records["active"] = RunRecord(
        run_id="active",
        user_id="user-1",
        status=RecommendationTaskStatus.RUNNING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        recommendation_input=RecommendationRunInput(profile_id="p", profile_version=1),
        model_config_version="v1",
        idempotency_key="old-key",
        request_fingerprint="old",
        credit_cost=100,
        balance_after_charge=9900,
    )
    with pytest.raises(ApplicationError) as error:
        run(make_service(store=store).start("user-1", None, "new-key"))
    assert error.value.code == str(ErrorCode.CONFLICT)
    assert store.charge_count == 0


def test_deleted_historical_success_is_permanently_skipped() -> None:
    old_job = make_job(id="job-1")
    new_job = make_job(id="job-2", title="平台工程师")
    store = InMemoryRunStore()
    historical = _historical_recommendation(old_job, deleted=True)
    store.recommendations[historical.recommendation_id] = historical
    evaluator = FakeEvaluator()
    catalog = FakeCatalog(jobs=[old_job, new_job], hits=[_hit("job-1"), _hit("job-2")])

    run(
        make_service(store=store, catalog=catalog, evaluator=evaluator).start(
            "user-1", None, "key-1"
        )
    )

    assert evaluator.evaluated_job_ids == ["job-2"]
    assert {item.job_id for item in store.recommendations.values()} == {"job-1", "job-2"}


def test_matched_false_can_be_retried_and_matched_true_has_no_score_threshold() -> None:
    job = make_job()
    catalog = FakeCatalog(jobs=[job], hits=[_hit(job.id)])
    store = InMemoryRunStore()
    false_evaluator = FakeEvaluator(matched=False, score=99)
    first = run(
        make_service(store=store, catalog=catalog, evaluator=false_evaluator).start(
            "user-1", None, "key-1"
        )
    )
    assert store.records[first.run_id].counts == {"evaluated": 1, "recommended": 0}
    assert store.recommendations == {}

    true_evaluator = FakeEvaluator(matched=True, score=0)
    second = run(
        make_service(store=store, catalog=catalog, evaluator=true_evaluator).start(
            "user-1", None, "key-2"
        )
    )
    assert store.records[second.run_id].counts == {"evaluated": 1, "recommended": 1}
    assert next(iter(store.recommendations.values())).assessment.match_score == 0


def test_candidate_and_result_count_never_exceeds_fifty() -> None:
    jobs = [make_job(id=f"job-{index}", title=f"岗位 {index}") for index in range(60)]
    evaluator = FakeEvaluator()
    catalog = FakeCatalog(jobs=jobs, hits=[_hit(job.id) for job in jobs])
    store = InMemoryRunStore()
    accepted = run(
        make_service(store=store, catalog=catalog, evaluator=evaluator).start(
            "user-1", None, "key-1"
        )
    )
    assert len(evaluator.evaluated_job_ids) == 50
    assert store.records[accepted.run_id].counts["recommended"] == 50
    assert len(store.recommendations) == 50


def test_system_failure_refunds_once_and_persists_actual_progress() -> None:
    store = InMemoryRunStore()
    catalog = FakeCatalog(
        error=ApplicationError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "database detail",
            status_code=503,
            details={"stage": "FILTER"},
        )
    )
    accepted = run(make_service(store=store, catalog=catalog).start("user-1", None, "key-1"))
    record = store.records[accepted.run_id]

    assert record.status == RecommendationTaskStatus.FAILED
    assert record.progress_percent == 25
    assert record.credit_refunded
    assert record.error is not None
    assert record.error.message == "依赖服务暂时不可用，请稍后重试。"
    assert store.balance == 10_000
    assert store.refund_count == 1

    run(
        store.fail_and_refund(
            "user-1",
            accepted.run_id,
            record.error,
            datetime.now(UTC),
        )
    )
    assert store.balance == 10_000
    assert store.refund_count == 1


def test_successful_empty_run_remains_charged() -> None:
    store = InMemoryRunStore()
    accepted = run(
        make_service(store=store, catalog=FakeCatalog(eligible_job_ids=[])).start(
            "user-1", None, "key-1"
        )
    )
    record = store.records[accepted.run_id]
    assert record.status == RecommendationTaskStatus.SUCCEEDED
    assert record.counts == {"evaluated": 0, "recommended": 0}
    assert store.balance == 9900
    assert store.refund_count == 0


def test_feedback_delete_and_saved_state_are_real_and_user_scoped() -> None:
    job = make_job()
    store = InMemoryRunStore()
    store.saved_job_ids.add(job.id)
    catalog = FakeCatalog(jobs=[job], hits=[_hit(job.id)])
    service = make_service(store=store, catalog=catalog)
    accepted = run(service.start("user-1", None, "key-1"))

    all_items = run(
        service.list_recommendations("user-1", 1, 10, RecommendationSort.RECOMMENDED_AT_DESC)
    )
    assert all_items.total == 1
    card = all_items.items[0]
    assert card.is_saved
    assert card.job.id == job.id
    assert not hasattr(card, "retrieval")

    feedback = run(service.update_feedback("user-1", card.recommendation_id, Feedback.LIKE))
    assert feedback.feedback == Feedback.LIKE
    run(service.delete_recommendation("user-1", card.recommendation_id))
    run(service.delete_recommendation("user-1", card.recommendation_id))
    assert (
        run(
            service.list_recommendations("user-1", 1, 10, RecommendationSort.RECOMMENDED_AT_DESC)
        ).total
        == 0
    )

    history = run(service.get_results("user-1", accepted.run_id, 1, 10))
    assert history.total == 1
    assert history.items[0].is_deleted
    assert history.items[0].feedback == Feedback.LIKE
    assert job.id in run(store.successful_job_ids("user-1"))

    with pytest.raises(ApplicationError) as error:
        run(service.update_feedback("other-user", card.recommendation_id, Feedback.LIKE))
    assert error.value.code == str(ErrorCode.NOT_FOUND)
