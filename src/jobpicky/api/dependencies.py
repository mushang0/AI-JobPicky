from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..auth import AuthService
from ..catalog.service import JobPoolService
from ..contracts import AuthUserView, ErrorCode
from ..credits import CreditService
from ..errors import ApplicationError
from ..profiles import ProfileService

_bearer = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth_service)


def get_credit_service(request: Request) -> CreditService:
    return cast(CreditService, request.app.state.credit_service)


def get_job_pool_service(request: Request) -> JobPoolService:
    return cast(JobPoolService, request.app.state.job_pool_service)


def get_profile_service(request: Request) -> ProfileService:
    return cast(ProfileService, request.app.state.profile_service)


async def optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUserView | None:
    if credentials is None:
        return None
    if credentials.scheme.casefold() != "bearer":
        raise _authentication_required()
    return await get_auth_service(request).authenticate_access(credentials.credentials)


async def require_user(
    user: Annotated[AuthUserView | None, Depends(optional_user)],
) -> AuthUserView:
    if user is None:
        raise _authentication_required()
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def validate_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    allowed = request.app.state.settings.cors_allowed_origins
    if origin is not None and origin not in allowed:
        raise ApplicationError(
            ErrorCode.FORBIDDEN,
            "origin is not allowed",
            status_code=403,
        )


def _authentication_required() -> ApplicationError:
    return ApplicationError(
        ErrorCode.AUTHENTICATION_REQUIRED,
        "authentication required",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
CreditServiceDependency = Annotated[CreditService, Depends(get_credit_service)]
JobPoolServiceDependency = Annotated[JobPoolService, Depends(get_job_pool_service)]
ProfileServiceDependency = Annotated[ProfileService, Depends(get_profile_service)]
OptionalUser = Annotated[AuthUserView | None, Depends(optional_user)]
RequiredUser = Annotated[AuthUserView, Depends(require_user)]

__all__ = [
    "AuthServiceDependency",
    "CreditServiceDependency",
    "JobPoolServiceDependency",
    "ProfileServiceDependency",
    "OptionalUser",
    "RequiredUser",
    "client_ip",
    "get_auth_service",
    "get_credit_service",
    "get_job_pool_service",
    "get_profile_service",
    "optional_user",
    "require_user",
    "validate_browser_origin",
]
