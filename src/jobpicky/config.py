from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "JobPicky"
    environment: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if environ is None else environ
        defaults = cls()
        app_name = values.get("JOBPICKY_APP_NAME", defaults.app_name).strip()
        environment = values.get("JOBPICKY_ENVIRONMENT", defaults.environment).strip()
        log_level = values.get("JOBPICKY_LOG_LEVEL", defaults.log_level).strip().upper()

        if not app_name:
            raise ValueError("JOBPICKY_APP_NAME must not be empty")
        if not environment:
            raise ValueError("JOBPICKY_ENVIRONMENT must not be empty")
        if log_level not in _LOG_LEVELS:
            raise ValueError(f"JOBPICKY_LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")

        return cls(app_name=app_name, environment=environment, log_level=log_level)


__all__ = ["Settings"]
