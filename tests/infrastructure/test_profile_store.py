from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from jobpicky.contracts import (
    EducationLevel,
    ErrorCode,
    ProfileSaveRequest,
    ProfileSnapshot,
    RecruitmentType,
)
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.auth_store import USER_ACCOUNT_TABLE
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.profile_store import (
    PROFILE_SAVE_REQUEST_TABLE,
    PROFILE_TABLE,
    PostgresProfileStore,
)
from jobpicky.profiles import ProfileService

_TEST_DATABASE_URL = os.environ.get("JOBPICKY_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="JOBPICKY_TEST_DATABASE_URL is not set; start the compose db and run migrations",
)

_PROFILE_ID = "itest-profile-1"
_USER_ID = "itest-user-1"


def _snapshot(version: int) -> ProfileSnapshot:
    return ProfileSnapshot(
        id=_PROFILE_ID,
        user_id=_USER_ID,
        version=version,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        target_locations=["上海"],
        target_roles=["后端工程师"],
        recruitment_types=[RecruitmentType.SOCIAL],
        skills=["Python"],
        excluded_roles=[],
        education=EducationLevel.BACHELOR,
        graduation_year=2027,
        expected_salary_min=None,
        experience_summary=None,
        extra_request=None,
        warnings=[],
    )


def _save_request(
    *,
    base_version: int | None = None,
    extra_request: str | None = None,
) -> ProfileSaveRequest:
    return ProfileSaveRequest(
        base_version=base_version,
        target_roles=["后端工程师"],
        target_locations=["上海"],
        recruitment_types=[RecruitmentType.SOCIAL],
        skills=["Python"],
        extra_request=extra_request,
    )


def _store() -> PostgresProfileStore:
    engine = create_engine(_TEST_DATABASE_URL)
    return PostgresProfileStore(create_session_factory(engine))


def _clean() -> None:
    async def delete() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        factory = create_session_factory(engine)
        async with factory() as session:
            await session.execute(
                sa.delete(PROFILE_SAVE_REQUEST_TABLE).where(
                    PROFILE_SAVE_REQUEST_TABLE.c.user_id == _USER_ID
                )
            )
            await session.execute(
                sa.delete(PROFILE_TABLE).where(PROFILE_TABLE.c.user_id == _USER_ID)
            )
            await session.execute(
                sa.delete(USER_ACCOUNT_TABLE).where(USER_ACCOUNT_TABLE.c.id == _USER_ID)
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(delete())


async def _insert_user() -> None:
    engine = create_engine(_TEST_DATABASE_URL)
    factory = create_session_factory(engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    async with factory() as session:
        await session.execute(
            sa.insert(USER_ACCOUNT_TABLE).values(
                id=_USER_ID,
                email="itest-profile-user@example.com",
                password_hash="test-only-hash",
                role="USER",
                status="ACTIVE",
                created_at=now,
                updated_at=now,
                last_login_at=None,
            )
        )
        await session.commit()
    await engine.dispose()


def test_save_then_get_snapshot_roundtrip() -> None:
    _clean()

    async def check() -> None:
        store = _store()
        await store.save_snapshot(_snapshot(version=1))
        snapshot = await store.get_snapshot("itest-user-1", _PROFILE_ID)
        assert snapshot.version == 1
        assert snapshot.target_roles == ["后端工程师"]
        assert snapshot.recruitment_types == ["社招"]
        assert snapshot.skills == ["Python"]

    asyncio.run(check())


def test_save_current_versions_noop_and_idempotency_replay() -> None:
    _clean()

    async def check() -> None:
        await _insert_user()
        store = _store()
        service = ProfileService(
            store,
            now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            id_factory=lambda: _PROFILE_ID,
        )
        first = await service.save_current(
            _USER_ID,
            _save_request(),
            "create",
        )
        second = await service.save_current(
            _USER_ID,
            _save_request(base_version=1, extra_request="远程优先"),
            "update",
        )
        unchanged = await service.save_current(
            _USER_ID,
            _save_request(base_version=2, extra_request="远程优先"),
            "no-change",
        )
        replay = await service.save_current(
            _USER_ID,
            _save_request(),
            "create",
        )

        assert (first.version, second.version, unchanged.version, replay.version) == (1, 2, 2, 1)
        assert (await store.get_version(_USER_ID, _PROFILE_ID, 1)).extra_request is None
        assert (await store.get_current(_USER_ID)).extra_request == "远程优先"

    asyncio.run(check())


def test_concurrent_updates_allow_exactly_one_base_version_winner() -> None:
    _clean()

    async def check() -> None:
        await _insert_user()
        store = _store()
        service = ProfileService(
            store,
            now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            id_factory=lambda: _PROFILE_ID,
        )
        await service.save_current(_USER_ID, _save_request(), "create")

        results = await asyncio.gather(
            service.save_current(
                _USER_ID,
                _save_request(base_version=1, extra_request="方案 A"),
                "update-a",
            ),
            service.save_current(
                _USER_ID,
                _save_request(base_version=1, extra_request="方案 B"),
                "update-b",
            ),
            return_exceptions=True,
        )

        snapshots = [result for result in results if isinstance(result, ProfileSnapshot)]
        errors = [result for result in results if isinstance(result, ApplicationError)]
        assert len(snapshots) == 1
        assert snapshots[0].version == 2
        assert len(errors) == 1
        assert errors[0].code == str(ErrorCode.PROFILE_VERSION_CONFLICT)
        assert (await store.get_current(_USER_ID)).version == 2

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
