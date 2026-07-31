from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime

import pytest

from jobpicky.auth.service import (
    AccessTokenCodec,
    AuthService,
    EmailAlreadyExistsError,
    RotationResult,
    SessionSeed,
    UserRecord,
)
from jobpicky.config import Settings
from jobpicky.contracts import ErrorCode, LoginRequest, RegisterRequest
from jobpicky.errors import ApplicationError

_KEY = "test-signing-key-that-is-longer-than-32-bytes"
_PASSWORD = "  exact long password  "


class MemoryAuthStore:
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.sessions: dict[str, dict[str, object]] = {}
        self.signup_balances: dict[str, int] = {}

    async def create_account_with_bonus(
        self,
        *,
        email: str,
        password_hash: str,
        session: SessionSeed,
        signup_bonus: int,
        now: datetime,
    ) -> UserRecord:
        if email in self.users:
            raise EmailAlreadyExistsError(email)
        user = UserRecord(
            id=f"user-{len(self.users) + 1}",
            email=email,
            password_hash=password_hash,
            role="USER",  # type: ignore[arg-type]
            status="ACTIVE",
            created_at=now,
        )
        self.users[email] = user
        self.signup_balances[user.id] = signup_bonus
        self._save_session(user.id, session)
        return user

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        return self.users.get(email)

    async def get_user(self, user_id: str) -> UserRecord | None:
        return next((user for user in self.users.values() if user.id == user_id), None)

    async def create_login_session(
        self,
        user_id: str,
        session: SessionSeed,
        now: datetime,
    ) -> UserRecord:
        self._save_session(user_id, session)
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def find_refresh_family(self, token_hash: str) -> str | None:
        session = self.sessions.get(token_hash)
        return str(session["family_id"]) if session else None

    async def rotate_refresh_session(
        self,
        old_token_hash: str,
        new_session: SessionSeed,
        now: datetime,
    ) -> RotationResult:
        old = self.sessions.get(old_token_hash)
        if old is None:
            return RotationResult("MISSING")
        if old["revoked"]:
            if old["rotated"]:
                family_id = old["family_id"]
                for session in self.sessions.values():
                    if session["family_id"] == family_id:
                        session["revoked"] = True
                return RotationResult("REUSED")
            return RotationResult("REVOKED")
        expires_at = old["expires_at"]
        assert isinstance(expires_at, datetime)
        if expires_at <= now:
            old["revoked"] = True
            return RotationResult("EXPIRED")
        old["revoked"] = True
        old["rotated"] = True
        rotated = replace(new_session, family_id=str(old["family_id"]))
        self._save_session(str(old["user_id"]), rotated)
        user = await self.get_user(str(old["user_id"]))
        assert user is not None
        return RotationResult("ROTATED", user)

    async def revoke_refresh_family(self, token_hash: str, now: datetime) -> None:
        session = self.sessions.get(token_hash)
        if session is None:
            return
        for candidate in self.sessions.values():
            if candidate["family_id"] == session["family_id"]:
                candidate["revoked"] = True

    def _save_session(self, user_id: str, session: SessionSeed) -> None:
        self.sessions[session.token_hash] = {
            "user_id": user_id,
            "family_id": session.family_id,
            "expires_at": session.expires_at,
            "revoked": False,
            "rotated": False,
        }


def _service(login_email_failure_limit: int = 5) -> tuple[AuthService, MemoryAuthStore]:
    settings = Settings(
        environment="test",
        jwt_signing_key=_KEY,
        refresh_cookie_secure=False,
        login_email_failure_limit=login_email_failure_limit,
    )
    store = MemoryAuthStore()
    return AuthService(store, settings, AccessTokenCodec(_KEY, settings)), store


def test_registration_normalizes_email_hashes_password_and_issues_access_token() -> None:
    async def check() -> None:
        service, store = _service()
        result = await service.register(
            RegisterRequest(email="  User@Example.COM ", password=_PASSWORD)
        )

        user = store.users["user@example.com"]
        assert user.password_hash.startswith("$argon2id$")
        assert _PASSWORD not in user.password_hash
        assert store.signup_balances[user.id] == 10_000
        assert result.response.user.email == "user@example.com"
        assert await service.authenticate_access(result.response.access_token) == user.to_view()

    asyncio.run(check())


def test_password_is_verified_verbatim_and_bad_credentials_share_one_error() -> None:
    async def check() -> None:
        service, _ = _service()
        await service.register(RegisterRequest(email="user@example.com", password=_PASSWORD))
        logged_in = await service.login(LoginRequest(email="USER@example.com", password=_PASSWORD))
        assert logged_in.response.user.email == "user@example.com"

        for email, password in [
            ("missing@example.com", _PASSWORD),
            ("user@example.com", _PASSWORD.strip()),
        ]:
            with pytest.raises(ApplicationError) as error:
                await service.login(LoginRequest(email=email, password=password))
            assert error.value.code == str(ErrorCode.INVALID_CREDENTIALS)
            assert error.value.status_code == 401

    asyncio.run(check())


def test_refresh_rotation_detects_reuse_and_revokes_the_token_family() -> None:
    async def check() -> None:
        service, _ = _service()
        registered = await service.register(
            RegisterRequest(email="user@example.com", password=_PASSWORD)
        )
        refreshed = await service.refresh(registered.refresh_token)
        assert refreshed.refresh_token != registered.refresh_token

        with pytest.raises(ApplicationError) as reused:
            await service.refresh(registered.refresh_token)
        assert reused.value.code == str(ErrorCode.SESSION_EXPIRED)

        with pytest.raises(ApplicationError) as revoked:
            await service.refresh(refreshed.refresh_token)
        assert revoked.value.code == str(ErrorCode.SESSION_EXPIRED)

    asyncio.run(check())


def test_login_failure_limit_returns_retry_after_without_permanent_lock() -> None:
    async def check() -> None:
        service, _ = _service(login_email_failure_limit=2)
        request = LoginRequest(email="missing@example.com", password=_PASSWORD)
        for _ in range(2):
            with pytest.raises(ApplicationError) as invalid:
                await service.login(request)
            assert invalid.value.code == str(ErrorCode.INVALID_CREDENTIALS)

        with pytest.raises(ApplicationError) as limited:
            await service.login(request)
        assert limited.value.code == str(ErrorCode.TOO_MANY_ATTEMPTS)
        assert int(limited.value.headers["Retry-After"]) > 0

    asyncio.run(check())


def test_invalid_access_token_uses_bearer_authentication_error() -> None:
    async def check() -> None:
        service, _ = _service()
        with pytest.raises(ApplicationError) as error:
            await service.authenticate_access("not-a-jwt")
        assert error.value.code == str(ErrorCode.AUTHENTICATION_REQUIRED)
        assert error.value.headers == {"WWW-Authenticate": "Bearer"}

    asyncio.run(check())
