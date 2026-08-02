from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from ..contracts import (
    CreditUsage,
    Feedback,
    JobFact,
    JobStatus,
    MatchAssessment,
    RecommendationAssessmentView,
    RecommendationCardView,
    RecommendationJobView,
    RecommendationResultView,
    RecommendationRunInput,
    RecommendationSort,
    RecommendationStep,
    RecommendationTaskStatus,
    RecommendationTaskView,
    RunError,
)


class IdempotencyConflictError(Exception):
    """Compatibility marker for adapters that surface a unique-key replay."""


_IDEMPOTENCY_INDEX_NAME = "uq_recommendation_run_user_idempotency"
_CONSTRAINT_PATTERN = re.compile(r'constraint "([^"]+)"')


def _integrity_error_constraint_name(exc: IntegrityError) -> str | None:
    candidates = [exc.orig]
    for candidate in tuple(candidates):
        nested = getattr(candidate, "orig", None)
        if nested is not None:
            candidates.append(nested)
        cause = getattr(candidate, "__cause__", None)
        if cause is not None:
            candidates.append(cause)
    for candidate in candidates:
        direct_name = getattr(candidate, "constraint_name", None)
        if direct_name is not None:
            return str(direct_name)
        diagnostic = getattr(getattr(candidate, "diag", None), "constraint_name", None)
        if diagnostic is not None:
            return str(diagnostic)
        match = _CONSTRAINT_PATTERN.search(str(candidate))
        if match:
            return match.group(1)
    return None


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    return _integrity_error_constraint_name(exc) == _IDEMPOTENCY_INDEX_NAME


# Compatibility mapping for older seed/integration callers. The actual
# PostgreSQL adapter lives in infrastructure/recommendation_store.py.
RUN_TABLE = sa.table(
    "recommendation_run",
    sa.column("run_id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("status", sa.String),
    sa.column("current_step", sa.String),
    sa.column("progress_percent", sa.Integer),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("finished_at", sa.DateTime(timezone=True)),
    sa.column("counts", postgresql.JSONB),
    sa.column("warnings", postgresql.JSONB),
    sa.column("recommendation_input", postgresql.JSONB),
    sa.column("model_config_version", sa.String),
    sa.column("error", postgresql.JSONB),
    sa.column("idempotency_key", sa.String),
    sa.column("request_fingerprint", sa.String),
    sa.column("credit_cost", sa.BigInteger),
    sa.column("credit_refunded", sa.Boolean),
    sa.column("balance_after_charge", sa.BigInteger),
)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Persisted state for one user recommendation task."""

    run_id: str
    user_id: str
    status: RecommendationTaskStatus
    created_at: datetime
    recommendation_input: RecommendationRunInput
    model_config_version: str
    current_step: RecommendationStep = RecommendationStep.PENDING
    progress_percent: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: RunError | None = None
    idempotency_key: str | None = None
    request_fingerprint: str | None = None
    credit_cost: int = 0
    credit_refunded: bool = False
    balance_after_charge: int = 0


@dataclass(frozen=True, slots=True)
class RecommendationRecord:
    """Formal recommendation result, independent of mutable catalog facts."""

    recommendation_id: str
    user_id: str
    run_id: str
    job_id: str
    position: int
    job_snapshot: JobFact
    assessment: MatchAssessment
    recommended_at: datetime
    feedback: Feedback | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecommendationProjection:
    record: RecommendationRecord
    is_saved: bool
    current_job_status: JobStatus | None = None
    current_published_at: datetime | None = None
    current_deadline_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CreateRunResult:
    record: RunRecord
    created: bool


def record_to_task_view(record: RunRecord) -> RecommendationTaskView:
    return RecommendationTaskView(
        run_id=record.run_id,
        status=record.status,
        current_step=record.current_step,
        progress_percent=record.progress_percent,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        counts=record.counts,
        credits=CreditUsage(
            cost=record.credit_cost,
            refunded=record.credit_refunded,
            net_spent=0 if record.credit_refunded else record.credit_cost,
        ),
        error=record.error,
    )


def projection_to_card(projection: RecommendationProjection) -> RecommendationCardView:
    record = projection.record
    job = record.job_snapshot
    assessment = record.assessment
    current_status = projection.current_job_status or job.status
    current_published_at = projection.current_published_at or job.published_at
    current_deadline_at = projection.current_deadline_at or job.deadline_at
    evidence = assessment.evidence or [detail.explanation for detail in assessment.evidence_details]
    return RecommendationCardView(
        recommendation_id=record.recommendation_id,
        run_id=record.run_id,
        recommended_at=record.recommended_at,
        job=RecommendationJobView(
            id=job.id,
            title=job.title,
            company_name=job.company_name,
            company_nature=job.company_nature,
            locations=job.locations,
            status=current_status,
            published_at=current_published_at,
            deadline_at=current_deadline_at,
            first_seen_at=job.first_seen_at,
        ),
        assessment=RecommendationAssessmentView(
            match_score=assessment.match_score,
            reason=assessment.reason,
            matched_strengths=assessment.matched_strengths,
            gaps=assessment.gaps,
            evidence=evidence,
        ),
        is_saved=projection.is_saved,
        feedback=record.feedback,
    )


def projection_to_result(projection: RecommendationProjection) -> RecommendationResultView:
    card = projection_to_card(projection)
    return RecommendationResultView(
        **card.model_dump(),
        is_deleted=projection.record.deleted_at is not None,
        deleted_at=projection.record.deleted_at,
    )


class RecommendationRunStore(Protocol):
    """Private persistence boundary used by recommendation orchestration."""

    async def find_by_idempotency(self, user_id: str, key: str) -> RunRecord | None: ...

    async def create_charged_run(self, record: RunRecord) -> CreateRunResult: ...

    async def save_progress(self, record: RunRecord) -> None: ...

    async def complete_run(
        self,
        record: RunRecord,
        recommendations: list[RecommendationRecord],
    ) -> None: ...

    async def fail_and_refund(
        self,
        user_id: str,
        run_id: str,
        error: RunError,
        finished_at: datetime,
    ) -> None: ...

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def list_by_user(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RunRecord], int]: ...

    async def successful_job_ids(self, user_id: str) -> set[str]: ...

    async def list_recommendations(
        self,
        user_id: str,
        page: int,
        page_size: int,
        sort: RecommendationSort,
    ) -> tuple[list[RecommendationProjection], int]: ...

    async def list_run_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RecommendationProjection], int]: ...

    async def set_feedback(
        self,
        user_id: str,
        recommendation_id: str,
        feedback: Feedback | None,
    ) -> bool: ...

    async def soft_delete(
        self,
        user_id: str,
        recommendation_id: str,
        deleted_at: datetime,
    ) -> bool: ...


__all__ = [
    "CreateRunResult",
    "IdempotencyConflictError",
    "RecommendationProjection",
    "RecommendationRecord",
    "RecommendationRunStore",
    "RunRecord",
    "RUN_TABLE",
    "projection_to_card",
    "projection_to_result",
    "record_to_task_view",
    "_IDEMPOTENCY_INDEX_NAME",
    "_is_idempotency_conflict",
]
