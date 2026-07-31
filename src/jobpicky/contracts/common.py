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
    model_validator,
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


def _validate_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    if (
        value.count("@") != 1
        or not separator
        or not local
        or not domain
        or "." not in domain
        or any(character.isspace() for character in value)
    ):
        raise ValueError("must be a valid email address")
    return value.casefold()


EmailAddress = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=254),
    AfterValidator(_validate_email),
]
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


class RecommendationTaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RunKind(StrEnum):
    CRAWL = "CRAWL"
    RECOMMENDATION = "RECOMMENDATION"


class UserRole(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class Feedback(StrEnum):
    LIKE = "LIKE"
    DISLIKE = "DISLIKE"


class RecommendationSort(StrEnum):
    RECOMMENDED_AT_DESC = "recommended_at_desc"
    MATCH_SCORE_DESC = "match_score_desc"


class ErrorCode(StrEnum):
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_VERSION_CONFLICT = "PROFILE_VERSION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
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


DEFAULT_ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.AUTHENTICATION_REQUIRED: "登录状态已失效，请重新登录。",
    ErrorCode.SESSION_EXPIRED: "登录会话已过期，请重新登录。",
    ErrorCode.ACCOUNT_DISABLED: "当前账号不可用，请联系管理员。",
    ErrorCode.INVALID_CREDENTIALS: "邮箱或密码错误。",
    ErrorCode.EMAIL_ALREADY_REGISTERED: "该邮箱已经注册。",
    ErrorCode.TOO_MANY_ATTEMPTS: "操作过于频繁，请稍后重试。",
    ErrorCode.INSUFFICIENT_CREDITS: "积分余额不足，请先补充积分。",
    ErrorCode.PROFILE_NOT_FOUND: "还没有保存求职画像，请先完成画像。",
    ErrorCode.PROFILE_VERSION_CONFLICT: "画像已在其他页面更新，请刷新后重试。",
    ErrorCode.IDEMPOTENCY_CONFLICT: "请求标识已用于其他操作，请重新提交。",
    ErrorCode.VALIDATION_ERROR: "请求内容不符合要求。",
    ErrorCode.NOT_FOUND: "请求的资源不存在。",
    ErrorCode.FORBIDDEN: "你没有权限执行此操作。",
    ErrorCode.CONFLICT: "当前操作与已有状态冲突。",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "依赖服务暂时不可用，请稍后重试。",
    ErrorCode.CRAWL_UNSUPPORTED: "该招聘来源暂不支持自动采集。",
    ErrorCode.CRAWL_INCOMPLETE: "招聘来源采集未完整完成，请稍后查看运行详情。",
    ErrorCode.PROFILE_PARSE_FAILED: "求职画像处理失败，请检查输入后重试。",
    ErrorCode.RECOMMENDATION_FAILED: "推荐任务处理失败，已退回本次消耗的积分。",
    ErrorCode.INTERNAL_ERROR: "系统暂时无法处理请求，请稍后重试。",
}


def error_message(code: ErrorCode | str) -> str:
    """Return the stable Chinese message for a user-visible error code."""
    try:
        return DEFAULT_ERROR_MESSAGES[ErrorCode(str(code))]
    except (KeyError, ValueError):
        return DEFAULT_ERROR_MESSAGES[ErrorCode.INTERNAL_ERROR]


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


class AuthUserView(ContractModel):
    id: NonEmptyStr
    email: EmailAddress
    role: UserRole
    created_at: AwareDatetime


UserView = AuthUserView


class LoginRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    email: EmailAddress
    password: str = Field(min_length=15, max_length=128)


class RegisterRequest(LoginRequest):
    pass


class AccessTokenResponse(ContractModel):
    access_token: NonEmptyStr
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: PositiveInt


class LoginResponse(AccessTokenResponse):
    user: AuthUserView


class CreditSummary(ContractModel):
    balance: NonNegativeInt
    recommendation_cost: NonNegativeInt


CreditsView = CreditSummary


class CreditUsage(ContractModel):
    cost: NonNegativeInt
    refunded: bool
    net_spent: NonNegativeInt

    @model_validator(mode="after")
    def keep_net_spent_consistent(self) -> CreditUsage:
        expected = 0 if self.refunded else self.cost
        if self.net_spent != expected:
            raise ValueError("net_spent must equal cost unless the charge was refunded")
        return self


class SavedJobState(ContractModel):
    job_id: NonEmptyStr
    is_saved: bool


class RecommendationRunAccepted(ContractModel):
    run_id: NonEmptyStr
    status: RecommendationTaskStatus
    credits_charged: NonNegativeInt
    balance_after: NonNegativeInt


class RecommendationTaskView(ContractModel):
    run_id: NonEmptyStr
    status: RecommendationTaskStatus
    current_step: RecommendationStep
    progress_percent: int = Field(ge=0, le=100)
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    counts: dict[str, NonNegativeInt] = Field(default_factory=dict)
    credits: CreditUsage
    error: RunError | None = None


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
