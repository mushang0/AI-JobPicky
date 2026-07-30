from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from catalog.factories import make_job
from matching.factories import make_profile

from jobpicky.contracts import (
    Candidate,
    CollectionBatch,
    ErrorCode,
    FilterResult,
    HardFilterSpec,
    IngestionResult,
    JobFact,
    MatchAssessment,
    ProfileSnapshot,
    RecommendationRunInput,
    RetrievalChannel,
    RunStatus,
    SearchHit,
)
from jobpicky.errors import ApplicationError
from jobpicky.matching import BaselineMatchingService
from jobpicky.orchestration import (
    IdempotencyConflictError,
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

    async def insert(self, record: RunRecord) -> None:
        if record.idempotency_key is not None and any(
            r.user_id == record.user_id and r.idempotency_key == record.idempotency_key
            for r in self.records.values()
        ):
            raise IdempotencyConflictError(record.idempotency_key)
        self.records[record.run_id] = record

    async def save(self, record: RunRecord) -> None:
        self.records[record.run_id] = record

    async def get(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)

    async def find_by_idempotency(self, user_id: str, key: str) -> RunRecord | None:
        for record in self.records.values():
            if record.user_id == user_id and record.idempotency_key == key:
                return record
        return None

    async def list_by_user(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RunRecord], int]:
        owned = [r for r in self.records.values() if r.user_id == user_id]
        owned.sort(key=lambda r: (r.created_at, r.run_id), reverse=True)
        start = (page - 1) * page_size
        return owned[start : start + page_size], len(owned)


class GetBombRunStore(InMemoryRunStore):
    async def get(self, run_id: str) -> RunRecord | None:
        raise AssertionError("run execution should not read the record before starting")


class FakeProfileReader:
    def __init__(self, *profiles: ProfileSnapshot) -> None:
        self._profiles = {(p.user_id, p.id): p for p in profiles}

    async def get_snapshot(self, user_id: str, profile_id: str) -> ProfileSnapshot:
        profile = self._profiles.get((user_id, profile_id))
        if profile is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "profile not found", status_code=404)
        return profile


class FakeCatalog:
    def __init__(
        self,
        jobs: Sequence[JobFact] = (),
        eligible_job_ids: Sequence[str] | None = None,
        hits: Sequence[SearchHit] = (),
        semantic_hits: Sequence[SearchHit] = (),
        error: Exception | None = None,
    ) -> None:
        self._jobs = {job.id: job for job in jobs}
        self._eligible = (
            list(eligible_job_ids) if eligible_job_ids is not None else [job.id for job in jobs]
        )
        self._hits = list(hits)
        self._semantic_hits = list(semantic_hits)
        self._error = error

    async def ingest(self, run_id: str, batch: CollectionBatch) -> IngestionResult:
        raise NotImplementedError

    async def get_jobs(self, job_ids: Sequence[str]) -> list[JobFact]:
        return [self._jobs[job_id] for job_id in job_ids if job_id in self._jobs]

    async def hard_filter(self, spec: HardFilterSpec) -> FilterResult:
        if self._error is not None:
            raise self._error
        return FilterResult(eligible_job_ids=self._eligible, excluded=[])

    async def keyword_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        eligible = set(eligible_job_ids)
        return [hit for hit in self._hits if hit.job_id in eligible]

    async def semantic_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        eligible = set(eligible_job_ids)
        return [hit for hit in self._semantic_hits if hit.job_id in eligible]


class FakeEvaluator:
    async def evaluate(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        effective_extra_request: str | None = None,
    ) -> list[MatchAssessment]:
        return [
            MatchAssessment(
                job_id=candidate.job_id,
                matched=True,
                match_score=88,
                reason="The candidate has relevant experience.",
                matched_strengths=["Python"],
                gaps=[],
            )
            for candidate in candidates
        ]


def make_service(
    *,
    profiles: Sequence[ProfileSnapshot] = (),
    catalog: FakeCatalog | None = None,
    store: InMemoryRunStore | None = None,
    evaluator: FakeEvaluator | None = None,
    evaluation_batch_size: int = 10,
    run_in_background: bool = False,
) -> RecommendationRunService:
    return RecommendationRunService(
        store or InMemoryRunStore(),
        FakeProfileReader(*(profiles or [make_profile()])),
        catalog or FakeCatalog(),
        BaselineMatchingService(),
        evaluator or FakeEvaluator(),
        "recommendation-v1",
        evaluation_batch_size=evaluation_batch_size,
        run_in_background=run_in_background,
    )


