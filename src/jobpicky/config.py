from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
_COOKIE_SAMESITE_VALUES = {"lax", "strict", "none"}

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky"
_DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "JobPicky"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = _DEFAULT_DATABASE_URL
    embedding_provider: str = "local"
    embedding_model_path: str | None = None
    embedding_model_revision: str | None = None
    embedding_query_timeout_seconds: float = 5.0
    embedding_backfill_timeout_seconds: float = 60.0
    embedding_batch_size: int = 32
    llm_provider: str = "dashscope"
    llm_model: str | None = None
    llm_base_url: str = _DEFAULT_DASHSCOPE_BASE_URL
    dashscope_api_key: str | None = None
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 1
    evaluation_batch_size: int = 10
    model_config_version: str = "recommendation-v1"

    job_pool_default_page_size: int = 30
    job_pool_public_page_size_max: int = 30
    job_pool_authenticated_page_size_max: int = 100
    recommendation_default_page_size: int = 10
    recommendation_page_size_max: int = 50
    recommendation_run_default_page_size: int = 20
    recommendation_run_page_size_max: int = 100
    recommendation_result_default_page_size: int = 10
    recommendation_result_page_size_max: int = 50
    saved_jobs_default_page_size: int = 10
    saved_jobs_page_size_max: int = 50
    recommendation_candidate_limit: int = 50
    signup_bonus_credits: int = 10_000
    recommendation_cost: int = 100
    job_description_preview_length: int = 240
    idempotency_key_max_length: int = 128

    jwt_issuer: str = "jobpicky"
    jwt_audience: str = "jobpicky-api"
    jwt_algorithm: str = "HS256"
    jwt_signing_key: str | None = None
    access_token_ttl_seconds: int = 900
    refresh_session_ttl_seconds: int = 2_592_000
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: str = "lax"
    refresh_cookie_path: str = "/api/v1/auth"
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:3000",)
    register_ip_limit_per_hour: int = 5
    login_email_failure_limit: int = 5
    login_ip_attempt_limit: int = 30
    refresh_session_limit_per_minute: int = 10
    refresh_ip_limit_per_minute: int = 60

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if environ is None else environ
        defaults = cls()
        app_name = values.get("JOBPICKY_APP_NAME", defaults.app_name).strip()
        environment = values.get("JOBPICKY_ENVIRONMENT", defaults.environment).strip().lower()
        log_level = values.get("JOBPICKY_LOG_LEVEL", defaults.log_level).strip().upper()
        database_url = values.get("JOBPICKY_DATABASE_URL", defaults.database_url).strip()
        embedding_provider = (
            values.get("JOBPICKY_EMBEDDING_PROVIDER", defaults.embedding_provider).strip().lower()
        )
        embedding_model_path = _optional_value(
            values.get("JOBPICKY_EMBEDDING_MODEL_PATH", defaults.embedding_model_path)
        )
        embedding_model_revision = _optional_value(
            values.get("JOBPICKY_EMBEDDING_MODEL_REVISION", defaults.embedding_model_revision)
        )
        embedding_query_timeout_seconds = _read_positive_float(
            values.get(
                "JOBPICKY_EMBEDDING_QUERY_TIMEOUT_SECONDS",
                str(defaults.embedding_query_timeout_seconds),
            ),
            "JOBPICKY_EMBEDDING_QUERY_TIMEOUT_SECONDS",
        )
        embedding_backfill_timeout_seconds = _read_positive_float(
            values.get(
                "JOBPICKY_EMBEDDING_BACKFILL_TIMEOUT_SECONDS",
                str(defaults.embedding_backfill_timeout_seconds),
            ),
            "JOBPICKY_EMBEDDING_BACKFILL_TIMEOUT_SECONDS",
        )
        embedding_batch_size = _read_positive_int(
            values.get("JOBPICKY_EMBEDDING_BATCH_SIZE", str(defaults.embedding_batch_size)),
            "JOBPICKY_EMBEDDING_BATCH_SIZE",
        )
        llm_provider = values.get("JOBPICKY_LLM_PROVIDER", defaults.llm_provider).strip().lower()
        llm_model = _optional_value(values.get("JOBPICKY_LLM_MODEL", defaults.llm_model))
        llm_base_url = values.get("JOBPICKY_LLM_BASE_URL", defaults.llm_base_url).strip()
        dashscope_api_key = _optional_value(
            values.get("JOBPICKY_DASHSCOPE_API_KEY", defaults.dashscope_api_key)
        )
        llm_timeout_seconds = _read_positive_float(
            values.get("JOBPICKY_LLM_TIMEOUT_SECONDS", str(defaults.llm_timeout_seconds)),
            "JOBPICKY_LLM_TIMEOUT_SECONDS",
        )
        llm_max_retries = _read_non_negative_int(
            values.get("JOBPICKY_LLM_MAX_RETRIES", str(defaults.llm_max_retries)),
            "JOBPICKY_LLM_MAX_RETRIES",
        )
        evaluation_batch_size = _read_positive_int(
            values.get("JOBPICKY_EVALUATION_BATCH_SIZE", str(defaults.evaluation_batch_size)),
            "JOBPICKY_EVALUATION_BATCH_SIZE",
        )
        model_config_version = values.get(
            "JOBPICKY_MODEL_CONFIG_VERSION", defaults.model_config_version
        ).strip()

        job_pool_default_page_size = _read_positive_int(
            values.get(
                "JOBPICKY_JOB_POOL_DEFAULT_PAGE_SIZE", str(defaults.job_pool_default_page_size)
            ),
            "JOBPICKY_JOB_POOL_DEFAULT_PAGE_SIZE",
        )
        job_pool_public_page_size_max = _read_positive_int(
            values.get(
                "JOBPICKY_JOB_POOL_PUBLIC_PAGE_SIZE_MAX",
                str(defaults.job_pool_public_page_size_max),
            ),
            "JOBPICKY_JOB_POOL_PUBLIC_PAGE_SIZE_MAX",
        )
        job_pool_authenticated_page_size_max = _read_positive_int(
            values.get(
                "JOBPICKY_JOB_POOL_AUTHENTICATED_PAGE_SIZE_MAX",
                str(defaults.job_pool_authenticated_page_size_max),
            ),
            "JOBPICKY_JOB_POOL_AUTHENTICATED_PAGE_SIZE_MAX",
        )
        recommendation_default_page_size = _read_positive_int(
            values.get(
                "JOBPICKY_RECOMMENDATION_DEFAULT_PAGE_SIZE",
                str(defaults.recommendation_default_page_size),
            ),
            "JOBPICKY_RECOMMENDATION_DEFAULT_PAGE_SIZE",
        )
        recommendation_page_size_max = _read_positive_int(
            values.get(
                "JOBPICKY_RECOMMENDATION_PAGE_SIZE_MAX",
                str(defaults.recommendation_page_size_max),
            ),
            "JOBPICKY_RECOMMENDATION_PAGE_SIZE_MAX",
        )
        recommendation_run_default_page_size = _read_positive_int(
            values.get(
                "JOBPICKY_RECOMMENDATION_RUN_DEFAULT_PAGE_SIZE",
                str(defaults.recommendation_run_default_page_size),
            ),
            "JOBPICKY_RECOMMENDATION_RUN_DEFAULT_PAGE_SIZE",
        )
        recommendation_run_page_size_max = _read_positive_int(
            values.get(
                "JOBPICKY_RECOMMENDATION_RUN_PAGE_SIZE_MAX",
                str(defaults.recommendation_run_page_size_max),
            ),
            "JOBPICKY_RECOMMENDATION_RUN_PAGE_SIZE_MAX",
        )
        recommendation_result_default_page_size = _read_positive_int(
            values.get(
                "JOBPICKY_RECOMMENDATION_RESULT_DEFAULT_PAGE_SIZE",
                str(defaults.recommendation_result_default_page_size),
            ),
            "JOBPICKY_RECOMMENDATION_RESULT_DEFAULT_PAGE_SIZE",
        )
        recommendation_result_page_size_max = _read_positive_int(
            values.get(
                "JOBPICKY_RECOMMENDATION_RESULT_PAGE_SIZE_MAX",
                str(defaults.recommendation_result_page_size_max),
            ),
            "JOBPICKY_RECOMMENDATION_RESULT_PAGE_SIZE_MAX",
        )
        saved_jobs_default_page_size = _read_positive_int(
            values.get(
                "JOBPICKY_SAVED_JOBS_DEFAULT_PAGE_SIZE", str(defaults.saved_jobs_default_page_size)
            ),
            "JOBPICKY_SAVED_JOBS_DEFAULT_PAGE_SIZE",
        )
        saved_jobs_page_size_max = _read_positive_int(
            values.get("JOBPICKY_SAVED_JOBS_PAGE_SIZE_MAX", str(defaults.saved_jobs_page_size_max)),
            "JOBPICKY_SAVED_JOBS_PAGE_SIZE_MAX",
        )
        recommendation_candidate_limit = _read_positive_int(
            values.get(
                "JOBPICKY_RECOMMENDATION_CANDIDATE_LIMIT",
                str(defaults.recommendation_candidate_limit),
            ),
            "JOBPICKY_RECOMMENDATION_CANDIDATE_LIMIT",
        )
        signup_bonus_credits = _read_non_negative_int(
            values.get("JOBPICKY_SIGNUP_BONUS_CREDITS", str(defaults.signup_bonus_credits)),
            "JOBPICKY_SIGNUP_BONUS_CREDITS",
        )
        recommendation_cost = _read_positive_int(
            values.get("JOBPICKY_RECOMMENDATION_COST", str(defaults.recommendation_cost)),
            "JOBPICKY_RECOMMENDATION_COST",
        )
        job_description_preview_length = _read_positive_int(
            values.get(
                "JOBPICKY_JOB_DESCRIPTION_PREVIEW_LENGTH",
                str(defaults.job_description_preview_length),
            ),
            "JOBPICKY_JOB_DESCRIPTION_PREVIEW_LENGTH",
        )
        idempotency_key_max_length = _read_positive_int(
            values.get(
                "JOBPICKY_IDEMPOTENCY_KEY_MAX_LENGTH",
                str(defaults.idempotency_key_max_length),
            ),
            "JOBPICKY_IDEMPOTENCY_KEY_MAX_LENGTH",
        )

        jwt_issuer = values.get("JOBPICKY_JWT_ISSUER", defaults.jwt_issuer).strip()
        jwt_audience = values.get("JOBPICKY_JWT_AUDIENCE", defaults.jwt_audience).strip()
        jwt_algorithm = values.get("JOBPICKY_JWT_ALGORITHM", defaults.jwt_algorithm).strip()
        jwt_signing_key = _optional_value(
            values.get("JOBPICKY_JWT_SIGNING_KEY", defaults.jwt_signing_key)
        )
        access_token_ttl_seconds = _read_positive_int(
            values.get("JOBPICKY_ACCESS_TOKEN_TTL_SECONDS", str(defaults.access_token_ttl_seconds)),
            "JOBPICKY_ACCESS_TOKEN_TTL_SECONDS",
        )
        refresh_session_ttl_seconds = _read_positive_int(
            values.get(
                "JOBPICKY_REFRESH_SESSION_TTL_SECONDS",
                str(defaults.refresh_session_ttl_seconds),
            ),
            "JOBPICKY_REFRESH_SESSION_TTL_SECONDS",
        )
        refresh_cookie_name = values.get(
            "JOBPICKY_REFRESH_COOKIE_NAME", defaults.refresh_cookie_name
        ).strip()
        refresh_cookie_secure = _read_bool(
            values.get("JOBPICKY_REFRESH_COOKIE_SECURE", str(defaults.refresh_cookie_secure)),
            "JOBPICKY_REFRESH_COOKIE_SECURE",
        )
        refresh_cookie_samesite = (
            values.get("JOBPICKY_REFRESH_COOKIE_SAMESITE", defaults.refresh_cookie_samesite)
            .strip()
            .lower()
        )
        refresh_cookie_path = values.get(
            "JOBPICKY_REFRESH_COOKIE_PATH", defaults.refresh_cookie_path
        ).strip()
        cors_allowed_origins = _read_origins(
            values.get("JOBPICKY_CORS_ALLOWED_ORIGINS"), defaults.cors_allowed_origins
        )
        register_ip_limit_per_hour = _read_positive_int(
            values.get(
                "JOBPICKY_REGISTER_IP_LIMIT_PER_HOUR",
                str(defaults.register_ip_limit_per_hour),
            ),
            "JOBPICKY_REGISTER_IP_LIMIT_PER_HOUR",
        )
        login_email_failure_limit = _read_positive_int(
            values.get(
                "JOBPICKY_LOGIN_EMAIL_FAILURE_LIMIT",
                str(defaults.login_email_failure_limit),
            ),
            "JOBPICKY_LOGIN_EMAIL_FAILURE_LIMIT",
        )
        login_ip_attempt_limit = _read_positive_int(
            values.get("JOBPICKY_LOGIN_IP_ATTEMPT_LIMIT", str(defaults.login_ip_attempt_limit)),
            "JOBPICKY_LOGIN_IP_ATTEMPT_LIMIT",
        )
        refresh_session_limit_per_minute = _read_positive_int(
            values.get(
                "JOBPICKY_REFRESH_SESSION_LIMIT_PER_MINUTE",
                str(defaults.refresh_session_limit_per_minute),
            ),
            "JOBPICKY_REFRESH_SESSION_LIMIT_PER_MINUTE",
        )
        refresh_ip_limit_per_minute = _read_positive_int(
            values.get(
                "JOBPICKY_REFRESH_IP_LIMIT_PER_MINUTE",
                str(defaults.refresh_ip_limit_per_minute),
            ),
            "JOBPICKY_REFRESH_IP_LIMIT_PER_MINUTE",
        )

        if not app_name:
            raise ValueError("JOBPICKY_APP_NAME must not be empty")
        if not environment:
            raise ValueError("JOBPICKY_ENVIRONMENT must not be empty")
        if log_level not in _LOG_LEVELS:
            raise ValueError(f"JOBPICKY_LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        if not database_url:
            raise ValueError("JOBPICKY_DATABASE_URL must not be empty")
        if embedding_provider != "local":
            raise ValueError("JOBPICKY_EMBEDDING_PROVIDER must be 'local'")
        if llm_provider != "dashscope":
            raise ValueError("JOBPICKY_LLM_PROVIDER must be 'dashscope'")
        if not llm_base_url:
            raise ValueError("JOBPICKY_LLM_BASE_URL must not be empty")
        if not model_config_version:
            raise ValueError("JOBPICKY_MODEL_CONFIG_VERSION must not be empty")
        if job_pool_default_page_size > job_pool_authenticated_page_size_max:
            raise ValueError("JOBPICKY_JOB_POOL_DEFAULT_PAGE_SIZE exceeds authenticated page limit")
        if job_pool_public_page_size_max > job_pool_authenticated_page_size_max:
            raise ValueError("JOBPICKY_JOB_POOL_PUBLIC_PAGE_SIZE_MAX exceeds authenticated limit")
        if recommendation_default_page_size > recommendation_page_size_max:
            raise ValueError("JOBPICKY_RECOMMENDATION_DEFAULT_PAGE_SIZE exceeds page limit")
        if recommendation_run_default_page_size > recommendation_run_page_size_max:
            raise ValueError("JOBPICKY_RECOMMENDATION_RUN_DEFAULT_PAGE_SIZE exceeds page limit")
        if recommendation_result_default_page_size > recommendation_result_page_size_max:
            raise ValueError("JOBPICKY_RECOMMENDATION_RESULT_DEFAULT_PAGE_SIZE exceeds page limit")
        if saved_jobs_default_page_size > saved_jobs_page_size_max:
            raise ValueError("JOBPICKY_SAVED_JOBS_DEFAULT_PAGE_SIZE exceeds page limit")
        if recommendation_candidate_limit > 50:
            raise ValueError("JOBPICKY_RECOMMENDATION_CANDIDATE_LIMIT must not exceed 50")
        if not jwt_issuer or not jwt_audience:
            raise ValueError("JOBPICKY_JWT_ISSUER and JOBPICKY_JWT_AUDIENCE must not be empty")
        if jwt_algorithm != "HS256":
            raise ValueError("JOBPICKY_JWT_ALGORITHM must be 'HS256'")
        if not refresh_cookie_name or not refresh_cookie_path:
            raise ValueError("refresh cookie name and path must not be empty")
        if refresh_cookie_samesite not in _COOKIE_SAMESITE_VALUES:
            raise ValueError(
                f"JOBPICKY_REFRESH_COOKIE_SAMESITE must be one of {sorted(_COOKIE_SAMESITE_VALUES)}"
            )
        if refresh_cookie_samesite == "none" and not refresh_cookie_secure:
            raise ValueError("SameSite=None requires JOBPICKY_REFRESH_COOKIE_SECURE=true")
        if any(origin == "*" for origin in cors_allowed_origins):
            raise ValueError("JOBPICKY_CORS_ALLOWED_ORIGINS must not contain '*'")
        if environment in {"production", "prod"} and (
            jwt_signing_key is None or len(jwt_signing_key.encode()) < 32
        ):
            raise ValueError(
                "JOBPICKY_JWT_SIGNING_KEY must contain at least 32 bytes in production"
            )
        if environment in {"production", "prod"} and not refresh_cookie_secure:
            raise ValueError("JOBPICKY_REFRESH_COOKIE_SECURE must be true in production")

        return cls(
            app_name=app_name,
            environment=environment,
            log_level=log_level,
            database_url=database_url,
            embedding_provider=embedding_provider,
            embedding_model_path=embedding_model_path,
            embedding_model_revision=embedding_model_revision,
            embedding_query_timeout_seconds=embedding_query_timeout_seconds,
            embedding_backfill_timeout_seconds=embedding_backfill_timeout_seconds,
            embedding_batch_size=embedding_batch_size,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
            dashscope_api_key=dashscope_api_key,
            llm_timeout_seconds=llm_timeout_seconds,
            llm_max_retries=llm_max_retries,
            evaluation_batch_size=evaluation_batch_size,
            model_config_version=model_config_version,
            job_pool_default_page_size=job_pool_default_page_size,
            job_pool_public_page_size_max=job_pool_public_page_size_max,
            job_pool_authenticated_page_size_max=job_pool_authenticated_page_size_max,
            recommendation_default_page_size=recommendation_default_page_size,
            recommendation_page_size_max=recommendation_page_size_max,
            recommendation_run_default_page_size=recommendation_run_default_page_size,
            recommendation_run_page_size_max=recommendation_run_page_size_max,
            recommendation_result_default_page_size=recommendation_result_default_page_size,
            recommendation_result_page_size_max=recommendation_result_page_size_max,
            saved_jobs_default_page_size=saved_jobs_default_page_size,
            saved_jobs_page_size_max=saved_jobs_page_size_max,
            recommendation_candidate_limit=recommendation_candidate_limit,
            signup_bonus_credits=signup_bonus_credits,
            recommendation_cost=recommendation_cost,
            job_description_preview_length=job_description_preview_length,
            idempotency_key_max_length=idempotency_key_max_length,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_algorithm=jwt_algorithm,
            jwt_signing_key=jwt_signing_key,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_session_ttl_seconds=refresh_session_ttl_seconds,
            refresh_cookie_name=refresh_cookie_name,
            refresh_cookie_secure=refresh_cookie_secure,
            refresh_cookie_samesite=refresh_cookie_samesite,
            refresh_cookie_path=refresh_cookie_path,
            cors_allowed_origins=cors_allowed_origins,
            register_ip_limit_per_hour=register_ip_limit_per_hour,
            login_email_failure_limit=login_email_failure_limit,
            login_ip_attempt_limit=login_ip_attempt_limit,
            refresh_session_limit_per_minute=refresh_session_limit_per_minute,
            refresh_ip_limit_per_minute=refresh_ip_limit_per_minute,
        )


def _optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _read_origins(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def _read_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _read_positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive number")
    return parsed


def _read_positive_int(value: str, name: str) -> int:
    parsed = _read_non_negative_int(value, name)
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _read_non_negative_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return parsed


__all__ = ["Settings"]
