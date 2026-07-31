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
from .api.routers import (
    auth_router,
    credits_router,
    jobs_router,
    profiles_router,
    recommendations_router,
    saved_jobs_router,
)
from .auth import AccessTokenCodec, AuthService
from .catalog.service import JobPoolService
from .config import Settings
from .contracts import ErrorBody, ErrorCode, HealthView, error_message
from .credits import CreditService
from .errors import ApplicationError
from .infrastructure.auth_store import PostgresAuthStore
from .infrastructure.credit_store import PostgresCreditStore
from .infrastructure.database import create_engine, create_session_factory
from .infrastructure.embeddings import LocalBGEEmbedding
from .infrastructure.job_catalog import PostgresJobCatalog
from .infrastructure.job_pool_store import PostgresJobPoolStore
from .infrastructure.llm_evaluator import DashScopeJobEvaluator
from .infrastructure.profile_store import PostgresProfileStore
from .infrastructure.recommendation_store import PostgresRecommendationStore
from .infrastructure.saved_job_store import PostgresSavedJobStore
from .matching import BaselineMatchingService
from .orchestration import RecommendationRunService
from .profiles import ProfileService

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
    if settings.environment in {"production", "prod"} and not settings.refresh_cookie_secure:
        raise ValueError("refresh cookie must be secure in production")
    logging.basicConfig(level=settings.log_level)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    auth_store = PostgresAuthStore(session_factory)
    credit_store = PostgresCreditStore(session_factory)
    job_pool_store = PostgresJobPoolStore(session_factory)
    profile_store = PostgresProfileStore(session_factory)
    saved_job_store = PostgresSavedJobStore(session_factory)
    embedding = LocalBGEEmbedding(
        settings.embedding_model_path,
        model_revision=settings.embedding_model_revision,
        query_timeout_seconds=settings.embedding_query_timeout_seconds,
        batch_timeout_seconds=settings.embedding_backfill_timeout_seconds,
    )
    job_catalog = PostgresJobCatalog(session_factory, embedding)
    recommendation_store = PostgresRecommendationStore(session_factory, credit_store)
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
    app.state.job_pool_service = JobPoolService(job_pool_store, saved_job_store, settings)
    app.state.profile_service = ProfileService(
        profile_store,
        idempotency_key_max_length=settings.idempotency_key_max_length,
    )
    app.state.recommendation_service = RecommendationRunService(
        recommendation_store,
        profile_store,
        job_catalog,
        BaselineMatchingService(),
        DashScopeJobEvaluator(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        ),
        settings.model_config_version,
        recommendation_cost=settings.recommendation_cost,
        candidate_limit=settings.recommendation_candidate_limit,
        evaluation_batch_size=settings.evaluation_batch_size,
    )

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
    app.include_router(jobs_router)
    app.include_router(profiles_router)
    app.include_router(recommendations_router)
    app.include_router(saved_jobs_router)

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
