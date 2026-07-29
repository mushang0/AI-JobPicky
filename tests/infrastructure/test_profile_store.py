from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from jobpicky.contracts import ErrorCode, ProfileSnapshot
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.profile_store import PROFILE_TABLE, PostgresProfileStore

_TEST_DATABASE_URL = os.environ.get("JOBPICKY_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="JOBPICKY_TEST_DATABASE_URL is not set; start the compose db and run migrations",
)

_PROFILE_ID = "itest-profile-1"


def _snapshot(version: int) -> ProfileSnapshot:
    return ProfileSnapshot(
        id=_PROFILE_ID,
        user_id="itest-user-1",
        version=version,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target_locations=["上海"],
        target_roles=["后端工程师"],
        skills=["Python"],
        excluded_roles=[],
        education="本科",
        graduation_year=2027,
        expected_salary_min=None,
        experience_summary=None,
        extra_request=None,
        warnings=[],
    )


def _store() -> PostgresProfileStore:
    engine = create_engine(_TEST_DATABASE_URL)
    return PostgresProfileStore(create_session_factory(engine))


def _clean() -> None:
    async def delete() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        async with factory() as session:
            await session.execute(sa.delete(PROFILE_TABLE).where(PROFILE_TABLE.c.id == _PROFILE_ID))
            await session.commit()
        await engine.dispose()

    asyncio.run(delete())


def test_save_then_get_snapshot_roundtrip() -> None:
    _clean()

    async def check() -> None:
        store = _store()
        await store.save_snapshot(_snapshot(version=1))
        snapshot = await store.get_snapshot("itest-user-1", _PROFILE_ID)
        assert snapshot.version == 1
        assert snapshot.target_roles == ["后端工程师"]
        assert snapshot.skills == ["Python"]

    asyncio.run(check())


def test_get_snapshot_returns_latest_version() -> None:
    _clean()

    async def check() -> None:
        store = _store()
        await store.save_snapshot(_snapshot(version=1))
        await store.save_snapshot(_snapshot(version=2))
        snapshot = await store.get_snapshot("itest-user-1", _PROFILE_ID)
        assert snapshot.version == 2

    asyncio.run(check())


def test_get_snapshot_scopes_to_user() -> None:
    _clean()

    async def check() -> None:
        store = _store()
        await store.save_snapshot(_snapshot(version=1))
        with pytest.raises(ApplicationError) as error:
            await store.get_snapshot("someone-else", _PROFILE_ID)
        assert error.value.code == str(ErrorCode.NOT_FOUND)

    asyncio.run(check())