def test_plan_run_input_freezes_merged_extra_request() -> None:
    profile = make_profile(version=3, extra_request="想远程")
    run_input = plan_run_input(profile, "只要外企")
    assert run_input == RecommendationRunInput(
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
    assembled = assemble_candidates(candidates, jobs)
    assert [item.job.id for item in assembled] == ["job-2", "job-1"]
    assert all(item.job.id == item.retrieval.job_id for item in assembled)


def test_start_freezes_input_and_completes() -> None:
    store = InMemoryRunStore()
    service = make_service(store=store, profiles=[make_profile(extra_request="想远程")])
    accepted = run(service.start("user-1", "profile-1", "只要外企", "key-1"))
    record = store.records[accepted.run_id]
    assert accepted.status == RunStatus.SUCCEEDED
    assert record.recommendation_input.effective_extra_request == "想远程\n\n只要外企"
    assert record.model_config_version == "recommendation-v1"
    assert record.finished_at is not None


def test_background_run_does_not_require_initial_store_read() -> None:
    async def check() -> None:
        store = GetBombRunStore()
        service = make_service(store=store, run_in_background=True)
        accepted = await service.start("user-1", "profile-1")
        assert accepted.status == RunStatus.PENDING

        for _ in range(20):
            if store.records[accepted.run_id].status == RunStatus.SUCCEEDED:
                break
            await asyncio.sleep(0)
        assert store.records[accepted.run_id].status == RunStatus.SUCCEEDED

    run(check())


def test_idempotent_replay_same_input_returns_existing_run() -> None:
    store = InMemoryRunStore()
    service = make_service(store=store)
    first = run(service.start("user-1", "profile-1", None, "key-1"))
    second = run(service.start("user-1", "profile-1", None, "key-1"))
    assert second.run_id == first.run_id
    assert len(store.records) == 1


def test_same_key_with_different_input_conflicts() -> None:
    service = make_service()
    run(service.start("user-1", "profile-1", "只要外企", "key-1"))
    with pytest.raises(ApplicationError) as error:
        run(service.start("user-1", "profile-1", "只要国企", "key-1"))
    assert error.value.code == str(ErrorCode.CONFLICT)


def test_same_key_across_users_is_isolated() -> None:
    profiles = [make_profile(id="p1", user_id="u1"), make_profile(id="p2", user_id="u2")]
    service = make_service(profiles=profiles)
    first = run(service.start("u1", "p1", None, "key-1"))
    second = run(service.start("u2", "p2", None, "key-1"))
    assert first.run_id != second.run_id


def test_unfinished_run_results_are_empty_page() -> None:
    store = InMemoryRunStore()
    record = RunRecord(
        run_id="run-1",
        user_id="user-1",
        status=RunStatus.RUNNING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        recommendation_input=RecommendationRunInput(profile_id="p", profile_version=1),
        model_config_version="recommendation-v1",
    )
    run(store.insert(record))
    service = make_service(store=store)
    page = run(service.get_results("user-1", "run-1", 1, 10))
    assert page.items == [] and page.total == 0


def test_zero_candidates_is_a_successful_empty_run() -> None:
    store = InMemoryRunStore()
    service = make_service(store=store, catalog=FakeCatalog(eligible_job_ids=[]))
    accepted = run(service.start("user-1", "profile-1"))
    record = store.records[accepted.run_id]
    assert record.status == RunStatus.SUCCEEDED
    assert record.results == []
    assert record.counts == {
        "eligible_jobs": 0,
        "keyword_hits": 0,
        "semantic_hits": 0,
        "candidates": 0,
        "evaluated": 0,
        "results": 0,
    }


def test_failure_lands_as_failed_with_run_error() -> None:
    store = InMemoryRunStore()
    failing = FakeCatalog(
        error=ApplicationError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "db down",
            status_code=503,
            details={"stage": "FILTER"},
        )
    )
    service = make_service(store=store, catalog=failing)
    accepted = run(service.start("user-1", "profile-1"))
    record = store.records[accepted.run_id]
    assert record.status == RunStatus.FAILED
    assert record.error is not None
    assert record.error.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE)
    assert record.error.details == {
        "stage": "FILTER",
        "error_type": "ApplicationError",
    }
    assert record.finished_at is not None


def test_missing_job_facts_are_reported_as_warning() -> None:
    job = make_job(id="job-1")
    catalog = FakeCatalog(
        jobs=[job],
        eligible_job_ids=["job-1", "gone"],
        hits=[
            SearchHit(job_id="job-1", score=0.8, channel=RetrievalChannel.KEYWORD),
            SearchHit(job_id="gone", score=0.7, channel=RetrievalChannel.KEYWORD),
        ],
    )
    store = InMemoryRunStore()
    service = make_service(store=store, catalog=catalog)
    accepted = run(service.start("user-1", "profile-1"))
    record = store.records[accepted.run_id]

    assert record.status == RunStatus.SUCCEEDED
    assert record.counts["candidates"] == 2
    assert record.counts["results"] == 1
    assert record.warnings == ["1 candidate job facts could not be loaded"]


