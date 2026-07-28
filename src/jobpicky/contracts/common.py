from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PositiveInt,
    StringConstraints,
)


def _validate_http_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("must be an absolute HTTP(S) URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in value)
    ):
        raise ValueError("must be an absolute HTTP(S) URL")
    return value


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
HttpUrlString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(_validate_http_url),
]
NonNegativeInt = Annotated[int, Field(ge=0)]
NormalizedScore = Annotated[float, Field(ge=0.0, le=1.0)]
MatchScore = Annotated[int, Field(ge=0, le=100)]
JsonObject = dict[str, JsonValue]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JobStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RecommendationStep(StrEnum):
    PENDING = "PENDING"
    PROFILE = "PROFILE"
    FILTER = "FILTER"
    RETRIEVE = "RETRIEVE"
    EVALUATE = "EVALUATE"
    SAVE = "SAVE"
    COMPLETE = "COMPLETE"


class RunKind(StrEnum):
    CRAWL = "CRAWL"
    RECOMMENDATION = "RECOMMENDATION"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    CRAWL_UNSUPPORTED = "CRAWL_UNSUPPORTED"
    CRAWL_INCOMPLETE = "CRAWL_INCOMPLETE"
    PROFILE_PARSE_FAILED = "PROFILE_PARSE_FAILED"
    RECOMMENDATION_FAILED = "RECOMMENDATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RunError(ContractModel):
    """Sanitized error persisted with a background business run."""

    code: NonEmptyStr
    message: NonEmptyStr
    details: JsonObject = Field(default_factory=dict)


class ErrorBody(ContractModel):
    code: NonEmptyStr
    message: NonEmptyStr
    details: JsonObject = Field(default_factory=dict)
    request_id: NonEmptyStr
    run_id: NonEmptyStr | None = None


class RecommendationRunInput(ContractModel):
    profile_id: NonEmptyStr
    profile_version: PositiveInt
    effective_extra_request: NonEmptyStr | None = None


class RunAccepted(ContractModel):
    run_id: NonEmptyStr
    status: RunStatus


class RunView(ContractModel):
    run_id: NonEmptyStr
    kind: RunKind
    status: RunStatus
    created_at: AwareDatetime
    current_step: NonEmptyStr | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    counts: dict[str, NonNegativeInt] = Field(default_factory=dict)
    warnings: list[NonEmptyStr]
    recommendation_input: RecommendationRunInput | None = None
    model_config_version: NonEmptyStr | None = None
    error: RunError | None = None


PageItem = TypeVar("PageItem")


class Page(ContractModel, Generic[PageItem]):
    items: list[PageItem]
    total: NonNegativeInt
    page: PositiveInt
    page_size: PositiveInt


class HealthView(ContractModel):
    status: Literal["UP", "DEGRADED"]
    service: NonEmptyStr
    version: NonEmptyStr
    dependencies: dict[str, str] = Field(default_factory=dict)
