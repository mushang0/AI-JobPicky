"""PostgreSQL state for Feishu record-level incremental processing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FEISHU_SYNC_STATE_TABLE = sa.table(
    "feishu_sync_state",
    sa.column("app_token", sa.String),
    sa.column("table_id", sa.String),
    sa.column("record_id", sa.String),
    sa.column("record_hash", sa.String),
    sa.column("last_modified_time", sa.DateTime(timezone=True)),
    sa.column("last_processed_at", sa.DateTime(timezone=True)),
    sa.column("status", sa.String),
    sa.column("last_error", sa.Text),
)


@dataclass(frozen=True, slots=True)
class FeishuSyncState:
    record_id: str
    record_hash: str
    last_modified_time: datetime | None
    last_processed_at: datetime | None
    status: str
    last_error: str | None


class PostgresFeishuSyncStateStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_many(
        self,
        app_token: str,
        table_id: str,
        record_ids: Sequence[str],
    ) -> dict[str, FeishuSyncState]:
        if not record_ids:
            return {}
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(FEISHU_SYNC_STATE_TABLE).where(
                    FEISHU_SYNC_STATE_TABLE.c.app_token == app_token,
                    FEISHU_SYNC_STATE_TABLE.c.table_id == table_id,
                    FEISHU_SYNC_STATE_TABLE.c.record_id.in_(record_ids),
                )
            )
            return {
                row.record_id: FeishuSyncState(
                    record_id=row.record_id,
                    record_hash=row.record_hash,
                    last_modified_time=row.last_modified_time,
                    last_processed_at=row.last_processed_at,
                    status=row.status,
                    last_error=row.last_error,
                )
                for row in result.mappings()
            }

    async def save(
        self,
        *,
        app_token: str,
        table_id: str,
        record_id: str,
        record_hash: str,
        last_modified_time: datetime | None,
        status: str,
        last_error: str | None,
    ) -> None:
        if status not in {"SUCCEEDED", "SKIPPED", "FAILED"}:
            raise ValueError(f"unsupported Feishu sync status: {status}")
        now = datetime.now(UTC)
        values: Mapping[str, object] = {
            "app_token": app_token,
            "table_id": table_id,
            "record_id": record_id,
            "record_hash": record_hash,
            "last_modified_time": last_modified_time,
            "last_processed_at": now,
            "status": status,
            "last_error": last_error,
        }
        insert = postgresql.insert(FEISHU_SYNC_STATE_TABLE).values(**values)
        async with self._session_factory() as session, session.begin():
            await session.execute(
                insert.on_conflict_do_update(
                    index_elements=["app_token", "table_id", "record_id"],
                    set_={
                        "record_hash": insert.excluded.record_hash,
                        "last_modified_time": insert.excluded.last_modified_time,
                        "last_processed_at": insert.excluded.last_processed_at,
                        "status": insert.excluded.status,
                        "last_error": insert.excluded.last_error,
                    },
                )
            )

    async def reset(self, app_token: str, table_id: str) -> None:
        """Forget processed records for one table before a development rebuild."""
        async with self._session_factory() as session, session.begin():
            await session.execute(
                sa.delete(FEISHU_SYNC_STATE_TABLE).where(
                    FEISHU_SYNC_STATE_TABLE.c.app_token == app_token,
                    FEISHU_SYNC_STATE_TABLE.c.table_id == table_id,
                )
            )


def should_process(state: FeishuSyncState | None, record_hash: str) -> bool:
    return state is None or state.record_hash != record_hash or state.status == "FAILED"


__all__ = [
    "FEISHU_SYNC_STATE_TABLE",
    "FeishuSyncState",
    "PostgresFeishuSyncStateStore",
    "should_process",
]
