from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import JsonValue

from . import __version__
from .api.routers import auth_router, credits_router
from .auth import AccessTokenCodec, AuthService
from .config import Settings
from .contracts import ErrorBody, ErrorCode, HealthView, error_message
from .credits import CreditService
from .errors import ApplicationError
from .infrastructure.auth_store import PostgresAuthStore
from .infrastructure.credit_store import PostgresCreditStore
from .infrastructure.database import create_engine, create_session_factory

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _error_response(
    body: ErrorBody,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = {"X-Request-ID": body.request_id, **(headers or {})}
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body),
        headers=response_headers,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if "*" in settings.cors_allowed_origins:
        raise ValueError("CORS allowed origins must not contain '*'")
    if settings.environment in {"production", "prod"} and (
        settings.jwt_signing_key is None or len(settings.jwt_signing_key.encode()) < 32
    ):
        raise ValueError("JWT signing key must contain at least 32 bytes in production")
    logging.basicConfig(level=settings.log_level)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    auth_store = PostgresAuthStore(session_factory)
    credit_store = PostgresCreditStore(session_factory)
    signing_key = settings.jwt_signing_key or secrets.token_urlsafe(48)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        responses={
            422: {"model": ErrorBody, "description": "Request validation failed"},
            500: {"model": ErrorBody, "description": "Internal server error"},
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.auth_service = AuthService(
        auth_store,
        settings,
        AccessTokenCodec(signing_key, settings),
    )
    app.state.credit_service = CreditService(credit_store, settings.recommendation_cost)
    app.state.credit_store = credit_store

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return _error_response(
            ErrorBody(
                code=exc.code,
                message=error_message(exc.code),
                details=exc.details,
                request_id=_request_id(request),
                run_id=exc.run_id,
            ),
            exc.status_code,
            exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            ErrorBody(
                code=ErrorCode.VALIDATION_ERROR,
                message="请求内容不符合要求。",
                details={"errors": cast(JsonValue, _safe_validation_errors(exc))},
                request_id=_request_id(request),
            ),
            422,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.error(
            "Unhandled application error request_id=%s method=%s path=%s error_type=%s",
            request_id,
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return _error_response(
            ErrorBody(
                code=ErrorCode.INTERNAL_ERROR,
                message="系统暂时无法处理请求，请稍后重试。",
                request_id=request_id,
            ),
            500,
        )

    @app.get("/api/v1/system/health", response_model=HealthView, tags=["system"])
    async def health() -> HealthView:
        return HealthView(
            status="UP",
            service=settings.app_name,
            version=__version__,
            dependencies={},
        )

    app.include_router(auth_router)
    app.include_router(credits_router)

    return app


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, JsonValue]]:
    """Keep validation locations and messages without echoing credentials or request input."""
    safe: list[dict[str, JsonValue]] = []
    for error in exc.errors():
        safe.append(
            {
                "type": cast(JsonValue, error["type"]),
                "loc": cast(JsonValue, jsonable_encoder(error["loc"])),
                "msg": "字段值不符合要求。",
            }
        )
    return safe


__all__ = ["create_app"]
