from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from ..contracts import (
    Candidate,
    ErrorCode,
    JobFact,
    MatchAssessment,
    Page,
    ProfileSnapshot,
    RecommendationCandidate,
    RecommendationItem,
    RecommendationRunInput,
    RecommendationStep,
    RunAccepted,
    RunError,
    RunStatus,
    RunView,
    error_message,
    merge_extra_request,
    validate_assessments,
)
from ..contracts.common import JsonObject
from ..errors import ApplicationError
from ..ports import JobCatalogPort, JobEvaluatorPort, MatchingPort, ProfileSnapshotReaderPort
from .store import (
    IdempotencyConflictError,
    RecommendationRunStore,
    RunRecord,
    record_to_run_view,
)


def plan_run_input(
    profile: ProfileSnapshot,
    extra_request: str | None,
) -> RecommendationRunInput:
    """Freeze the run input at creation time (architecture §4.12)."""
    return RecommendationRunInput(
        profile_id=profile.id,
        profile_version=profile.version,
        effective_extra_request=merge_extra_request(profile.extra_request, extra_request),
    )


def assemble_candidates(
    candidates: Sequence[Candidate],
    jobs: Sequence[JobFact],
) -> list[RecommendationCandidate]:
    """Pair candidates with their job snapshots, keeping candidate order."""
    jobs_by_id = {job.id: job for job in jobs}
    return [
        RecommendationCandidate(job=jobs_by_id[candidate.job_id], retrieval=candidate)
        for candidate in candidates
        if candidate.job_id in jobs_by_id
    ]


def assemble_recommendations(
    candidates: Sequence[Candidate],
    assessments: Sequence[MatchAssessment],
    jobs: Sequence[JobFact],
) -> list[RecommendationItem]:
    """Rebuild final items from catalog facts after evaluation."""
    validate_assessments([candidate.job_id for candidate in candidates], assessments)
    candidates_by_id = {candidate.job_id: candidate for candidate in candidates}
    jobs_by_id = {job.id: job for job in jobs}
    assessments_by_id = {assessment.job_id: assessment for assessment in assessments}
    items: list[RecommendationItem] = []
    for candidate in candidates:
        job = jobs_by_id.get(candidate.job_id)
        assessment = assessments_by_id[candidate.job_id]
        if job is None or not assessment.matched:
            continue
        items.append(
            RecommendationItem(
                job=job,
                retrieval=candidates_by_id[candidate.job_id],
                assessment=assessment,
            )
        )
    return items


