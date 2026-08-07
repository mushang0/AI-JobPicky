from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from ..contracts import (
    Candidate,
    ErrorCode,
    Feedback,
    JobFact,
    MatchAssessment,
    Page,
    ProfileSnapshot,
    RecommendationCandidate,
    RecommendationCardView,
    RecommendationFeedbackView,
    RecommendationItem,
    RecommendationResultView,
    RecommendationRunAccepted,
    RecommendationRunInput,
    RecommendationSort,
    RecommendationStep,
    RecommendationTaskStatus,
    RecommendationTaskView,
    RunError,
    error_message,
    merge_extra_request,
    validate_assessments,
)
from ..contracts.common import JsonObject
from ..errors import ApplicationError
from ..ports import JobCatalogPort, JobEvaluatorPort, MatchingPort, ProfileSnapshotReaderPort
from .store import (
    RecommendationRecord,
    RecommendationRunStore,
    RunRecord,
    projection_to_card,
    projection_to_result,
    record_to_task_view,
)


def plan_run_input(
    profile: ProfileSnapshot,
    extra_request: str | None,
) -> RecommendationRunInput:
    """Freeze the exact immutable profile version and merged guidance."""
    return RecommendationRunInput(
        profile_id=profile.id,
        profile_version=profile.version,
        effective_extra_request=merge_extra_request(profile.extra_request, extra_request),
    )


def assemble_candidates(
    candidates: Sequence[Candidate],
    jobs: Sequence[JobFact],
) -> list[RecommendationCandidate]:
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
    """Build formal matched results in stable candidate order, with no score threshold."""
    validate_assessments([candidate.job_id for candidate in candidates], assessments)
    jobs_by_id = {job.id: job for job in jobs}
    assessments_by_id = {assessment.job_id: assessment for assessment in assessments}
    items: list[RecommendationItem] = []
    for candidate in candidates:
        job = jobs_by_id.get(candidate.job_id)
        assessment = assessments_by_id[candidate.job_id]
        if job is None or not assessment.matched:
            continue
        items.append(RecommendationItem(job=job, retrieval=candidate, assessment=assessment))
    return items


