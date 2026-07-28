from __future__ import annotations

from pydantic import AwareDatetime, ConfigDict, Field

from .common import ContractModel, NonEmptyStr


class ProfileDraft(ContractModel):
    target_locations: list[NonEmptyStr]
    target_roles: list[NonEmptyStr]
    skills: list[NonEmptyStr]
    excluded_roles: list[NonEmptyStr]
    education: NonEmptyStr | None = None
    graduation_year: int | None = None
    expected_salary_min: int | None = Field(default=None, ge=0)
    experience_summary: NonEmptyStr | None = None
    extra_request: NonEmptyStr | None = None
    warnings: list[NonEmptyStr]


class ProfileSnapshot(ProfileDraft):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: NonEmptyStr
    user_id: NonEmptyStr
    version: int = Field(ge=1)
    created_at: AwareDatetime


def merge_extra_request(
    profile_extra_request: str | None,
    request_extra_request: str | None,
) -> str | None:
    """Keep profile guidance and one-off guidance in a deterministic order."""
    parts = [
        value.strip()
        for value in (profile_extra_request, request_extra_request)
        if value is not None and value.strip()
    ]
    return "\n\n".join(parts) or None
