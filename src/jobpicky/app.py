from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .config import Settings
from .contracts import ErrorBody, ErrorCode, HealthView
from .errors import ApplicationError

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _error_response(body: ErrorBody, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body),
        headers={"X-Request-ID": body.request_id},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        responses={
            422: {"model": ErrorBody, "description": "Request validation failed"},
            500: {"model": ErrorBody, "description": "Internal server error"},
        },
    )
    app.state.settings = settings

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
                message=exc.message,
                details=exc.details,
                request_id=_request_id(request),
                run_id=exc.run_id,
            ),
            exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            ErrorBody(
                code=ErrorCode.VALIDATION_ERROR,
                message="Request validation failed.",
                details={"errors": jsonable_encoder(exc.errors())},
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
                message="An unexpected error occurred.",
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

    return app


__all__ = ["create_app"]
