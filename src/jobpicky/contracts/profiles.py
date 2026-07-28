from __future__ import annotations

from pydantic import AwareDatetime, ConfigDict, Field

from .common import ContractModel, NonEmptyStr


class ProfileDraft(ContractModel):
    target_locations: list[NonEmptyStr]
    target_roles: list[NonEmptyStr]
    skills: list[NonEmptyStr]
    excluded_roles: list[NonEmptyStr]
    education: NonEmptyStr | None = None
    experience_summary: NonEmptyStr | None = None
    extra_request: NonEmptyStr | None = None
    warnings: list[NonEmptyStr]


class ProfileSnapshot(ProfileDraft):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: NonEmptyStr
    user_id: NonEmptyStr
    version: int = Field(ge=1)
    created_at: AwareDatetime
