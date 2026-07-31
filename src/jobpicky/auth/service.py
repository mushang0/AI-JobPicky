from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import uuid4

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import Settings
from ..contracts import (
    AccessTokenResponse,
    AuthUserView,
    ErrorCode,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserRole,
)
from ..errors import ApplicationError


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    email: str
    password_hash: str
    role: UserRole
    status: str
    created_at: datetime

    def to_view(self) -> AuthUserView:
        return AuthUserView(
            id=self.id,
            email=self.email,
            role=self.role,
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class SessionSeed:
    id: str
    token_hash: str
    family_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RotationResult:
    status: Literal["ROTATED", "MISSING", "EXPIRED", "REVOKED", "REUSED"]
    user: UserRecord | None = None


class EmailAlreadyExistsError(Exception):
    pass


class AuthStore(Protocol):
    async def create_account_with_bonus(
        self,
        *,
        email: str,
        password_hash: str,
        session: SessionSeed,
        signup_bonus: int,
        now: datetime,
    ) -> UserRecord: ...

    async def get_user_by_email(self, email: str) -> UserRecord | None: ...

    async def get_user(self, user_id: str) -> UserRecord | None: ...

    async def create_login_session(
        self,
        user_id: str,
        session: SessionSeed,
        now: datetime,
    ) -> UserRecord: ...

    async def find_refresh_family(self, token_hash: str) -> str | None: ...

    async def rotate_refresh_session(
        self,
        old_token_hash: str,
        new_session: SessionSeed,
        now: datetime,
    ) -> RotationResult: ...

    async def revoke_refresh_family(self, token_hash: str, now: datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class AccessIdentity:
    user_id: str
    role: UserRole


@dataclass(frozen=True, slots=True)
class LoginSessionResult:
    response: LoginResponse
    refresh_token: str


@dataclass(frozen=True, slots=True)
class RefreshSessionResult:
    response: AccessTokenResponse
    refresh_token: str


class PasswordManager:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def verify_dummy(self, password: str) -> None:
        self.verify(self._dummy_hash, password)


class AccessTokenCodec:
    def __init__(self, signing_key: str, settings: Settings) -> None:
        if len(signing_key.encode()) < 32:
            raise ValueError("JWT signing key must contain at least 32 bytes")
        if settings.jwt_algorithm != "HS256":
            raise ValueError("JWT algorithm must be HS256")
        self._key = signing_key
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._algorithm = settings.jwt_algorithm
        self._ttl_seconds = settings.access_token_ttl_seconds

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def encode(self, user: UserRecord) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "iss": self._issuer,
                "aud": self._audience,
                "sub": user.id,
                "jti": str(uuid4()),
                "iat": now,
                "exp": now + timedelta(seconds=self._ttl_seconds),
                "token_type": "access",
                "role": str(user.role),
            },
            self._key,
            algorithm=self._algorithm,
        )

    def decode(self, token: str) -> AccessIdentity:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": ["iss", "aud", "sub", "jti", "iat", "exp", "token_type", "role"]
                },
            )
            user_id = claims["sub"]
            if not isinstance(user_id, str) or not user_id:
                raise ValueError("invalid subject")
            if claims["token_type"] != "access":
                raise jwt.InvalidTokenError("invalid token type")
            role = UserRole(claims["role"])
        except (KeyError, ValueError, jwt.PyJWTError) as exc:
            raise _authentication_required() from exc
        return AccessIdentity(user_id=user_id, role=role)