def test_full_chain_returns_candidates_and_scopes_queries() -> None:
    job = make_job(id="job-1")
    other = make_job(id="job-2", title="算法工程师")
    catalog = FakeCatalog(
        jobs=[job, other],
        hits=[SearchHit(job_id="job-1", score=0.8, channel=RetrievalChannel.KEYWORD)],
    )
    store = InMemoryRunStore()
    service = make_service(store=store, catalog=catalog)
    accepted = run(service.start("user-1", "profile-1"))

    view = run(service.get_run("user-1", accepted.run_id))
    assert view.status == RunStatus.SUCCEEDED
    assert view.counts["results"] == 1

    page = run(service.get_results("user-1", accepted.run_id, 1, 10))
    assert page.total == 1
    item = page.items[0]
    assert item.job.id == "job-1" and item.retrieval.job_id == "job-1"
    assert item.assessment.matched
    assert item.retrieval.retrieval_score == pytest.approx(0.4)

    runs = run(service.list_runs("user-1", 1, 10))
    assert runs.total == 1 and runs.items[0].run_id == accepted.run_id

    with pytest.raises(ApplicationError) as error:
        run(service.get_run("someone-else", accepted.run_id))
    assert error.value.code == str(ErrorCode.NOT_FOUND)


def test_final_result_reloads_job_fact_after_evaluation() -> None:
    initial = make_job(id="job-1", title="旧岗位", fact_version="v1")
    refreshed = make_job(id="job-1", title="更新后的岗位", fact_version="v2")

    class RefreshingCatalog(FakeCatalog):
        def __init__(self) -> None:
            super().__init__(
                jobs=[initial],
                hits=[SearchHit(job_id="job-1", score=0.8, channel=RetrievalChannel.KEYWORD)],
            )
            self.get_jobs_calls = 0

        async def get_jobs(self, job_ids: Sequence[str]) -> list[JobFact]:
            self.get_jobs_calls += 1
            jobs = {initial.id: initial} if self.get_jobs_calls == 1 else {refreshed.id: refreshed}
            return [jobs[job_id] for job_id in job_ids if job_id in jobs]

    catalog = RefreshingCatalog()
    service = make_service(catalog=catalog)

    accepted = run(service.start("user-1", "profile-1"))
    result = run(service.get_results("user-1", accepted.run_id, 1, 10)).items[0]

    assert catalog.get_jobs_calls == 2
    assert result.job.title == "更新后的岗位"
    assert result.job.fact_version == "v2"


def test_retrieve_fuses_keyword_and_semantic_channels_before_evaluation() -> None:
    jobs = [make_job(id="job-1"), make_job(id="job-2", title="平台工程师")]
    catalog = FakeCatalog(
        jobs=jobs,
        hits=[SearchHit(job_id="job-1", score=0.8, channel=RetrievalChannel.KEYWORD)],
        semantic_hits=[SearchHit(job_id="job-2", score=0.9, channel=RetrievalChannel.SEMANTIC)],
    )
    store = InMemoryRunStore()
    service = make_service(store=store, catalog=catalog)

    accepted = run(service.start("user-1", "profile-1"))
    record = store.records[accepted.run_id]

    assert record.status == RunStatus.SUCCEEDED
    assert record.counts["keyword_hits"] == 1
    assert record.counts["semantic_hits"] == 1
    assert {item.job.id for item in record.results} == {"job-1", "job-2"}
    assert record.results[0].retrieval.sources


def test_evaluation_batch_failure_does_not_persist_partial_results() -> None:
    class FailingEvaluator(FakeEvaluator):
        def __init__(self) -> None:
            self.calls = 0

        async def evaluate(
            self,
            profile: ProfileSnapshot,
            jobs: Sequence[JobFact],
            candidates: Sequence[Candidate],
            effective_extra_request: str | None = None,
        ) -> list[MatchAssessment]:
            self.calls += 1
            if self.calls == 2:
                raise ApplicationError(
                    ErrorCode.RECOMMENDATION_FAILED,
                    "unsafe provider detail must not escape",
                    status_code=502,
                    details={"stage": "EVALUATE"},
                )
            return await super().evaluate(profile, jobs, candidates, effective_extra_request)

    jobs = [make_job(id="job-1"), make_job(id="job-2", title="平台工程师")]
    catalog = FakeCatalog(
        jobs=jobs,
        hits=[
            SearchHit(job_id="job-1", score=0.8, channel=RetrievalChannel.KEYWORD),
            SearchHit(job_id="job-2", score=0.7, channel=RetrievalChannel.KEYWORD),
        ],
    )
    store = InMemoryRunStore()
    service = make_service(
        store=store,
        catalog=catalog,
        evaluator=FailingEvaluator(),
        evaluation_batch_size=1,
    )

    accepted = run(service.start("user-1", "profile-1"))
    record = store.records[accepted.run_id]

    assert record.status == RunStatus.FAILED
    assert record.results == []
    assert record.error is not None
    assert record.error.details == {
        "stage": "EVALUATE",
        "batch_index": 1,
        "error_type": "ApplicationError",
    }
