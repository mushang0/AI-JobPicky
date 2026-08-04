from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from jobpicky.api.dependencies import require_user
from jobpicky.app import create_app
from jobpicky.config import Settings
from jobpicky.contracts import AuthUserView, UserRole
from jobpicky.profiles import ProfileService

from .test_service import FakeProfileParser, MemoryProfileStore, service

USER = AuthUserView(
    id="user-1",
    email="user@example.com",
    role=UserRole.USER,
    created_at=datetime(2026, 8, 1, tzinfo=UTC),
)


def app_with_user():
    app = create_app(Settings(environment="test"))
    app.state.profile_service = service(MemoryProfileStore())
    app.dependency_overrides[require_user] = lambda: USER
    return app


def payload(*, base_version: int | None = None, role: str = "Python 后端工程师"):
    return {
        "base_version": base_version,
        "target_roles": [role],
        "target_locations": ["上海"],
        "recruitment_types": ["社招"],
        "skills": ["Python"],
        "excluded_roles": [],
    }


def test_profile_routes_require_identity_and_report_missing_profile() -> None:
    anonymous = create_app(Settings(environment="test"))
    with TestClient(anonymous) as client:
        unauthorized = client.get("/api/v1/user/profiles/current")
        unauthorized_import = client.post(
            "/api/v1/user/profile-imports",
            files={"file": ("resume.txt", b"Python backend resume content", "text/plain")},
        )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert unauthorized_import.status_code == 401
    assert unauthorized_import.json()["code"] == "AUTHENTICATION_REQUIRED"

    with TestClient(app_with_user()) as client:
        missing = client.get("/api/v1/user/profiles/current")
    assert missing.status_code == 404
    assert missing.json()["code"] == "PROFILE_NOT_FOUND"


def test_create_read_update_and_replay_current_profile() -> None:
    with TestClient(app_with_user()) as client:
        created = client.put(
            "/api/v1/user/profiles/current",
            json=payload(),
            headers={"Idempotency-Key": "create-profile"},
        )
        read = client.get("/api/v1/user/profiles/current")
        updated = client.put(
            "/api/v1/user/profiles/current",
            json=payload(base_version=1, role="平台后端工程师"),
            headers={"Idempotency-Key": "update-profile"},
        )
        replay = client.put(
            "/api/v1/user/profiles/current",
            json=payload(),
            headers={"Idempotency-Key": "create-profile"},
        )

    assert created.status_code == 201
    assert created.json()["version"] == 1
    assert "user_id" not in created.json()
    assert read.status_code == 200
    assert read.json() == created.json()
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["id"] == created.json()["id"]
    assert replay.status_code == 201
    assert replay.json() == created.json()


def test_profile_save_validates_header_server_fields_and_conflicts() -> None:
    with TestClient(app_with_user()) as client:
        missing_key = client.put("/api/v1/user/profiles/current", json=payload())
        long_key = client.put(
            "/api/v1/user/profiles/current",
            json=payload(),
            headers={"Idempotency-Key": "x" * 129},
        )
        server_field = client.put(
            "/api/v1/user/profiles/current",
            json={**payload(), "warnings": []},
            headers={"Idempotency-Key": "server-field"},
        )
        created = client.put(
            "/api/v1/user/profiles/current",
            json=payload(),
            headers={"Idempotency-Key": "create"},
        )
        stale = client.put(
            "/api/v1/user/profiles/current",
            json=payload(base_version=2, role="其他岗位"),
            headers={"Idempotency-Key": "stale"},
        )
        reused = client.put(
            "/api/v1/user/profiles/current",
            json=payload(role="其他岗位"),
            headers={"Idempotency-Key": "create"},
        )

    assert missing_key.status_code == 422
    assert long_key.status_code == 422
    assert server_field.status_code == 422
    assert created.status_code == 201
    assert stale.status_code == 409
    assert stale.json()["code"] == "PROFILE_VERSION_CONFLICT"
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_resume_upload_returns_an_unsaved_profile_draft() -> None:
    app = app_with_user()
    store = MemoryProfileStore()
    app.state.profile_service = ProfileService(store, parser=FakeProfileParser())

    with TestClient(app) as client:
        imported = client.post(
            "/api/v1/user/profile-imports",
            files={
                "file": (
                    "resume.txt",
                    "使用 Python 和 FastAPI 负责后端接口及异步任务开发。".encode(),
                    "text/plain",
                )
            },
        )
        current = client.get("/api/v1/user/profiles/current")
        unsupported = client.post(
            "/api/v1/user/profile-imports",
            files={"file": ("resume.doc", b"legacy word resume content", "application/msword")},
        )

    assert imported.status_code == 200
    assert imported.json()["draft"]["skills"] == ["Python"]
    assert "base_version" not in imported.json()["draft"]
    assert current.status_code == 404
    assert store.snapshots == {}
    assert unsupported.status_code == 415
