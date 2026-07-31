from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ...contracts import (
    AccessTokenResponse,
    AuthUserView,
    ErrorCode,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
)
from ...errors import ApplicationError
from ..dependencies import (
    AuthServiceDependency,
    RequiredUser,
    client_ip,
    validate_browser_origin,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> LoginResponse:
    validate_browser_origin(request)
    result = await service.register(payload, client_ip=client_ip(request))
    _set_refresh_cookie(response, request, result.refresh_token)
    return result.response


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> LoginResponse:
    validate_browser_origin(request)
    result = await service.login(payload, client_ip=client_ip(request))
    _set_refresh_cookie(response, request, result.refresh_token)
    return result.response


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> AccessTokenResponse:
    validate_browser_origin(request)
    settings = request.app.state.settings
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise ApplicationError(
            ErrorCode.SESSION_EXPIRED,
            "refresh cookie is missing",
            status_code=401,
        )
    result = await service.refresh(refresh_token, client_ip=client_ip(request))
    _set_refresh_cookie(response, request, result.refresh_token)
    return result.response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> None:
    validate_browser_origin(request)
    settings = request.app.state.settings
    await service.logout(request.cookies.get(settings.refresh_cookie_name))
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


@router.get("/me", response_model=AuthUserView)
async def me(user: RequiredUser) -> AuthUserView:
    return user


def _set_refresh_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_session_ttl_seconds,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


__all__ = ["router"]
