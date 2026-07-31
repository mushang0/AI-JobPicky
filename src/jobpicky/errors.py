from __future__ import annotations

from collections.abc import Mapping

from .contracts.common import ErrorCode, JsonObject


class ApplicationError(Exception):
    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        *,
        status_code: int = 400,
        details: JsonObject | None = None,
        run_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not 400 <= status_code <= 599:
            raise ValueError("application error status_code must be between 400 and 599")
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.run_id = run_id
        self.headers = dict(headers or {})


__all__ = ["ApplicationError"]