class RecommendationRunService:
    """Complete user recommendation workflow and query service."""

    def __init__(
        self,
        store: RecommendationRunStore,
        profile_reader: ProfileSnapshotReaderPort,
        catalog: JobCatalogPort,
        matching: MatchingPort,
        evaluator: JobEvaluatorPort,
        model_config_version: str,
        *,
        recommendation_cost: int = 100,
        candidate_limit: int = 50,
        evaluation_batch_size: int = 10,
        evaluation_workers: int = 2,
        run_in_background: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if recommendation_cost < 1:
            raise ValueError("recommendation_cost must be positive")
        if not 1 <= candidate_limit <= 50:
            raise ValueError("candidate_limit must be between 1 and 50")
        if evaluation_batch_size < 1:
            raise ValueError("evaluation_batch_size must be at least 1")
        if not 1 <= evaluation_workers <= 4:
            raise ValueError("evaluation_workers must be between 1 and 4")
        self._store = store
        self._profile_reader = profile_reader
        self._catalog = catalog
        self._matching = matching
        self._evaluator = evaluator
        self._model_config_version = model_config_version
        self._recommendation_cost = recommendation_cost
        self._candidate_limit = candidate_limit
        self._evaluation_batch_size = evaluation_batch_size
        self._evaluation_semaphore = asyncio.Semaphore(evaluation_workers)
        self._run_in_background = run_in_background
        self._now = now or (lambda: datetime.now(UTC))
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(
        self,
        user_id: str,
        extra_request: str | None = None,
        idempotency_key: str | None = None,
    ) -> RecommendationRunAccepted:
        key = _validate_idempotency_key(idempotency_key)
        normalized_request = _normalize_extra_request(extra_request)
        fingerprint = _request_fingerprint(normalized_request)

        # Replays must not bind to a newer profile version or charge again.
        existing = await self._store.find_by_idempotency(user_id, key)
        if existing is not None:
            return self._reuse_or_conflict(existing, fingerprint)

        profile = await self._profile_reader.get_current(user_id)
        if profile is None:  # defensive for older adapters that returned None
            raise ApplicationError(
                ErrorCode.PROFILE_NOT_FOUND,
                "profile not found",
                status_code=404,
            )
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            user_id=user_id,
            status=RecommendationTaskStatus.PENDING,
            created_at=self._now(),
            recommendation_input=plan_run_input(profile, normalized_request),
            model_config_version=self._model_config_version,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            credit_cost=self._recommendation_cost,
        )
        created = await self._store.create_charged_run(record)
        if not created.created:
            return self._reuse_or_conflict(created.record, fingerprint)
        record = created.record

        if self._run_in_background:
            task = asyncio.create_task(self._execute(record, profile))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            await self._execute(record, profile)
            record = await self._require_user_record(user_id, record.run_id)
        return RecommendationRunAccepted(
            run_id=record.run_id,
            status=record.status,
            credits_charged=record.credit_cost,
            balance_after=record.balance_after_charge,
        )

    async def list_runs(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationTaskView]:
        _validate_pagination(page, page_size, max_page_size=100)
        records, total = await self._store.list_by_user(user_id, page, page_size)
        return Page(
            items=[record_to_task_view(record) for record in records],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_run(self, user_id: str, run_id: str) -> RecommendationTaskView:
        return record_to_task_view(await self._require_user_record(user_id, run_id))

    async def get_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationResultView]:
        _validate_pagination(page, page_size, max_page_size=50)
        run = await self._require_user_record(user_id, run_id)
        if run.status in _UNFINISHED:
            return Page(items=[], total=0, page=page, page_size=page_size)
        records, total = await self._store.list_run_results(
            user_id,
            run_id,
            page,
            page_size,
        )
        return Page(
            items=[projection_to_result(record) for record in records],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_recommendations(
        self,
        user_id: str,
        page: int,
        page_size: int,
        sort: RecommendationSort,
    ) -> Page[RecommendationCardView]:
        _validate_pagination(page, page_size, max_page_size=50)
        records, total = await self._store.list_recommendations(
            user_id,
            page,
            page_size,
            sort,
        )
        return Page(
            items=[projection_to_card(record) for record in records],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def update_feedback(
        self,
        user_id: str,
        recommendation_id: str,
        feedback: Feedback | None,
    ) -> RecommendationFeedbackView:
        found = await self._store.set_feedback(user_id, recommendation_id, feedback)
        if not found:
            _raise_recommendation_not_found()
        return RecommendationFeedbackView(
            recommendation_id=recommendation_id,
            feedback=feedback,
        )

    async def delete_recommendation(self, user_id: str, recommendation_id: str) -> None:
        found = await self._store.soft_delete(
            user_id,
            recommendation_id,
            self._now(),
        )
        if not found:
            _raise_recommendation_not_found()

    async def _execute(self, record: RunRecord, profile: ProfileSnapshot) -> None:
        try:
            record = replace(
                record,
                status=RecommendationTaskStatus.RUNNING,
                current_step=RecommendationStep.PROFILE,
                progress_percent=10,
                started_at=self._now(),
            )
            await self._store.save_progress(record)

            record = replace(
                record,
                current_step=RecommendationStep.FILTER,
                progress_percent=25,
            )
            await self._store.save_progress(record)
            run_input = record.recommendation_input
            spec = self._matching.build_filter_spec(profile, run_input.effective_extra_request)
            filter_result = await self._catalog.hard_filter(spec)
            historical_ids = await self._store.successful_job_ids(record.user_id)
            eligible_job_ids = [
                job_id for job_id in filter_result.eligible_job_ids if job_id not in historical_ids
            ]

            record = replace(
                record,
                current_step=RecommendationStep.RETRIEVE,
                progress_percent=45,
            )
            await self._store.save_progress(record)
            query_text = self._matching.build_query_text(profile, run_input.effective_extra_request)
            if eligible_job_ids:
                keyword_hits, semantic_hits = await asyncio.gather(
                    self._catalog.keyword_search(query_text, eligible_job_ids),
                    self._catalog.semantic_search(query_text, eligible_job_ids),
                )
            else:
                keyword_hits, semantic_hits = [], []
            candidates = self._matching.merge_candidates(keyword_hits, semantic_hits)[
                : self._candidate_limit
            ]
            jobs = await self._catalog.get_jobs([candidate.job_id for candidate in candidates])
            jobs_by_id = {job.id: job for job in jobs}
            evaluable_candidates = [
                candidate for candidate in candidates if candidate.job_id in jobs_by_id
            ]
            missing_job_count = len(candidates) - len(evaluable_candidates)
            warnings = list(record.warnings)
            if missing_job_count:
                warnings.append(f"{missing_job_count} candidate job facts could not be loaded")

            assessments: list[MatchAssessment] = []
            if evaluable_candidates:
                record = replace(
                    record,
                    current_step=RecommendationStep.EVALUATE,
                    progress_percent=50,
                    warnings=warnings,
                    counts={"evaluated": 0, "recommended": 0},
                )
                await self._store.save_progress(record)
                total = len(evaluable_candidates)
                batch_specs = [
                    (
                        batch_index,
                        evaluable_candidates[start : start + self._evaluation_batch_size],
                    )
                    for batch_index, start in enumerate(
                        range(0, total, self._evaluation_batch_size)
                    )
                ]
                batch_tasks = [
                    asyncio.create_task(
                        self._evaluate_batch_limited(
                            profile,
                            [jobs_by_id[candidate.job_id] for candidate in candidate_batch],
                            candidate_batch,
                            run_input.effective_extra_request,
                            batch_index,
                        )
                    )
                    for batch_index, candidate_batch in batch_specs
                ]
                batch_results: dict[int, list[MatchAssessment]] = {}
                try:
                    for completed_task in asyncio.as_completed(batch_tasks):
                        batch_index, batch_assessments = await completed_task
                        batch_results[batch_index] = batch_assessments
                        completed = sum(len(result) for result in batch_results.values())
                        completed_assessments = [
                            assessment
                            for index in sorted(batch_results)
                            for assessment in batch_results[index]
                        ]
                        record = replace(
                            record,
                            progress_percent=50 + (40 * completed // total),
                            counts={
                                "evaluated": completed,
                                "recommended": sum(item.matched for item in completed_assessments),
                            },
                        )
                        await self._store.save_progress(record)
                except BaseException:
                    for task in batch_tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*batch_tasks, return_exceptions=True)
                    raise
                assessments = [
                    assessment
                    for batch_index in sorted(batch_results)
                    for assessment in batch_results[batch_index]
                ]

            # Re-read facts after the model call so history contains completion-time snapshots.
            final_jobs = await self._catalog.get_jobs(
                [candidate.job_id for candidate in evaluable_candidates]
            )
            final_job_ids = {job.id for job in final_jobs}
            missing_after_evaluation = len(evaluable_candidates) - len(final_job_ids)
            if missing_after_evaluation:
                warnings.append(
                    f"{missing_after_evaluation} candidate job facts could not be loaded "
                    "after evaluation"
                )
            items = assemble_recommendations(
                evaluable_candidates,
                assessments,
                final_jobs,
            )
            recommended_at = self._now()
            recommendations = [
                RecommendationRecord(
                    recommendation_id=uuid.uuid4().hex,
                    user_id=record.user_id,
                    run_id=record.run_id,
                    job_id=item.job.id,
                    position=position,
                    job_snapshot=item.job,
                    assessment=item.assessment,
                    recommended_at=recommended_at,
                )
                for position, item in enumerate(items, start=1)
            ]
            counts = {"evaluated": len(assessments), "recommended": len(recommendations)}
            record = replace(
                record,
                current_step=RecommendationStep.SAVE,
                progress_percent=95,
                counts=counts,
                warnings=warnings,
            )
            await self._store.save_progress(record)
            record = replace(
                record,
                status=RecommendationTaskStatus.SUCCEEDED,
                current_step=RecommendationStep.COMPLETE,
                progress_percent=100,
                finished_at=self._now(),
            )
            await self._store.complete_run(record, recommendations)
        except Exception as exc:
            await self._fail(record, exc)

    async def _evaluate_batch_limited(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        extra_request: str | None,
        batch_index: int,
    ) -> tuple[int, list[MatchAssessment]]:
        async with self._evaluation_semaphore:
            return batch_index, await self._evaluate_batch(
                profile,
                jobs,
                candidates,
                extra_request,
                batch_index,
            )

    async def _evaluate_batch(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        extra_request: str | None,
        batch_index: int,
    ) -> list[MatchAssessment]:
        try:
            assessments = await self._evaluator.evaluate(
                profile,
                jobs,
                candidates,
                extra_request,
            )
        except ApplicationError as exc:
            details: JsonObject = {"stage": "EVALUATE", "batch_index": batch_index}
            if exc.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE):
                details["dependency"] = "llm"
            for key in ("failure_kind", "provider_attempts", "validation_attempts", "retryable"):
                if key in exc.details:
                    details[key] = exc.details[key]
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
                details={
                    "stage": "EVALUATE",
                    "batch_index": batch_index,
                    "failure_kind": "unexpected",
                },
            ) from exc
        try:
            return validate_assessments([candidate.job_id for candidate in candidates], assessments)
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.RECOMMENDATION_FAILED,
                "evaluator returned an incomplete assessment batch",
                status_code=502,
                details={
                    "stage": "EVALUATE",
                    "batch_index": batch_index,
                    "failure_kind": "candidate_mapping",
                },
            ) from exc

    async def _fail(self, record: RunRecord, exc: Exception) -> None:
        if isinstance(exc, ApplicationError):
            code = exc.code
            details = dict(exc.details)
        else:
            code = str(ErrorCode.RECOMMENDATION_FAILED)
            details = {"stage": str(record.current_step)}
        error = RunError(code=code, message=error_message(code), details=details)
        try:
            await self._store.fail_and_refund(
                record.user_id,
                record.run_id,
                error,
                self._now(),
            )
        except Exception:
            # The exception is contained because background tasks have no caller.
            # A later retry of fail_and_refund is safe through the credit ledger.
            return

    def _reuse_or_conflict(
        self,
        existing: RunRecord,
        request_fingerprint: str,
    ) -> RecommendationRunAccepted:
        if existing.request_fingerprint != request_fingerprint:
            raise ApplicationError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "idempotency key was already used with a different request",
                status_code=409,
                details={"run_id": existing.run_id},
            )
        return RecommendationRunAccepted(
            run_id=existing.run_id,
            status=existing.status,
            credits_charged=existing.credit_cost,
            balance_after=existing.balance_after_charge,
        )

    async def _require_user_record(self, user_id: str, run_id: str) -> RunRecord:
        record = await self._store.get(run_id)
        if record is None or record.user_id != user_id:
            raise ApplicationError(
                ErrorCode.NOT_FOUND,
                "recommendation run not found",
                status_code=404,
            )
        return record


_UNFINISHED = (
    RecommendationTaskStatus.PENDING,
    RecommendationTaskStatus.RUNNING,
)


def _normalize_extra_request(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _request_fingerprint(extra_request: str | None) -> str:
    payload = json.dumps(
        {"extra_request": extra_request},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_idempotency_key(value: str | None) -> str:
    if (
        value is None
        or not 1 <= len(value) <= 128
        or any(ord(character) < 32 or ord(character) > 126 for character in value)
    ):
        raise ApplicationError(
            ErrorCode.VALIDATION_ERROR,
            "invalid Idempotency-Key",
            status_code=422,
        )
    return value


def _validate_pagination(page: int, page_size: int, *, max_page_size: int) -> None:
    if page < 1 or not 1 <= page_size <= max_page_size:
        raise ApplicationError(
            ErrorCode.VALIDATION_ERROR,
            "invalid pagination",
            status_code=422,
        )


def _raise_recommendation_not_found() -> None:
    raise ApplicationError(
        ErrorCode.NOT_FOUND,
        "recommendation not found",
        status_code=404,
    )


__all__ = [
    "RecommendationRunService",
    "assemble_candidates",
    "assemble_recommendations",
    "plan_run_input",
]