class SlidingWindowLimiter:
    # ponytail: process-local buckets are enough for the single-process MVP;
    # move them to a shared store before deploying multiple API workers.
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def ensure_available(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            self._purge(events, now, window_seconds)
            if len(events) >= limit:
                retry_after = max(1, math.ceil(events[0] + window_seconds - now))
                raise ApplicationError(
                    ErrorCode.TOO_MANY_ATTEMPTS,
                    "rate limit exceeded",
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )

    def consume(self, key: str, limit: int, window_seconds: int) -> None:
        self.ensure_available(key, limit, window_seconds)
        with self._lock:
            self._events[key].append(time.monotonic())

    def record(self, key: str, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            self._purge(events, now, window_seconds)
            events.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    @staticmethod
    def _purge(events: deque[float], now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()


class AuthService:
    def __init__(
        self,
        store: AuthStore,
        settings: Settings,
        token_codec: AccessTokenCodec,
        *,
        passwords: PasswordManager | None = None,
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._tokens = token_codec
        self._passwords = passwords or PasswordManager()
        self._limiter = limiter or SlidingWindowLimiter()

    async def register(
        self,
        request: RegisterRequest,
        *,
        client_ip: str = "internal",
    ) -> LoginSessionResult:
        self._limiter.consume(
            f"register-ip:{client_ip}",
            self._settings.register_ip_limit_per_hour,
            3600,
        )
        now = datetime.now(UTC)
        raw_refresh, session = self._new_session(now)
        try:
            user = await self._store.create_account_with_bonus(
                email=request.email,
                password_hash=self._passwords.hash(request.password),
                session=session,
                signup_bonus=self._settings.signup_bonus_credits,
                now=now,
            )
        except EmailAlreadyExistsError as exc:
            raise ApplicationError(
                ErrorCode.EMAIL_ALREADY_REGISTERED,
                "email already registered",
                status_code=409,
            ) from exc
        return LoginSessionResult(
            response=self._login_response(user),
            refresh_token=raw_refresh,
        )

    async def login(
        self,
        request: LoginRequest,
        *,
        client_ip: str = "internal",
    ) -> LoginSessionResult:
        self._limiter.consume(
            f"login-ip:{client_ip}",
            self._settings.login_ip_attempt_limit,
            900,
        )
        email_key = f"login-email:{request.email}"
        self._limiter.ensure_available(
            email_key,
            self._settings.login_email_failure_limit,
            900,
        )
        user = await self._store.get_user_by_email(request.email)
        valid = False
        if user is None:
            self._passwords.verify_dummy(request.password)
        else:
            valid = self._passwords.verify(user.password_hash, request.password)
        if user is None or not valid:
            self._limiter.record(email_key, 900)
            raise ApplicationError(
                ErrorCode.INVALID_CREDENTIALS,
                "invalid credentials",
                status_code=401,
            )
        self._limiter.reset(email_key)
        self._ensure_active(user)
        now = datetime.now(UTC)
        raw_refresh, session = self._new_session(now)
        user = await self._store.create_login_session(user.id, session, now)
        return LoginSessionResult(
            response=self._login_response(user),
            refresh_token=raw_refresh,
        )

    async def refresh(
        self,
        refresh_token: str,
        *,
        client_ip: str = "internal",
    ) -> RefreshSessionResult:
        self._limiter.consume(
            f"refresh-ip:{client_ip}",
            self._settings.refresh_ip_limit_per_minute,
            60,
        )
        old_hash = _hash_refresh_token(refresh_token)
        family_id = await self._store.find_refresh_family(old_hash)
        self._limiter.consume(
            f"refresh-session:{family_id or old_hash}",
            self._settings.refresh_session_limit_per_minute,
            60,
        )
        now = datetime.now(UTC)
        raw_refresh, session = self._new_session(now, family_id=family_id)
        rotation = await self._store.rotate_refresh_session(old_hash, session, now)
        if rotation.status != "ROTATED" or rotation.user is None:
            raise ApplicationError(
                ErrorCode.SESSION_EXPIRED,
                "refresh session is unavailable",
                status_code=401,
            )
        self._ensure_active(rotation.user)
        return RefreshSessionResult(
            response=AccessTokenResponse(
                access_token=self._tokens.encode(rotation.user),
                expires_in=self._tokens.ttl_seconds,
            ),
            refresh_token=raw_refresh,
        )

    async def logout(self, refresh_token: str | None) -> None:
        if refresh_token:
            await self._store.revoke_refresh_family(
                _hash_refresh_token(refresh_token),
                datetime.now(UTC),
            )

    async def get_current_user(self, user_id: str) -> AuthUserView:
        user = await self._store.get_user(user_id)
        if user is None:
            raise _authentication_required()
        self._ensure_active(user)
        return user.to_view()

    async def authenticate_access(self, access_token: str) -> AuthUserView:
        identity = self._tokens.decode(access_token)
        user = await self._store.get_user(identity.user_id)
        if user is None or user.role != identity.role:
            raise _authentication_required()
        self._ensure_active(user)
        return user.to_view()

    def _new_session(
        self,
        now: datetime,
        *,
        family_id: str | None = None,
    ) -> tuple[str, SessionSeed]:
        raw_token = secrets.token_urlsafe(48)
        return raw_token, SessionSeed(
            id=str(uuid4()),
            token_hash=_hash_refresh_token(raw_token),
            family_id=family_id or str(uuid4()),
            expires_at=now + timedelta(seconds=self._settings.refresh_session_ttl_seconds),
        )

    def _login_response(self, user: UserRecord) -> LoginResponse:
        return LoginResponse(
            access_token=self._tokens.encode(user),
            expires_in=self._tokens.ttl_seconds,
            user=user.to_view(),
        )

    @staticmethod
    def _ensure_active(user: UserRecord) -> None:
        if user.status != "ACTIVE":
            raise ApplicationError(
                ErrorCode.ACCOUNT_DISABLED,
                "account disabled",
                status_code=403,
            )


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _authentication_required() -> ApplicationError:
    return ApplicationError(
        ErrorCode.AUTHENTICATION_REQUIRED,
        "authentication required",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = [
    "AccessIdentity",
    "AccessTokenCodec",
    "AuthService",
    "AuthStore",
    "EmailAlreadyExistsError",
    "LoginSessionResult",
    "PasswordManager",
    "RefreshSessionResult",
    "RotationResult",
    "SessionSeed",
    "SlidingWindowLimiter",
    "UserRecord",
]
