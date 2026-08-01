from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobpicky.app import create_app
from jobpicky.config import Settings
from jobpicky.contracts import CreditSummary

from .test_service import _KEY, _PASSWORD, _service


class StaticCreditService:
    async def get_summary(self, user_id: str) -> CreditSummary:
        return CreditSummary(balance=10_000, recommendation_cost=100)


def _app() -> FastAPI:
    settings = Settings(
        environment="test",
        jwt_signing_key=_KEY,
        refresh_cookie_secure=False,
    )
    app = create_app(settings)
    auth_service, _ = _service()
    app.state.auth_service = auth_service
    app.state.credit_service = StaticCreditService()
    return app


def test_register_me_refresh_credits_and_logout_are_real_http_flows() -> None:
    with TestClient(_app()) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "User@Example.com", "password": _PASSWORD},
            headers={"Origin": "http://localhost:3000"},
        )
        assert registered.status_code == 201
        assert registered.json()["user"]["email"] == "user@example.com"
        assert "refresh_token" not in registered.json()
        cookie = registered.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/api/v1/auth" in cookie

        access_token = registered.json()["access_token"]
        current = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert current.status_code == 200
        assert current.json()["email"] == "user@example.com"

        credits = client.get(
            "/api/v1/user/credits",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert credits.json() == {"balance": 10_000, "recommendation_cost": 100}

        refreshed = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "http://localhost:3000"},
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"] != access_token

        logged_out = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "http://localhost:3000"},
        )
        assert logged_out.status_code == 204
        assert "Max-Age=0" in logged_out.headers["set-cookie"]

        expired = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "http://localhost:3000"},
        )
        assert expired.status_code == 401
        assert expired.json()["code"] == "SESSION_EXPIRED"


def test_required_identity_and_browser_origin_errors_are_stable() -> None:
    with TestClient(_app()) as client:
        missing = client.get("/api/v1/auth/me")
        forbidden = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": _PASSWORD},
            headers={"Origin": "https://evil.example"},
        )

    assert missing.status_code == 401
    assert missing.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert missing.headers["www-authenticate"] == "Bearer"
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"


def test_validation_errors_do_not_echo_passwords() -> None:
    secret = "12345"
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": secret},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert secret not in response.text
