from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, Field, model_validator

from .common import (
    ContractModel,
    HttpUrlString,
    JobStatus,
    JsonObject,
    NonEmptyStr,
    NonNegativeInt,
    NormalizedScore,
)
from .normalization import (
    EDUCATION_VALUES,
    RECRUITMENT_TYPE_VALUES,
    normalize_city,
    normalize_company_nature,
    normalize_education,
    normalize_recruitment_type,
    normalize_search_text,
)


class FilterReasonCode(StrEnum):
    JOB_NOT_OPEN = "JOB_NOT_OPEN"
    LOCATION_MISMATCH = "LOCATION_MISMATCH"
    RECRUITMENT_TYPE_MISMATCH = "RECRUITMENT_TYPE_MISMATCH"
    EDUCATION_MISMATCH = "EDUCATION_MISMATCH"
    EXCLUDED_ROLE = "EXCLUDED_ROLE"
    GRADUATION_YEAR_MISMATCH = "GRADUATION_YEAR_MISMATCH"
    SALARY_MISMATCH = "SALARY_MISMATCH"


class RetrievalChannel(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class RecruitmentType(StrEnum):
    CAMPUS = RECRUITMENT_TYPE_VALUES[0]
    SOCIAL = RECRUITMENT_TYPE_VALUES[1]
    INTERNSHIP = RECRUITMENT_TYPE_VALUES[2]


class EducationLevel(StrEnum):
    HIGH_SCHOOL_OR_BELOW = EDUCATION_VALUES[0]
    COLLEGE = EDUCATION_VALUES[1]
    BACHELOR = EDUCATION_VALUES[2]
    MASTER = EDUCATION_VALUES[3]
    DOCTORATE = EDUCATION_VALUES[4]


class JobSourceView(ContractModel):
    id: NonEmptyStr
    name: NonEmptyStr


class JobFilterSource(ContractModel):
    platform: NonEmptyStr
    source_ids: list[NonEmptyStr] = Field(min_length=1)


class JobFact(ContractModel):
    id: NonEmptyStr
    source_id: NonEmptyStr
    company_name: NonEmptyStr
    company_nature: NonEmptyStr | None = None
    title: NonEmptyStr
    locations: list[NonEmptyStr]
    description: NonEmptyStr | None = None
    detail_url: HttpUrlString | None = None
    apply_url: HttpUrlString | None = None
    recruitment_type: NonEmptyStr | None = None
    education_requirement: NonEmptyStr | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_months: int | None = Field(default=None, ge=1)
    graduation_years: list[int] = Field(default_factory=list)
    status: JobStatus
    fact_version: NonEmptyStr
    published_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    first_seen_at: AwareDatetime
    last_confirmed_at: AwareDatetime
    updated_at: AwareDatetime
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def keep_salary_range_ordered(self) -> JobFact:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        return self


class JobQuery(ContractModel):
    status: JobStatus | None = None
    company_name: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
    keyword: NonEmptyStr | None = None


class JobListQuery(ContractModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1, le=100)
    q: str | None = Field(default=None, max_length=200)
    city: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    company_nature: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    source_id: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    batch: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    recruitment_type: list[RecruitmentType] = Field(default_factory=list, max_length=50)
    education: list[EducationLevel] = Field(default_factory=list, max_length=50)
    graduation_year: list[int] = Field(default_factory=list, max_length=50)
    salary_min: NonNegativeInt | None = None
    salary_max: NonNegativeInt | None = None
    published_within_days: int | None = Field(default=None, ge=1, le=3650)
    published_at_unknown: bool = False
    company_group_id: NonEmptyStr | None = Field(default=None, max_length=200)

    @model_validator(mode="before")
    @classmethod
    def normalize_filter_values(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        if isinstance(normalized.get("q"), str):
            normalized["q"] = normalize_search_text(normalized["q"])
        _normalize_list(normalized, "city", normalize_city)
        _normalize_list(normalized, "company_nature", normalize_company_nature)
        _normalize_list(normalized, "recruitment_type", normalize_recruitment_type)
        _normalize_list(normalized, "education", normalize_education)
        return normalized

    @model_validator(mode="after")
    def validate_salary_range(self) -> JobListQuery:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        if self.published_within_days is not None and self.published_at_unknown:
            raise ValueError("published date filters cannot be combined")
        self.q = self.q.strip() if self.q and self.q.strip() else None
        for field_name in (
            "city",
            "company_nature",
            "source_id",
            "batch",
            "recruitment_type",
            "education",
            "graduation_year",
        ):
            values = getattr(self, field_name)
            setattr(self, field_name, _deduplicate(values))
        return self


JobPoolQuery = JobListQuery


class HardFilterSpec(ContractModel):
    target_locations: list[NonEmptyStr] = Field(default_factory=list)
    excluded_roles: list[NonEmptyStr] = Field(default_factory=list)
    education: NonEmptyStr | None = None
    recruitment_types: list[NonEmptyStr] = Field(default_factory=list)
    graduation_year: int | None = None
    min_salary: int | None = Field(default=None, ge=0)
    only_open: bool = True


class FilterExclusion(ContractModel):
    job_id: NonEmptyStr
    reason_code: NonEmptyStr
    reason: NonEmptyStr


class FilterResult(ContractModel):
    eligible_job_ids: list[NonEmptyStr]
    excluded: list[FilterExclusion]

    @model_validator(mode="after")
    def keep_eligible_and_excluded_disjoint(self) -> FilterResult:
        eligible = set(self.eligible_job_ids)
        if len(eligible) != len(self.eligible_job_ids):
            raise ValueError("eligible_job_ids must not contain duplicates")
        excluded = {item.job_id for item in self.excluded}
        if eligible & excluded:
            raise ValueError("a job cannot be both eligible and excluded")
        return self


class SearchHit(ContractModel):
    job_id: NonEmptyStr
    score: NormalizedScore
    channel: RetrievalChannel


class JobListItem(ContractModel):
    """Public job-pool card; it intentionally is not a JobFact."""

    id: NonEmptyStr
    title: NonEmptyStr
    company_name: NonEmptyStr
    company_nature: NonEmptyStr | None = None
    locations: list[NonEmptyStr] = Field(default_factory=list)
    source: JobSourceView
    batch: NonEmptyStr | None = None
    recruitment_type: RecruitmentType | None = None
    education_requirement: NonEmptyStr | None = None
    graduation_years: list[int] = Field(default_factory=list)
    salary_min: NonNegativeInt | None = None
    salary_max: NonNegativeInt | None = None
    salary_months: int | None = Field(default=None, ge=1)
    description_preview: str | None = Field(default=None, max_length=240)
    published_at: AwareDatetime | None = None
    last_confirmed_at: AwareDatetime
    is_saved: bool | None = None

    @model_validator(mode="after")
    def keep_salary_range_ordered(self) -> JobListItem:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        return self


class JobDetailView(ContractModel):
    """Public job detail; internal fact version and source secrets stay hidden."""

    id: NonEmptyStr
    title: NonEmptyStr
    company_name: NonEmptyStr
    company_nature: NonEmptyStr | None = None
    locations: list[NonEmptyStr] = Field(default_factory=list)
    source: JobSourceView
    batch: NonEmptyStr | None = None
    recruitment_type: RecruitmentType | None = None
    education_requirement: NonEmptyStr | None = None
    graduation_years: list[int] = Field(default_factory=list)
    salary_min: NonNegativeInt | None = None
    salary_max: NonNegativeInt | None = None
    salary_months: int | None = Field(default=None, ge=1)
    description: str | None = None
    detail_url: HttpUrlString | None = None
    apply_url: HttpUrlString | None = None
    status: JobStatus
    published_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    first_seen_at: AwareDatetime
    last_confirmed_at: AwareDatetime
    updated_at: AwareDatetime
    is_saved: bool | None = None

    @model_validator(mode="after")
    def keep_salary_range_ordered(self) -> JobDetailView:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        return self


class SavedJobItem(JobListItem):
    status: JobStatus
    is_saved: bool = True


class SavedJobView(ContractModel):
    saved_at: AwareDatetime
    job: SavedJobItem


class CompanyListItem(ContractModel):
    group_id: NonEmptyStr
    company_name: NonEmptyStr
    company_nature: NonEmptyStr | None = None
    job_titles: list[NonEmptyStr] = Field(default_factory=list, max_length=3)
    job_count: NonNegativeInt
    latest_published_at: AwareDatetime | None = None


class CompanyPoolPage(ContractModel):
    items: list[CompanyListItem]
    total: NonNegativeInt
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    pool_total: NonNegativeInt


class JobPoolPage(ContractModel):
    items: list[JobListItem]
    total: NonNegativeInt
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    pool_total: NonNegativeInt


class FilterOptionsLimits(ContractModel):
    default_page_size: int = Field(ge=1, le=100)
    public_page_size_max: int = Field(ge=1, le=100)
    authenticated_page_size_max: int = Field(ge=1, le=100)


class JobFilterOptions(ContractModel):
    cities: list[NonEmptyStr] = Field(default_factory=list)
    company_natures: list[NonEmptyStr] = Field(default_factory=list)
    sources: list[JobFilterSource] = Field(default_factory=list)
    batches: list[NonEmptyStr] = Field(default_factory=list)
    recruitment_types: list[RecruitmentType] = Field(default_factory=list)
    educations: list[EducationLevel] = Field(default_factory=list)
    graduation_years: list[int] = Field(default_factory=list)
    limits: FilterOptionsLimits


FilterOptionsView = JobFilterOptions
JobListResponse = JobPoolPage


def _deduplicate(values: list[object]) -> list[object]:
    seen: set[str] = set()
    result: list[object] = []
    for value in values:
        key = str(value).strip().casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _normalize_list(
    values: dict[str, object],
    field_name: str,
    normalize: Callable[[str | None], str | None],
) -> None:
    items = values.get(field_name)
    if not isinstance(items, list):
        return
    values[field_name] = [
        normalize(item) or item if isinstance(item, str) else item for item in items
    ]
