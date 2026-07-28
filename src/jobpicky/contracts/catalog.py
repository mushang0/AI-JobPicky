from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, Field, model_validator

from .common import (
    ContractModel,
    HttpUrlString,
    JobStatus,
    NonEmptyStr,
    NormalizedScore,
)


class FilterReasonCode(StrEnum):
    JOB_NOT_OPEN = "JOB_NOT_OPEN"
    LOCATION_MISMATCH = "LOCATION_MISMATCH"
    RECRUITMENT_TYPE_MISMATCH = "RECRUITMENT_TYPE_MISMATCH"
    EDUCATION_MISMATCH = "EDUCATION_MISMATCH"
    EXCLUDED_ROLE = "EXCLUDED_ROLE"


class RetrievalChannel(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class JobFact(ContractModel):
    id: NonEmptyStr
    source_id: NonEmptyStr
    company_name: NonEmptyStr
    title: NonEmptyStr
    locations: list[NonEmptyStr]
    description: NonEmptyStr | None = None
    detail_url: HttpUrlString | None = None
    apply_url: HttpUrlString | None = None
    recruitment_type: NonEmptyStr | None = None
    education_requirement: NonEmptyStr | None = None
    status: JobStatus
    fact_version: NonEmptyStr
    published_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    first_seen_at: AwareDatetime
    last_confirmed_at: AwareDatetime
    updated_at: AwareDatetime


class JobQuery(ContractModel):
    status: JobStatus | None = None
    company_name: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
    keyword: NonEmptyStr | None = None


class HardFilterSpec(ContractModel):
    target_locations: list[NonEmptyStr] = Field(default_factory=list)
    excluded_roles: list[NonEmptyStr] = Field(default_factory=list)
    education: NonEmptyStr | None = None
    recruitment_types: list[NonEmptyStr] = Field(default_factory=list)
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
