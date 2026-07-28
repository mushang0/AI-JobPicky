from __future__ import annotations

from pydantic import AwareDatetime, Field, model_validator

from .common import (
    ContractModel,
    HttpUrlString,
    JsonObject,
    NonEmptyStr,
    NonNegativeInt,
)


class SourceInput(ContractModel):
    company_name: NonEmptyStr
    source_url: HttpUrlString
    enabled: bool = True
    platform_hint: NonEmptyStr | None = None
    metadata: JsonObject = Field(default_factory=dict)


class SourcePatch(ContractModel):
    company_name: NonEmptyStr | None = None
    source_url: HttpUrlString | None = None
    enabled: bool | None = None
    platform_hint: NonEmptyStr | None = None
    metadata: JsonObject | None = None


class SourceView(SourceInput):
    id: NonEmptyStr
    platform: NonEmptyStr | None = None
    resolved_url: HttpUrlString | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CollectedJob(ContractModel):
    source_id: NonEmptyStr
    source_job_id: NonEmptyStr | None = None
    company_name: NonEmptyStr
    title: NonEmptyStr
    locations: list[NonEmptyStr]
    description: NonEmptyStr | None = None
    detail_url: HttpUrlString | None = None
    apply_url: HttpUrlString | None = None
    recruitment_type: NonEmptyStr | None = None
    education_requirement: NonEmptyStr | None = None
    published_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    source_ref: NonEmptyStr | None = None
    metadata: JsonObject = Field(default_factory=dict)


class CollectionBatch(ContractModel):
    source_id: NonEmptyStr
    items: list[CollectedJob]
    complete: bool
    method: NonEmptyStr
    warnings: list[NonEmptyStr]
    metrics: JsonObject = Field(default_factory=dict)
    config_candidate: JsonObject | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> CollectionBatch:
        if any(item.source_id != self.source_id for item in self.items):
            raise ValueError("every collected job must belong to the batch source")
        return self


class IngestionResult(ContractModel):
    job_ids: list[NonEmptyStr]
    created_count: NonNegativeInt
    updated_count: NonNegativeInt
    unchanged_count: NonNegativeInt
    closed_count: NonNegativeInt
    close_skipped: bool
    complete_accepted: bool
    warnings: list[NonEmptyStr]

    @model_validator(mode="after")
    def protect_incomplete_collection(self) -> IngestionResult:
        if not self.complete_accepted and self.closed_count:
            raise ValueError("closed_count must be zero when completeness is not accepted")
        return self
