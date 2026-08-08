from __future__ import annotations

import hashlib
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
_JOB_TITLE_SEPARATOR_CHARS = frozenset(";；、，,|\n")
_JOB_TITLE_OPENERS = {"(": ")", "（": "）", "[": "]", "［": "］", "【": "】", "《": "》"}
_ROLE_TITLE_END_RE = re.compile(
    r"(工程师|经理|专员|助理|分析师|研究员|设计师|开发|算法|测试|运维|运营|销售|采购|财务|人事|行政|产品|质量|工艺|生产|项目|商务|管培生|实习生|技术员|技师|架构师|顾问|主管|总监|教师|医生|护士|会计|法务|审计|翻译|编辑|策划|后端|前端|研发|制造|设备|安全|管理|推广|营销|业务|金融|技术|方向|应用|系统|支持|服务|工程|传感器|芯片|电机|结构|物流|仓储|岗位|岗位类|类|岗|师|员|生)$"
)
_SIMPLE_ROLE_TITLES = frozenset(
    {
        "AI",
        "IT",
        "HR",
        "后端",
        "前端",
        "产品",
        "运营",
        "财务",
        "法务",
        "采购",
        "销售",
        "质量",
        "研发",
        "测试",
        "算法",
        "硬件",
        "软件",
        "市场",
        "人力",
        "行政",
        "项目",
        "商务",
        "安全",
        "设计",
        "开发",
        "实习",
        "传感器",
        "芯片",
        "电机",
        "结构",
        "物流",
        "仓储",
    }
)
_SHORT_TABLE_TITLE_RE = re.compile(r"[\w\u3400-\u9fff&+/#./-]+")
_WHITESPACE_ROLE_END_RE = re.compile(
    r"(工程师|经理|专员|助理|分析师|研究员|设计师|开发|算法|测试|运维|运营|销售|采购|财务|人事|行政|产品|质量|工艺|生产|项目|商务|管培生|实习生|技术员|技师|架构师|顾问|主管|总监|教师|医生|护士|会计|法务|审计|翻译|编辑|策划|研发|制造|设备|安全|推广|营销|业务|金融|类|岗|师|员|生)$"
)
_TITLE_QUALIFIER_RE = re.compile(r"\s+(?:intern|internship|实习)$", re.IGNORECASE)
_TABLE_PROSE_RE = re.compile(
    r"岗位名称|招聘岗位信息|任职要求|公告正文|详见|点击链接|请点击|负责|工作内容|报名截止"
)
_LATIN_TITLE_RE = re.compile(r"[A-Za-z]")
_CJK_TITLE_RE = re.compile(r"[\u3400-\u9fff]")
_MAX_TABLE_TITLE_CHARS = 80


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


def _split_top_level(text: str, *, whitespace: bool = False) -> list[str]:
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    for index, char in enumerate(text):
        if char in _JOB_TITLE_OPENERS:
            stack.append(_JOB_TITLE_OPENERS[char])
            continue
        if stack and char == stack[-1]:
            stack.pop()
            continue
        if stack:
            continue
        if char in _JOB_TITLE_SEPARATOR_CHARS or (whitespace and char.isspace()):
            value = text[start:index].strip()
            if value:
                parts.append(value)
            start = index + 1
    value = text[start:].strip()
    if value:
        parts.append(value)
    return parts


def _looks_like_job_title_fragment(title: str, *, allow_short_category: bool = False) -> bool:
    without_parenthetical = _title_without_parenthetical(title)
    without_qualifier = _TITLE_QUALIFIER_RE.sub("", without_parenthetical).strip()
    if _TABLE_PROSE_RE.search(without_qualifier):
        return False
    if without_qualifier in _SIMPLE_ROLE_TITLES or _ROLE_TITLE_END_RE.search(without_qualifier):
        return True
    return (
        allow_short_category
        and len(without_qualifier) <= 32
        and bool(_SHORT_TABLE_TITLE_RE.fullmatch(without_qualifier))
    )


def _title_without_parenthetical(title: str) -> str:
    return re.sub(r"[（(][^（）()]*[）)]$", "", title).strip()


def _strip_leading_job_label(text: str) -> str:
    stack: list[str] = []
    for index, char in enumerate(text):
        if char in _JOB_TITLE_OPENERS:
            stack.append(_JOB_TITLE_OPENERS[char])
            continue
        if stack and char == stack[-1]:
            stack.pop()
            continue
        if not stack and char in ":：":
            suffix = text[index + 1 :].strip()
            if suffix and not _TABLE_PROSE_RE.search(suffix):
                return suffix
    return text


def _split_whitespace_job_titles(text: str) -> list[str]:
    words = _split_top_level(text, whitespace=True)
    if len(words) <= 1:
        return words

    groups: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        current.append(word)
        if _WHITESPACE_ROLE_END_RE.search(_title_without_parenthetical(word)):
            if index + 1 < len(words) and words[index + 1].casefold() in {
                "intern",
                "internship",
                "实习",
            }:
                current.append(words[index + 1])
                index += 1
                groups.append(" ".join(current))
                current = []
            elif index + 1 < len(words) and _looks_like_job_title_fragment(words[index + 1]):
                groups.append(" ".join(current))
                current = []
        index += 1
    if current:
        groups.append(" ".join(current))
    if len(groups) > 1 and all(_looks_like_job_title_fragment(group) for group in groups):
        return groups
    return [text]


