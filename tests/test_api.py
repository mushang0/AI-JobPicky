from typing import Annotated
from uuid import UUID

import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from jobpicky.app import create_app
from jobpicky.config import Settings
from jobpicky.contracts import ErrorCode
from jobpicky.errors import ApplicationError


def test_health_and_openapi_are_available() -> None:
    app = create_app(Settings(app_name="JobPicky Test", environment="test"))

    with TestClient(app) as client:
        response = client.get("/api/v1/system/health")
        schema = client.get("/openapi.json").json()

    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert response.json()["service"] == "JobPicky Test"
    UUID(response.headers["X-Request-ID"])
    assert "/api/v1/system/health" in schema["paths"]


def test_public_errors_have_stable_shape_and_request_id() -> None:
    app = create_app(Settings(environment="test"))

    @app.get("/probe/validation")
    async def validation_probe(limit: Annotated[int, Query(gt=0)]) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/probe/not-found")
    async def not_found_probe() -> None:
        raise ApplicationError(
            ErrorCode.NOT_FOUND,
            "The requested resource was not found.",
            status_code=404,
        )

    with TestClient(app) as client:
        invalid = client.get("/probe/validation", params={"limit": 0})
        missing = client.get("/probe/not-found")

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_ERROR"
    assert invalid.json()["details"]["errors"]
    assert invalid.json()["request_id"] == invalid.headers["X-Request-ID"]

    assert missing.status_code == 404
    assert missing.json() == {
        "code": "NOT_FOUND",
        "message": "The requested resource was not found.",
        "details": {},
        "request_id": missing.headers["X-Request-ID"],
        "run_id": None,
    }


def test_unexpected_errors_do_not_expose_internal_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(Settings(environment="test"))

    @app.get("/probe/failure")
    async def failure_probe() -> None:
        raise RuntimeError("database password should stay private")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/probe/failure")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["details"] == {}
    assert "password" not in response.text
    assert "password" not in caplog.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
