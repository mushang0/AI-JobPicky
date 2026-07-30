from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}

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
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1
    evaluation_batch_size: int = 10
    model_config_version: str = "recommendation-v1"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if environ is None else environ
        defaults = cls()
        app_name = values.get("JOBPICKY_APP_NAME", defaults.app_name).strip()
        environment = values.get("JOBPICKY_ENVIRONMENT", defaults.environment).strip()
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
        )


def _optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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
