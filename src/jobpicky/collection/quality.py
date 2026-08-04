from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from jobpicky.contracts import CollectedJob
from jobpicky.contracts.common import JsonObject

from .link_classification import COMPANY_WEBSITE, WECHAT
from .spreadsheet import SpreadsheetRow

CollectionDecision = Literal["ACCEPT_PARSED", "FALLBACK_TO_TABLE", "SKIP_STALE"]

_GENERIC_TITLE_RE = re.compile(
    r"职位详情|招聘公告|招募公告|招聘官网|中文官网|报名平台|二维码|招聘网|活动邀请|^careers?\s+at\b",
    re.IGNORECASE,
)
_GENERIC_TITLES = {"职位", "职位详情", "招聘", "招聘岗位", "岗位详情", "校招岗位"}


@dataclass(frozen=True)
class CollectionQualityPolicy:
    """Small, conservative policy for deciding whether parsed facts are usable."""

    table_fallback_link_types: frozenset[str] = frozenset({WECHAT, COMPANY_WEBSITE})
    published_stale_days_by_type: Mapping[str, int] = field(
        default_factory=lambda: {"实习": 180, "校招": 365, "社招": 365}
    )

    def stale_days_for(self, recruitment_type: str | None) -> int:
        days = self.published_stale_days_by_type.get(recruitment_type or "", 365)
        if days < 1:
            raise ValueError("published stale days must be positive")
        return days


@dataclass(frozen=True)
class QualityDecision:
    decision: CollectionDecision
    reason_codes: tuple[str, ...] = ()


def _aware(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(UTC)


def _is_stale_deadline(row: SpreadsheetRow, now: datetime) -> bool:
    deadline = _aware(row.deadline_at)
    return deadline is not None and deadline < now


def preflight_quality(
    link_type: str,
    row: SpreadsheetRow,
    policy: CollectionQualityPolicy,
    *,
    now: datetime | None = None,
) -> QualityDecision | None:
    current = _aware(now) or datetime.now(UTC)
    if _is_stale_deadline(row, current):
        return QualityDecision("SKIP_STALE", ("STALE_DEADLINE",))
    if link_type in policy.table_fallback_link_types:
        return QualityDecision("FALLBACK_TO_TABLE", ("PARSER_POLICY_TABLE_FALLBACK",))
    return None


def _title_is_generic(title: object, company_name: str | None) -> bool:
    if not isinstance(title, str):
        return True
    normalized = re.sub(r"\s+", "", title).strip()
    if not normalized:
        return True
    if normalized in _GENERIC_TITLES or _GENERIC_TITLE_RE.search(normalized):
        return True
    return bool(company_name and normalized.casefold() == company_name.replace(" ", "").casefold())


def _published_jobs_are_stale(
    row: SpreadsheetRow,
    parsed_jobs: Sequence[Mapping[str, object]],
    policy: CollectionQualityPolicy,
    now: datetime,
) -> bool:
    if not parsed_jobs or _is_stale_deadline(row, now):
        return False
    published = [_aware(job.get("published_at")) for job in parsed_jobs]
    if any(value is None for value in published):
        return False
    threshold = now - timedelta(days=policy.stale_days_for(row.recruitment_type))
    return all(value < threshold for value in published if value is not None)


def assess_parsed_jobs(
    link_type: str,
    row: SpreadsheetRow,
    parsed_jobs: Sequence[Mapping[str, object]],
    policy: CollectionQualityPolicy,
    *,
    now: datetime | None = None,
) -> QualityDecision:
    current = _aware(now) or datetime.now(UTC)
    if not parsed_jobs:
        return QualityDecision("FALLBACK_TO_TABLE", ("PARSER_EMPTY",))

    reasons: list[str] = []
    for job in parsed_jobs:
        metadata = job.get("metadata")
        if isinstance(metadata, Mapping):
            if metadata.get("needs_review") is True:
                reasons.append("PARSER_NEEDS_REVIEW")
            if metadata.get("content_shape") == "multi_job_candidate":
                reasons.append("MULTI_JOB_ANNOUNCEMENT")
            record_kind = metadata.get("record_kind")
            if isinstance(record_kind, str) and record_kind.endswith("_announcement"):
                reasons.append("ANNOUNCEMENT_NOT_JOB")
        if _title_is_generic(job.get("title"), row.company_name):
            reasons.append("GENERIC_OR_MISSING_TITLE")
        parsed_type = job.get("recruitment_type")
        if (
            row.recruitment_type
            and isinstance(parsed_type, str)
            and parsed_type != row.recruitment_type
        ):
            reasons.append("RECRUITMENT_TYPE_CONFLICT")

    if _published_jobs_are_stale(row, parsed_jobs, policy, current):
        return QualityDecision("SKIP_STALE", ("STALE_PUBLISHED_AT",))
    if any(reason != "RECRUITMENT_TYPE_CONFLICT" for reason in reasons):
        unique_reasons = tuple(dict.fromkeys(reasons))
        return QualityDecision("FALLBACK_TO_TABLE", unique_reasons)
    return QualityDecision("ACCEPT_PARSED", tuple(dict.fromkeys(reasons)))


def build_table_fallback(
    source_id: str,
    row: SpreadsheetRow,
    source_url: str,
    link_type: str,
    *,
    reason_codes: Sequence[str],
) -> CollectedJob:
    if not row.company_name:
        raise ValueError("spreadsheet row has no company name")
    title = row.job_directions or row.company_name
    http_url = source_url if source_url.startswith(("http://", "https://")) else None
    metadata: JsonObject = {
        "collection_mode": "TABLE_FALLBACK",
        "quality_reasons": list(dict.fromkeys(reason_codes)),
        "fallback_link_type": link_type,
        "fallback_source_url": source_url,
        "table_row_number": row.row_number,
    }
    return CollectedJob(
        source_id=source_id,
        company_name=row.company_name,
        company_nature=row.company_nature,
        title=title,
        locations=row.locations,
        description=row.job_directions,
        detail_url=http_url,
        apply_url=http_url,
        recruitment_type=row.recruitment_type,
        education_requirement=row.education_requirement,
        graduation_years=row.graduation_years,
        deadline_at=row.deadline_at,
        source_ref=(
            f"feishu-record:{row.source_record_id}"
            if row.source_record_id
            else f"table-row:{row.row_number}"
        ),
        metadata=metadata,
    )


__all__ = [
    "CollectionDecision",
    "CollectionQualityPolicy",
    "QualityDecision",
    "assess_parsed_jobs",
    "build_table_fallback",
    "preflight_quality",
]
