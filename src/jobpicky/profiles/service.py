from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from ..contracts import ErrorCode, ProfileImportView, ProfileSaveRequest, ProfileSnapshot
from ..errors import ApplicationError
from ..ports import ProfileParserPort
from .resume_files import (
    PROFILE_IMPORT_MAX_BYTES,
    PROFILE_IMPORT_MAX_PDF_PAGES,
    PROFILE_IMPORT_MAX_TEXT_CHARS,
    extract_resume_text,
)

_PROFILE_CONTENT_FIELDS = frozenset(
    {
        "target_locations",
        "target_roles",
        "recruitment_types",
        "skills",
        "excluded_roles",
        "education",
        "graduation_year",
        "expected_salary_min",
        "experience_summary",
        "extra_request",
    }
)


class ProfileVersionConflictError(Exception):
    """The submitted base version is not the user's current version."""


class ProfileIdempotencyConflictError(Exception):
    """An idempotency key was reused with a different normalized request."""


@dataclass(frozen=True, slots=True)
class ProfileSaveCommand:
    user_id: str
    request: ProfileSaveRequest
    idempotency_key: str
    request_hash: str
    proposed_profile_id: str
    created_at: datetime


class ProfileStore(Protocol):
    async def find_current(self, user_id: str) -> ProfileSnapshot | None: ...

    async def save_current(self, command: ProfileSaveCommand) -> ProfileSnapshot: ...


class ProfileService:
    """Application service for the single logical, versioned user profile."""

    def __init__(
        self,
        store: ProfileStore,
        *,
        idempotency_key_max_length: int = 128,
        parser: ProfileParserPort | None = None,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if idempotency_key_max_length < 1:
            raise ValueError("idempotency_key_max_length must be positive")
        self._store = store
        self._idempotency_key_max_length = idempotency_key_max_length
        self._parser = parser
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid4()))

    @property
    def import_max_bytes(self) -> int:
        return PROFILE_IMPORT_MAX_BYTES

    async def get_current(self, user_id: str) -> ProfileSnapshot:
        snapshot = await self._store.find_current(user_id)
        if snapshot is None:
            raise ApplicationError(
                ErrorCode.PROFILE_NOT_FOUND,
                "profile not found",
                status_code=404,
            )
        return snapshot

    async def save_current(
        self,
        user_id: str,
        draft: ProfileSaveRequest,
        idempotency_key: str,
    ) -> ProfileSnapshot:
        self._validate_idempotency_key(idempotency_key)
        command = ProfileSaveCommand(
            user_id=user_id,
            request=draft,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(draft),
            proposed_profile_id=self._id_factory(),
            created_at=self._now(),
        )
        try:
            return await self._store.save_current(command)
        except ProfileVersionConflictError as exc:
            raise ApplicationError(
                ErrorCode.PROFILE_VERSION_CONFLICT,
                "profile version conflict",
                status_code=409,
            ) from exc
        except ProfileIdempotencyConflictError as exc:
            raise ApplicationError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "idempotency key conflict",
                status_code=409,
            ) from exc

    async def import_resume(
        self,
        user_id: str,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> ProfileImportView:
        del user_id, content_type
        extracted = await asyncio.to_thread(
            extract_resume_text,
            filename,
            content,
            max_bytes=PROFILE_IMPORT_MAX_BYTES,
            max_pdf_pages=PROFILE_IMPORT_MAX_PDF_PAGES,
            max_text_chars=PROFILE_IMPORT_MAX_TEXT_CHARS,
        )
        if self._parser is None:
            raise ApplicationError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "profile parser is not configured",
                status_code=503,
                details={"dependency": "llm", "stage": "PARSE"},
            )
        result = await self._parser.parse(extracted.text, None)
        warnings = list(dict.fromkeys([*extracted.warnings, *result.warnings]))[:20]
        return result.model_copy(update={"warnings": warnings})

    def _validate_idempotency_key(self, key: str) -> None:
        if not 1 <= len(key) <= self._idempotency_key_max_length or any(
            ord(character) < 0x20 or ord(character) > 0x7E for character in key
        ):
            raise ApplicationError(
                ErrorCode.VALIDATION_ERROR,
                "invalid idempotency key",
                status_code=422,
            )


def plan_profile_save(
    current: ProfileSnapshot | None,
    command: ProfileSaveCommand,
) -> ProfileSnapshot:
    """Apply optimistic version rules after idempotency replay has been checked."""
    base_version = command.request.base_version
    if current is None:
        if base_version is not None:
            raise ProfileVersionConflictError
        profile_id = command.proposed_profile_id
        version = 1
    else:
        if base_version != current.version:
            raise ProfileVersionConflictError
        if _profile_content(current) == _profile_content(command.request):
            return current
        profile_id = current.id
        version = current.version + 1

    return ProfileSnapshot.model_validate(
        {
            "id": profile_id,
            "user_id": command.user_id,
            "version": version,
            **_profile_content(command.request),
            "warnings": [],
            "created_at": command.created_at,
        }
    )


def _profile_content(value: ProfileSaveRequest | ProfileSnapshot) -> dict[str, object]:
    return value.model_dump(include=set(_PROFILE_CONTENT_FIELDS), mode="json")


def _request_hash(request: ProfileSaveRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "ProfileIdempotencyConflictError",
    "ProfileSaveCommand",
    "ProfileService",
    "ProfileStore",
    "ProfileVersionConflictError",
    "plan_profile_save",
]
