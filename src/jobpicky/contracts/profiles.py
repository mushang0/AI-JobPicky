from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from .catalog import EducationLevel, RecruitmentType
from .common import ContractModel, NonEmptyStr

ProfileTag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ProfileDraft(ContractModel):
    """User-editable profile fields; server-owned warnings are not accepted."""

    target_locations: list[ProfileTag] = Field(default_factory=list, max_length=10)
    target_roles: list[ProfileTag] = Field(min_length=1, max_length=10)
    recruitment_types: list[RecruitmentType] = Field(default_factory=list, max_length=3)
    skills: list[ProfileTag] = Field(default_factory=list, max_length=50)
    excluded_roles: list[ProfileTag] = Field(default_factory=list, max_length=20)
    education: EducationLevel | None = None
    graduation_year: int | None = None
    expected_salary_min: int | None = Field(default=None, ge=0, le=1_000_000)
    experience_summary: str | None = Field(default=None, max_length=5000)
    extra_request: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> Any:
        return _normalize_profile_value(value)

    @model_validator(mode="after")
    def validate_content(self) -> ProfileDraft:
        if not self.skills and not (self.experience_summary and self.experience_summary.strip()):
            raise ValueError("skills or experience_summary must be provided")
        _validate_graduation_year(self.graduation_year)
        return self


class ProfileSaveRequest(ProfileDraft):
    base_version: int | None = Field(default=None, ge=1)


ProfileUpdateRequest = ProfileSaveRequest


class ProfileSnapshot(ContractModel):
    """Immutable stored snapshot; warnings and identity fields are server-owned."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: NonEmptyStr
    user_id: NonEmptyStr
    version: int = Field(ge=1)
    target_locations: list[ProfileTag] = Field(default_factory=list, max_length=10)
    target_roles: list[ProfileTag]
    recruitment_types: list[RecruitmentType] = Field(default_factory=list, max_length=3)
    skills: list[ProfileTag] = Field(default_factory=list, max_length=50)
    excluded_roles: list[ProfileTag] = Field(default_factory=list, max_length=20)
    education: EducationLevel | None = None
    graduation_year: int | None = None
    expected_salary_min: int | None = Field(default=None, ge=0, le=1_000_000)
    experience_summary: str | None = Field(default=None, max_length=5000)
    extra_request: str | None = Field(default=None, max_length=1000)
    warnings: list[NonEmptyStr] = Field(default_factory=list)
    created_at: AwareDatetime

    @model_validator(mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> Any:
        return _normalize_profile_value(value)

    @model_validator(mode="after")
    def validate_content(self) -> ProfileSnapshot:
        _validate_graduation_year(self.graduation_year)
        return self


class CurrentProfileView(ContractModel):
    """User-facing profile response; ownership fields stay in ProfileSnapshot."""

    id: NonEmptyStr
    version: int = Field(ge=1)
    target_locations: list[ProfileTag] = Field(default_factory=list, max_length=10)
    target_roles: list[ProfileTag]
    recruitment_types: list[RecruitmentType] = Field(default_factory=list, max_length=3)
    skills: list[ProfileTag] = Field(default_factory=list, max_length=50)
    education: EducationLevel | None = None
    graduation_year: int | None = None
    expected_salary_min: int | None = Field(default=None, ge=0, le=1_000_000)
    experience_summary: str | None = Field(default=None, max_length=5000)
    excluded_roles: list[ProfileTag] = Field(default_factory=list, max_length=20)
    extra_request: str | None = Field(default=None, max_length=1000)
    warnings: list[NonEmptyStr] = Field(default_factory=list)
    created_at: AwareDatetime


ProfileView = CurrentProfileView


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


def _normalize_profile_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    for field_name in (
        "target_locations",
        "target_roles",
        "recruitment_types",
        "skills",
        "excluded_roles",
    ):
        if field_name in normalized and isinstance(normalized[field_name], list):
            normalized[field_name] = _deduplicate(normalized[field_name])
    for field_name in ("experience_summary", "extra_request"):
        if isinstance(normalized.get(field_name), str):
            normalized[field_name] = normalized[field_name].strip() or None
    return normalized


def _deduplicate(values: list[object]) -> list[object]:
    seen: set[str] = set()
    result: list[object] = []
    for value in values:
        key = str(value).strip().casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _validate_graduation_year(value: int | None) -> None:
    current_year = datetime.now(UTC).year
    if value is not None and not current_year - 80 <= value <= current_year + 10:
        raise ValueError("graduation_year is outside the supported range")
