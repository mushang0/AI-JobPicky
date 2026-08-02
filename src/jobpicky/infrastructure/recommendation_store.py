from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import (
    ErrorCode,
    Feedback,
    JobFact,
    JobStatus,
    MatchAssessment,
    RecommendationRunInput,
    RecommendationSort,
    RecommendationStep,
    RecommendationTaskStatus,
    RunError,
)
from ..errors import ApplicationError
from ..orchestration.store import (
    CreateRunResult,
    RecommendationProjection,
    RecommendationRecord,
    RunRecord,
)
from .credit_store import CREDIT_ACCOUNT_TABLE, PostgresCreditStore
from .job_catalog import JOB_TABLE
from .saved_job_store import SAVED_JOB_TABLE

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

RECOMMENDATION_TABLE = sa.table(
    "recommendation",
    sa.column("recommendation_id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("run_id", sa.String),
    sa.column("job_id", sa.String),
    sa.column("position", sa.Integer),
    sa.column("job_snapshot", postgresql.JSONB),
    sa.column("assessment", postgresql.JSONB),
    sa.column("recommended_at", sa.DateTime(timezone=True)),
    sa.column("feedback", sa.String),
    sa.column("deleted_at", sa.DateTime(timezone=True)),
)


class PostgresRecommendationStore:
    """PostgreSQL adapter for charged runs and formal recommendation history."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        credit_store: PostgresCreditStore,
    ) -> None:
        self._session_factory = session_factory
        self._credit_store = credit_store

    async def find_by_idempotency(self, user_id: str, key: str) -> RunRecord | None:
        async with self._session_factory() as session:
            return await _find_by_idempotency(session, user_id, key)

    async def create_charged_run(self, record: RunRecord) -> CreateRunResult:
        async with self._session_factory() as session, session.begin():
            await _lock_user_runs(session, record.user_id)
            existing = await _find_by_idempotency(
                session,
                record.user_id,
                record.idempotency_key or "",
            )
            if existing is not None:
                return CreateRunResult(record=existing, created=False)

            active = await session.scalar(
                sa.select(RUN_TABLE.c.run_id)
                .where(
                    RUN_TABLE.c.user_id == record.user_id,
                    RUN_TABLE.c.status.in_(
                        [
                            str(RecommendationTaskStatus.PENDING),
                            str(RecommendationTaskStatus.RUNNING),
                        ]
                    ),
                )
                .limit(1)
            )
            if active is not None:
                raise ApplicationError(
                    ErrorCode.CONFLICT,
                    "an active recommendation run already exists",
                    status_code=409,
                    details={"run_id": str(active)},
                )

            await self._credit_store.charge_in_session(
                session,
                record.user_id,
                record.run_id,
                record.credit_cost,
            )
            balance = await session.scalar(
                sa.select(CREDIT_ACCOUNT_TABLE.c.balance).where(
                    CREDIT_ACCOUNT_TABLE.c.user_id == record.user_id
                )
            )
            if balance is None:
                raise ApplicationError(
                    ErrorCode.INTERNAL_ERROR,
                    "credit account is missing",
                    status_code=500,
                )
            charged = replace(record, balance_after_charge=int(balance))
            await session.execute(sa.insert(RUN_TABLE).values(_run_to_row(charged)))
            return CreateRunResult(record=charged, created=True)

    async def save_progress(self, record: RunRecord) -> None:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                sa.update(RUN_TABLE)
                .where(
                    RUN_TABLE.c.run_id == record.run_id,
                    RUN_TABLE.c.user_id == record.user_id,
                    RUN_TABLE.c.status.in_(
                        [
                            str(RecommendationTaskStatus.PENDING),
                            str(RecommendationTaskStatus.RUNNING),
                        ]
                    ),
                )
                .values(_mutable_run_values(record))
            )
            if getattr(result, "rowcount", None) != 1:
                raise RuntimeError("recommendation run is no longer active")

    async def complete_run(
        self,
        record: RunRecord,
        recommendations: list[RecommendationRecord],
    ) -> None:
        _validate_completion(record, recommendations)
        async with self._session_factory() as session, session.begin():
            current = await _get_run(session, record.run_id, for_update=True)
            if current is None or current.user_id != record.user_id:
                raise RuntimeError("recommendation run not found")
            if current.status == RecommendationTaskStatus.SUCCEEDED:
                return
            if current.status == RecommendationTaskStatus.FAILED:
                raise RuntimeError("failed recommendation run cannot complete")
            if recommendations:
                await session.execute(
                    sa.insert(RECOMMENDATION_TABLE),
                    [_recommendation_to_row(item) for item in recommendations],
                )
            result = await session.execute(
                sa.update(RUN_TABLE)
                .where(
                    RUN_TABLE.c.run_id == record.run_id,
                    RUN_TABLE.c.user_id == record.user_id,
                    RUN_TABLE.c.status.in_(
                        [
                            str(RecommendationTaskStatus.PENDING),
                            str(RecommendationTaskStatus.RUNNING),
                        ]
                    ),
                )
                .values(_mutable_run_values(record))
            )
            if getattr(result, "rowcount", None) != 1:
                raise RuntimeError("recommendation run could not be completed")

    async def fail_and_refund(
        self,
        user_id: str,
        run_id: str,
        error: RunError,
        finished_at: datetime,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            current = await _get_run(session, run_id, for_update=True)
            if current is None or current.user_id != user_id:
                raise RuntimeError("recommendation run not found")
            if current.status == RecommendationTaskStatus.SUCCEEDED:
                return
            if current.credit_refunded:
                return
            await self._credit_store.refund_in_session(
                session,
                user_id,
                run_id,
                current.credit_cost,
            )
            await session.execute(
                sa.update(RUN_TABLE)
                .where(RUN_TABLE.c.run_id == run_id, RUN_TABLE.c.user_id == user_id)
                .values(
                    status=str(RecommendationTaskStatus.FAILED),
                    finished_at=finished_at,
                    error=error.model_dump(mode="json"),
                    credit_refunded=True,
                )
            )

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._session_factory() as session:
            return await _get_run(session, run_id)

    async def list_by_user(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RunRecord], int]:
        predicate = RUN_TABLE.c.user_id == user_id
        async with self._session_factory() as session:
            total = await session.scalar(
                sa.select(sa.func.count()).select_from(RUN_TABLE).where(predicate)
            )
            result = await session.execute(
                sa.select(RUN_TABLE)
                .where(predicate)
                .order_by(RUN_TABLE.c.created_at.desc(), RUN_TABLE.c.run_id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            records = [_row_to_run(row) for row in result.mappings()]
        return records, int(total or 0)

    async def successful_job_ids(self, user_id: str) -> set[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(RECOMMENDATION_TABLE.c.job_id).where(
                    RECOMMENDATION_TABLE.c.user_id == user_id
                )
            )
        return {str(job_id) for job_id in result.scalars()}

    async def list_recommendations(
        self,
        user_id: str,
        page: int,
        page_size: int,
        sort: RecommendationSort,
    ) -> tuple[list[RecommendationProjection], int]:
        predicate = sa.and_(
            RECOMMENDATION_TABLE.c.user_id == user_id,
            RECOMMENDATION_TABLE.c.deleted_at.is_(None),
        )
        if sort == RecommendationSort.MATCH_SCORE_DESC:
            order = (
                RECOMMENDATION_TABLE.c.assessment["match_score"].as_integer().desc(),
                RECOMMENDATION_TABLE.c.recommendation_id.asc(),
            )
        else:
            order = (
                RECOMMENDATION_TABLE.c.recommended_at.desc(),
                RECOMMENDATION_TABLE.c.recommendation_id.asc(),
            )
        return await self._list_recommendation_rows(
            user_id,
            predicate,
            order,
            page,
            page_size,
        )

    async def list_run_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RecommendationProjection], int]:
        return await self._list_recommendation_rows(
            user_id,
            sa.and_(
                RECOMMENDATION_TABLE.c.user_id == user_id,
                RECOMMENDATION_TABLE.c.run_id == run_id,
            ),
            (
                RECOMMENDATION_TABLE.c.position.asc(),
                RECOMMENDATION_TABLE.c.recommendation_id.asc(),
            ),
            page,
            page_size,
        )

    async def set_feedback(
        self,
        user_id: str,
        recommendation_id: str,
        feedback: Feedback | None,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            found = await session.scalar(
                sa.update(RECOMMENDATION_TABLE)
                .where(
                    RECOMMENDATION_TABLE.c.recommendation_id == recommendation_id,
                    RECOMMENDATION_TABLE.c.user_id == user_id,
                )
                .values(feedback=str(feedback) if feedback is not None else None)
                .returning(RECOMMENDATION_TABLE.c.recommendation_id)
            )
        return found is not None

    async def soft_delete(
        self,
        user_id: str,
        recommendation_id: str,
        deleted_at: datetime,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            found = await session.scalar(
                sa.update(RECOMMENDATION_TABLE)
                .where(
                    RECOMMENDATION_TABLE.c.recommendation_id == recommendation_id,
                    RECOMMENDATION_TABLE.c.user_id == user_id,
                )
                .values(
                    deleted_at=sa.func.coalesce(
                        RECOMMENDATION_TABLE.c.deleted_at,
                        deleted_at,
                    )
                )
                .returning(RECOMMENDATION_TABLE.c.recommendation_id)
            )
        return found is not None

    async def _list_recommendation_rows(
        self,
        user_id: str,
        predicate: sa.ColumnElement[bool],
        order: tuple[sa.ColumnElement[object], ...],
        page: int,
        page_size: int,
    ) -> tuple[list[RecommendationProjection], int]:
        join = RECOMMENDATION_TABLE.outerjoin(
            JOB_TABLE,
            JOB_TABLE.c.id == RECOMMENDATION_TABLE.c.job_id,
        ).outerjoin(
            SAVED_JOB_TABLE,
            sa.and_(
                SAVED_JOB_TABLE.c.job_id == RECOMMENDATION_TABLE.c.job_id,
                SAVED_JOB_TABLE.c.user_id == user_id,
            ),
        )
        async with self._session_factory() as session:
            total = await session.scalar(
                sa.select(sa.func.count()).select_from(RECOMMENDATION_TABLE).where(predicate)
            )
            result = await session.execute(
                sa.select(
                    RECOMMENDATION_TABLE,
                    JOB_TABLE.c.status.label("current_job_status"),
                    JOB_TABLE.c.published_at.label("current_published_at"),
                    JOB_TABLE.c.deadline_at.label("current_deadline_at"),
                    SAVED_JOB_TABLE.c.job_id.is_not(None).label("is_saved"),
                )
                .select_from(join)
                .where(predicate)
                .order_by(*order)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            records = [
                RecommendationProjection(
                    record=_row_to_recommendation(row),
                    is_saved=bool(row.is_saved),
                    current_job_status=(
                        JobStatus(row.current_job_status)
                        if row.current_job_status is not None
                        else None
                    ),
                    current_published_at=row.current_published_at,
                    current_deadline_at=row.current_deadline_at,
                )
                for row in result.mappings()
            ]
        return records, int(total or 0)


async def _lock_user_runs(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"recommendation-run:{user_id}"},
    )


async def _find_by_idempotency(
    session: AsyncSession,
    user_id: str,
    key: str,
) -> RunRecord | None:
    result = await session.execute(
        sa.select(RUN_TABLE).where(
            RUN_TABLE.c.user_id == user_id,
            RUN_TABLE.c.idempotency_key == key,
        )
    )
    row = result.mappings().one_or_none()
    return _row_to_run(row) if row is not None else None


async def _get_run(
    session: AsyncSession,
    run_id: str,
    *,
    for_update: bool = False,
) -> RunRecord | None:
    statement = sa.select(RUN_TABLE).where(RUN_TABLE.c.run_id == run_id)
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    row = result.mappings().one_or_none()
    return _row_to_run(row) if row is not None else None


def _run_to_row(record: RunRecord) -> dict[str, object]:
    return {
        "run_id": record.run_id,
        "user_id": record.user_id,
        "status": str(record.status),
        "current_step": str(record.current_step),
        "progress_percent": record.progress_percent,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "counts": record.counts,
        "warnings": record.warnings,
        "recommendation_input": record.recommendation_input.model_dump(mode="json"),
        "model_config_version": record.model_config_version,
        "error": record.error.model_dump(mode="json") if record.error else None,
        "idempotency_key": record.idempotency_key,
        "request_fingerprint": record.request_fingerprint,
        "credit_cost": record.credit_cost,
        "credit_refunded": record.credit_refunded,
        "balance_after_charge": record.balance_after_charge,
    }


def _mutable_run_values(record: RunRecord) -> dict[str, object]:
    row = _run_to_row(record)
    for key in (
        "run_id",
        "user_id",
        "created_at",
        "recommendation_input",
        "model_config_version",
        "idempotency_key",
        "request_fingerprint",
        "credit_cost",
        "balance_after_charge",
    ):
        row.pop(key)
    return row


def _row_to_run(row: sa.RowMapping) -> RunRecord:
    return RunRecord(
        run_id=str(row.run_id),
        user_id=str(row.user_id),
        status=RecommendationTaskStatus(row.status),
        current_step=RecommendationStep(row.current_step),
        progress_percent=int(row.progress_percent),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        counts={str(key): int(value) for key, value in (row.counts or {}).items()},
        warnings=[str(item) for item in (row.warnings or [])],
        recommendation_input=RecommendationRunInput.model_validate(row.recommendation_input),
        model_config_version=str(row.model_config_version),
        error=RunError.model_validate(row.error) if row.error else None,
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        credit_cost=int(row.credit_cost),
        credit_refunded=bool(row.credit_refunded),
        balance_after_charge=int(row.balance_after_charge),
    )


def _recommendation_to_row(record: RecommendationRecord) -> dict[str, object]:
    return {
        "recommendation_id": record.recommendation_id,
        "user_id": record.user_id,
        "run_id": record.run_id,
        "job_id": record.job_id,
        "position": record.position,
        "job_snapshot": record.job_snapshot.model_dump(mode="json"),
        "assessment": record.assessment.model_dump(mode="json"),
        "recommended_at": record.recommended_at,
        "feedback": str(record.feedback) if record.feedback is not None else None,
        "deleted_at": record.deleted_at,
    }


def _row_to_recommendation(row: sa.RowMapping) -> RecommendationRecord:
    return RecommendationRecord(
        recommendation_id=str(row.recommendation_id),
        user_id=str(row.user_id),
        run_id=str(row.run_id),
        job_id=str(row.job_id),
        position=int(row.position),
        job_snapshot=JobFact.model_validate(row.job_snapshot),
        assessment=MatchAssessment.model_validate(row.assessment),
        recommended_at=row.recommended_at,
        feedback=Feedback(row.feedback) if row.feedback is not None else None,
        deleted_at=row.deleted_at,
    )


def _validate_completion(
    run: RunRecord,
    recommendations: list[RecommendationRecord],
) -> None:
    if run.status != RecommendationTaskStatus.SUCCEEDED or run.progress_percent != 100:
        raise ValueError("completed run must be succeeded at 100 percent")
    if len(recommendations) > 50:
        raise ValueError("a run cannot persist more than 50 recommendations")
    job_ids: set[str] = set()
    for item in recommendations:
        if item.user_id != run.user_id or item.run_id != run.run_id:
            raise ValueError("recommendation owner and run must match")
        if item.job_id != item.job_snapshot.id or item.job_id != item.assessment.job_id:
            raise ValueError("recommendation job identities must match")
        if not item.assessment.matched:
            raise ValueError("formal recommendations must be matched")
        if item.job_id in job_ids:
            raise ValueError("recommendation job IDs must be unique within a run")
        job_ids.add(item.job_id)


__all__ = ["PostgresRecommendationStore", "RECOMMENDATION_TABLE", "RUN_TABLE"]