def _split_job_title_candidates(job_directions: str) -> list[str]:
    bilingual_parts = _split_top_level(job_directions)
    if (
        len(bilingual_parts) == 2
        and not any(_TABLE_PROSE_RE.search(part) for part in bilingual_parts)
        and (
            (
                _LATIN_TITLE_RE.search(bilingual_parts[0])
                and _CJK_TITLE_RE.search(bilingual_parts[1])
            )
            or (
                _CJK_TITLE_RE.search(bilingual_parts[0])
                and _LATIN_TITLE_RE.search(bilingual_parts[1])
            )
        )
    ):
        return [job_directions.strip()]
    if (
        "、" in job_directions
        and len(bilingual_parts) > 1
        and not all(_looks_like_job_title_fragment(part) for part in bilingual_parts)
    ):
        return [job_directions.strip()]
    candidates: list[str] = []
    for raw_part in bilingual_parts:
        part = _strip_leading_job_label(raw_part).strip()
        candidates.extend(_split_whitespace_job_titles(part))
    return candidates


def split_table_job_titles(
    job_directions: str | None, company_name: str | None = None
) -> list[str]:
    """Return distinct, short job titles from the table's job field.

    A table fallback is only safe when its job field is already a delimited list.
    Long or generic fragments are rejected instead of being stored as a misleading
    all-jobs title.
    """

    if not isinstance(job_directions, str) or not job_directions.strip():
        return []
    titles: list[str] = []
    candidates = _split_job_title_candidates(job_directions)
    allow_short_category = len(candidates) > 1
    for raw_title in candidates:
        title = re.sub(r"^[\d一二三四五六七八九十]+[.)、]\s*", "", raw_title).strip()
        if not title or (
            len(title) > _MAX_TABLE_TITLE_CHARS
            and len(_title_without_parenthetical(title)) > _MAX_TABLE_TITLE_CHARS
        ):
            return []
        if _title_is_generic(title, company_name):
            return []
        if not _looks_like_job_title_fragment(title, allow_short_category=allow_short_category):
            return []
        if title not in titles:
            titles.append(title)
    return titles


def _fallback_source_job_id(row: SpreadsheetRow, title: str) -> str:
    source_record = (
        f"record:{row.source_record_id}" if row.source_record_id else f"row:{row.row_number}"
    )
    title_key = re.sub(r"\s+", "", title).casefold()
    digest = hashlib.sha256(title_key.encode("utf-8")).hexdigest()[:16]
    return f"table-fallback:{source_record}:{digest}"


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
        parsed_title = job.get("title")
        if isinstance(parsed_title, str) and (
            len(_split_job_title_candidates(parsed_title)) > 1
            or (
                len(parsed_title.strip()) > _MAX_TABLE_TITLE_CHARS
                and len(_title_without_parenthetical(parsed_title.strip())) > _MAX_TABLE_TITLE_CHARS
            )
        ):
            table_titles = split_table_job_titles(parsed_title, row.company_name)
            reasons.append("MULTI_JOB_TITLE" if len(table_titles) > 1 else "UNSAFE_JOB_TITLE")
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


def build_table_fallbacks(
    source_id: str,
    row: SpreadsheetRow,
    source_url: str,
    link_type: str,
    *,
    reason_codes: Sequence[str],
) -> list[CollectedJob]:
    if not row.company_name:
        raise ValueError("spreadsheet row has no company name")
    titles = split_table_job_titles(row.job_directions, row.company_name)
    if not titles:
        raise ValueError("spreadsheet row job directions cannot be split into safe job titles")
    http_url = source_url if source_url.startswith(("http://", "https://")) else None
    source_ref = (
        f"feishu-record:{row.source_record_id}"
        if row.source_record_id
        else f"table-row:{row.row_number}"
    )
    jobs: list[CollectedJob] = []
    for title in titles:
        metadata: JsonObject = {
            "collection_mode": "TABLE_FALLBACK",
            "quality_reasons": list(dict.fromkeys(reason_codes)),
            "fallback_link_type": link_type,
            "fallback_source_url": source_url,
            "table_row_number": row.row_number,
            "table_job_summary": row.job_directions,
            "table_job_title": title,
            **({"batch": row.batch} if row.batch is not None else {}),
        }
        jobs.append(
            CollectedJob(
                source_id=source_id,
                source_job_id=_fallback_source_job_id(row, title),
                company_name=row.company_name,
                company_nature=row.company_nature,
                title=title,
                locations=row.locations,
                description=None,
                detail_url=http_url,
                apply_url=http_url,
                recruitment_type=row.recruitment_type,
                education_requirement=row.education_requirement,
                graduation_years=row.graduation_years,
                deadline_at=row.deadline_at,
                source_ref=source_ref,
                metadata=metadata,
            )
        )
    return jobs


def build_table_fallback(
    source_id: str,
    row: SpreadsheetRow,
    source_url: str,
    link_type: str,
    *,
    reason_codes: Sequence[str],
) -> CollectedJob:
    """Build a single fallback for callers that already know the row is singular."""

    jobs = build_table_fallbacks(
        source_id,
        row,
        source_url,
        link_type,
        reason_codes=reason_codes,
    )
    if len(jobs) != 1:
        raise ValueError("table row contains multiple job titles; use build_table_fallbacks")
    return jobs[0]


__all__ = [
    "CollectionDecision",
    "CollectionQualityPolicy",
    "QualityDecision",
    "assess_parsed_jobs",
    "build_table_fallback",
    "build_table_fallbacks",
    "preflight_quality",
    "split_table_job_titles",
]