class RecommendationRunService:
    """RecommendationOrchestratorPort implementation over the deterministic chain.

    Runs execute as in-process asyncio tasks: start returns immediately and a
    restart drops in-flight tasks, leaving their records in RUNNING (plan 004,
    decision 5 — recovery and retry hardening belong to phase 3, this slice
    does not fake reliability). run_in_background=False executes inline so
    tests and seeds get a deterministic, awaitable run.

    Results are stored as snapshots at completion time (R7): later changes to
    job facts never rewrite what a historical run returned.
    """

    def __init__(
        self,
        store: RecommendationRunStore,
        profile_reader: ProfileSnapshotReaderPort,
        catalog: JobCatalogPort,
        matching: MatchingPort,
        evaluator: JobEvaluatorPort,
        model_config_version: str,
        *,
        evaluation_batch_size: int = 10,
        run_in_background: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._profile_reader = profile_reader
        self._catalog = catalog
        self._matching = matching
        self._evaluator = evaluator
        self._model_config_version = model_config_version
        if evaluation_batch_size < 1:
            raise ValueError("evaluation_batch_size must be at least 1")
        self._evaluation_batch_size = evaluation_batch_size
        self._run_in_background = run_in_background
        self._now = now or (lambda: datetime.now(UTC))
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(
        self,
        user_id: str,
        profile_id: str,
        extra_request: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunAccepted:
        profile = await self._profile_reader.get_snapshot(user_id, profile_id)
        run_input = plan_run_input(profile, extra_request)

        if idempotency_key is not None:
            existing = await self._store.find_by_idempotency(user_id, idempotency_key)
            if existing is not None:
                return self._reuse_or_conflict(existing, run_input)

        record = RunRecord(
            run_id=uuid.uuid4().hex,
            user_id=user_id,
            status=RunStatus.PENDING,
            current_step=str(RecommendationStep.PENDING),
            created_at=self._now(),
            recommendation_input=run_input,
            model_config_version=self._model_config_version,
            idempotency_key=idempotency_key,
        )
        try:
            await self._store.insert(record)
        except IdempotencyConflictError:
            # Lost a race with a concurrent identical submission: replay the
            # winner instead of creating a duplicate run (R5).
            existing = await self._store.find_by_idempotency(user_id, idempotency_key or "")
            if existing is None:  # pragma: no cover - unique index fired without a row
                raise
            return self._reuse_or_conflict(existing, run_input)

        if self._run_in_background:
            task = asyncio.create_task(self._execute(record, profile))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return RunAccepted(run_id=record.run_id, status=record.status)
        await self._execute(record, profile)
        finished = await self._require_user_record(user_id, record.run_id)
        return RunAccepted(run_id=record.run_id, status=finished.status)

    async def list_runs(self, user_id: str, page: int, page_size: int) -> Page[RunView]:
        _validate_pagination(page, page_size)
        records, total = await self._store.list_by_user(user_id, page, page_size)
        return Page(
            items=[record_to_run_view(record) for record in records],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_run(self, user_id: str, run_id: str) -> RunView:
        return record_to_run_view(await self._require_user_record(user_id, run_id))

    async def get_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationItem]:
        _validate_pagination(page, page_size)
        record = await self._require_user_record(user_id, run_id)
        # An unfinished run has no results yet; that is a normal empty page,
        # not an error — RunView.status says whether results are due.
        results = record.results if record.status not in _UNFINISHED else []
        start = (page - 1) * page_size
        return Page(
            items=results[start : start + page_size],
            total=len(results),
            page=page,
            page_size=page_size,
        )

    async def _execute(self, record: RunRecord, profile: ProfileSnapshot) -> None:
        try:
            run_input = record.recommendation_input
            record = replace(
                record,
                status=RunStatus.RUNNING,
                started_at=self._now(),
                current_step=str(RecommendationStep.FILTER),
            )
            await self._store.save(record)

            spec = self._matching.build_filter_spec(profile, run_input.effective_extra_request)
            filter_result = await self._catalog.hard_filter(spec)
            eligible_job_ids = filter_result.eligible_job_ids

            record = replace(record, current_step=str(RecommendationStep.RETRIEVE))
            await self._store.save(record)
            query_text = self._matching.build_query_text(profile, run_input.effective_extra_request)
            if eligible_job_ids:
                keyword_hits, semantic_hits = await asyncio.gather(
                    self._catalog.keyword_search(query_text, eligible_job_ids),
                    self._catalog.semantic_search(query_text, eligible_job_ids),
                )
            else:
                keyword_hits, semantic_hits = [], []
            candidates = self._matching.merge_candidates(keyword_hits, semantic_hits)
            jobs = await self._catalog.get_jobs([c.job_id for c in candidates])
            jobs_by_id = {job.id: job for job in jobs}
            missing_job_count = sum(candidate.job_id not in jobs_by_id for candidate in candidates)
            warnings = list(record.warnings)
            if missing_job_count:
                warnings.append(f"{missing_job_count} candidate job facts could not be loaded")

            results: list[RecommendationItem] = []
            evaluated_count = 0
            if candidates and jobs:
                evaluable_candidates = [
                    candidate for candidate in candidates if candidate.job_id in jobs_by_id
                ]
                record = replace(record, current_step=str(RecommendationStep.EVALUATE))
                await self._store.save(record)
                assessments: list[MatchAssessment] = []
                for batch_index, start in enumerate(
                    range(0, len(evaluable_candidates), self._evaluation_batch_size)
                ):
                    candidate_batch = evaluable_candidates[
                        start : start + self._evaluation_batch_size
                    ]
                    batch_jobs = [jobs_by_id[candidate.job_id] for candidate in candidate_batch]
                    try:
                        batch_assessments = await self._evaluator.evaluate(
                            profile,
                            batch_jobs,
                            candidate_batch,
                            run_input.effective_extra_request,
                        )
                    except ApplicationError as exc:
                        details: JsonObject = {
                            "stage": "EVALUATE",
                            "batch_index": batch_index,
                        }
                        if exc.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE):
                            details["dependency"] = "llm"
                        raise ApplicationError(
                            exc.code,
                            "evaluator dependency unavailable"
                            if exc.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE)
                            else "evaluator batch failed",
                            status_code=exc.status_code,
                            details=details,
                        ) from exc
                    except Exception as exc:
                        raise ApplicationError(
                            ErrorCode.RECOMMENDATION_FAILED,
                            "evaluator batch failed",
                            status_code=502,
                            details={"stage": "EVALUATE", "batch_index": batch_index},
                        ) from exc
                    try:
                        validate_assessments(
                            [candidate.job_id for candidate in candidate_batch],
                            batch_assessments,
                        )
                    except ValueError as exc:
                        raise ApplicationError(
                            ErrorCode.RECOMMENDATION_FAILED,
                            "evaluator returned an incomplete assessment batch",
                            status_code=502,
                            details={"stage": "EVALUATE", "batch_index": batch_index},
                        ) from exc
                    assessments.extend(batch_assessments)
                evaluated_count = len(assessments)
                # The evaluator saw the pre-evaluation facts.  Re-read before
                # saving so the persisted item is the completion-time catalog
                # snapshot, not a stale copy held across the model call.
                final_jobs = await self._catalog.get_jobs(
                    [candidate.job_id for candidate in evaluable_candidates]
                )
                final_job_ids = {job.id for job in final_jobs}
                missing_after_evaluation = sum(
                    candidate.job_id not in final_job_ids for candidate in evaluable_candidates
                )
                if missing_after_evaluation:
                    warnings.append(
                        f"{missing_after_evaluation} candidate job facts could not be loaded "
                        "after evaluation"
                    )
                results = assemble_recommendations(evaluable_candidates, assessments, final_jobs)

            record = replace(record, current_step=str(RecommendationStep.SAVE))
            await self._store.save(record)

            record = replace(
                record,
                status=RunStatus.SUCCEEDED,
                current_step=str(RecommendationStep.COMPLETE),
                finished_at=self._now(),
                counts={
                    "eligible_jobs": len(eligible_job_ids),
                    "keyword_hits": len(keyword_hits),
                    "semantic_hits": len(semantic_hits),
                    "candidates": len(candidates),
                    "evaluated": evaluated_count,
                    "results": len(results),
                },
                warnings=warnings,
                results=results,
            )
            await self._store.save(record)
        except Exception as exc:
            await self._fail(record, exc)

    async def _fail(self, record: RunRecord, exc: Exception) -> None:
        details: JsonObject = {"error_type": type(exc).__name__}
        if isinstance(exc, ApplicationError):
            code, message = exc.code, error_message(exc.code)
            details = dict(exc.details)
            details["error_type"] = type(exc).__name__
        else:
            code = str(ErrorCode.RECOMMENDATION_FAILED)
            message = error_message(code)
        await self._store.save(
            replace(
                record,
                status=RunStatus.FAILED,
                finished_at=self._now(),
                error=RunError(
                    code=code,
                    message=message,
                    details=details,
                ),
            )
        )

    def _reuse_or_conflict(
        self,
        existing: RunRecord,
        run_input: RecommendationRunInput,
    ) -> RunAccepted:
        # Same key + same frozen input = the same request replayed: return the
        # existing run (R5). Same key + different input must fail loudly —
        # reusing the old run would silently pretend the new input took effect.
        if existing.recommendation_input == run_input:
            return RunAccepted(run_id=existing.run_id, status=existing.status)
        raise ApplicationError(
            ErrorCode.CONFLICT,
            "idempotency key was already used with different recommendation input",
            status_code=409,
            details={"run_id": existing.run_id},
        )

    async def _require_user_record(self, user_id: str, run_id: str) -> RunRecord:
        record = await self._store.get(run_id)
        if record is None or record.user_id != user_id:
            raise ApplicationError(
                ErrorCode.NOT_FOUND,
                f"recommendation run {run_id} not found",
                status_code=404,
            )
        return record


_UNFINISHED = (RunStatus.PENDING, RunStatus.RUNNING)


def _validate_pagination(page: int, page_size: int) -> None:
    if page < 1 or page_size < 1:
        raise ApplicationError(
            ErrorCode.VALIDATION_ERROR,
            "page and page_size must be positive integers",
            status_code=422,
        )


__all__ = [
    "RecommendationRunService",
    "assemble_candidates",
    "assemble_recommendations",
    "plan_run_input",
]
