from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import (
    RecommendationCandidate,
    RecommendationRunInput,
    RunError,
    RunKind,
    RunStatus,
    RunView,
)


class IdempotencyConflictError(Exception):
    """A run with the same (user_id, idempotency_key) already exists."""


_IDEMPOTENCY_INDEX_NAME = "uq_recommendation_run_user_idempotency"


def _integrity_error_constraint_name(exc: IntegrityError) -> str | None:
    original = exc.orig
    direct_name = getattr(original, "constraint_name", None)
    if direct_name is not None:
        return str(direct_name)
    diagnostic = getattr(original, "diag", None)
    diagnostic_name = getattr(diagnostic, "constraint_name", None)
    return str(diagnostic_name) if diagnostic_name is not None else None


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    return _integrity_error_constraint_name(exc) == _IDEMPOTENCY_INDEX_NAME


@dataclass(frozen=True)
class RunRecord:
    """Full persisted state of one recommendation run."""

    run_id: str
    user_id: str
    status: RunStatus
    created_at: datetime
    recommendation_input: RecommendationRunInput
    model_config_version: str
    current_step: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: RunError | None = None
    results: list[RecommendationCandidate] = field(default_factory=list)
    idempotency_key: str | None = None


def record_to_run_view(record: RunRecord) -> RunView:
    return RunView(
        run_id=record.run_id,
        kind=RunKind.RECOMMENDATION,
        status=record.status,
        current_step=record.current_step,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        counts=record.counts,
        warnings=record.warnings,
        recommendation_input=record.recommendation_input,
        model_config_version=record.model_config_version,
        error=record.error,
    )


RUN_TABLE = sa.table(
    "recommendation_run",
    sa.column("run_id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("status", sa.String),
    sa.column("current_step", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("finished_at", sa.DateTime(timezone=True)),
    sa.column("counts", postgresql.JSONB),
    sa.column("warnings", postgresql.JSONB),
    sa.column("recommendation_input", postgresql.JSONB),
    sa.column("model_config_version", sa.String),
    sa.column("error", postgresql.JSONB),
    sa.column("idempotency_key", sa.String),
    sa.column("results", postgresql.JSONB),
)


def _record_to_row(record: RunRecord) -> dict[str, object]:
    return {
        "run_id": record.run_id,
        "user_id": record.user_id,
        "status": str(record.status),
        "current_step": record.current_step,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "counts": record.counts,
        "warnings": record.warnings,
        "recommendation_input": record.recommendation_input.model_dump(mode="json"),
        "model_config_version": record.model_config_version,
        "error": record.error.model_dump(mode="json") if record.error else None,
        "idempotency_key": record.idempotency_key,
        "results": [item.model_dump(mode="json") for item in record.results],
    }


def _row_to_record(row: sa.RowMapping) -> RunRecord:
    return RunRecord(
        run_id=row.run_id,
        user_id=row.user_id,
        status=RunStatus(row.status),
        current_step=row.current_step,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        counts=dict(row.counts),
        warnings=list(row.warnings),
        recommendation_input=RecommendationRunInput.model_validate(row.recommendation_input),
        model_config_version=row.model_config_version,
        error=RunError.model_validate(row.error) if row.error else None,
        results=[RecommendationCandidate.model_validate(item) for item in row.results],
        idempotency_key=row.idempotency_key,
    )


class RecommendationRunStore(Protocol):
    """Persistence boundary of the orchestration module (not a cross-module port)."""

    async def insert(self, record: RunRecord) -> None: ...

    async def save(self, record: RunRecord) -> None: ...

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def find_by_idempotency(self, user_id: str, key: str) -> RunRecord | None: ...

    async def list_by_user(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RunRecord], int]: ...


class PostgresRecommendationRunStore:
    """Read/write adapter for recommendation_run. No orchestration logic here."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert(self, record: RunRecord) -> None:
        idempotency_key = record.idempotency_key
        async with self._session_factory() as session:
            try:
                await session.execute(sa.insert(RUN_TABLE), [_record_to_row(record)])
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if idempotency_key is not None and _is_idempotency_conflict(exc):
                    raise IdempotencyConflictError(idempotency_key) from exc
                raise

    async def save(self, record: RunRecord) -> None:
        row = _record_to_row(record)
        async with self._session_factory() as session:
            await session.execute(
                sa.update(RUN_TABLE).where(RUN_TABLE.c.run_id == record.run_id).values(row)
            )
            await session.commit()

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(sa.select(RUN_TABLE).where(RUN_TABLE.c.run_id == run_id))
            row = result.mappings().first()
        return _row_to_record(row) if row is not None else None

    async def find_by_idempotency(self, user_id: str, key: str) -> RunRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(RUN_TABLE).where(
                    RUN_TABLE.c.user_id == user_id,
                    RUN_TABLE.c.idempotency_key == key,
                )
            )
            row = result.mappings().first()
        return _row_to_record(row) if row is not None else None

    async def list_by_user(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[RunRecord], int]:
        async with self._session_factory() as session:
            total = await session.scalar(
                sa.select(sa.func.count())
                .select_from(RUN_TABLE)
                .where(RUN_TABLE.c.user_id == user_id)
            )
            result = await session.execute(
                sa.select(RUN_TABLE)
                .where(RUN_TABLE.c.user_id == user_id)
                .order_by(RUN_TABLE.c.created_at.desc(), RUN_TABLE.c.run_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            records = [_row_to_record(row) for row in result.mappings()]
        return records, total or 0


__all__ = [
    "IdempotencyConflictError",
    "PostgresRecommendationRunStore",
    "RUN_TABLE",
    "RecommendationRunStore",
    "RunRecord",
    "record_to_run_view",
]
