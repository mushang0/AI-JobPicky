from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky"


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "JobPicky"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = _DEFAULT_DATABASE_URL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if environ is None else environ
        defaults = cls()
        app_name = values.get("JOBPICKY_APP_NAME", defaults.app_name).strip()
        environment = values.get("JOBPICKY_ENVIRONMENT", defaults.environment).strip()
        log_level = values.get("JOBPICKY_LOG_LEVEL", defaults.log_level).strip().upper()
        database_url = values.get("JOBPICKY_DATABASE_URL", defaults.database_url).strip()

        if not app_name:
            raise ValueError("JOBPICKY_APP_NAME must not be empty")
        if not environment:
            raise ValueError("JOBPICKY_ENVIRONMENT must not be empty")
        if log_level not in _LOG_LEVELS:
            raise ValueError(f"JOBPICKY_LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        if not database_url:
            raise ValueError("JOBPICKY_DATABASE_URL must not be empty")

        return cls(
            app_name=app_name,
            environment=environment,
            log_level=log_level,
            database_url=database_url,
        )


__all__ = ["Settings"]
