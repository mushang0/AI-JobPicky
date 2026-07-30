from __future__ import annotations

import re
from collections.abc import Iterable

from ..contracts import JobFact

_WHITESPACE = re.compile(r"[^\S\r\n]+")
MAX_EMBEDDING_TOKENS = 512
_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\w\s]", re.UNICODE)


def normalize_embedding_text(text: str) -> str:
    """Normalize text shared by query and document embedding inputs."""
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def truncate_embedding_text(text: str, max_tokens: int = MAX_EMBEDDING_TOKENS) -> str:
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    normalized = normalize_embedding_text(text)
    tokens = list(_TOKEN.finditer(normalized))
    if len(tokens) <= max_tokens:
        return normalized
    return normalized[: tokens[max_tokens - 1].end()]


def build_job_embedding_text(
    job: JobFact,
    *,
    max_tokens: int = MAX_EMBEDDING_TOKENS,
) -> str:
    """Build the canonical, deterministic text represented by one job vector."""
    fields: list[str] = [
        f"岗位名称：{job.title}",
        f"工作地点：{'、'.join(job.locations)}" if job.locations else "",
        f"招聘性质：{job.recruitment_type}" if job.recruitment_type else "",
        f"学历要求：{job.education_requirement}" if job.education_requirement else "",
        (
            f"届次要求：{'、'.join(str(year) for year in job.graduation_years)}"
            if job.graduation_years
            else ""
        ),
        (
            f"薪资范围：{job.salary_min or ''}-{job.salary_max or ''}元"
            if job.salary_min is not None or job.salary_max is not None
            else ""
        ),
        f"岗位描述：{job.description}" if job.description else "",
    ]
    return truncate_embedding_text("\n".join(field for field in fields if field), max_tokens)


def build_query_embedding_text(
    parts: Iterable[str | None],
    *,
    max_tokens: int = MAX_EMBEDDING_TOKENS,
) -> str:
    return truncate_embedding_text("\n".join(part for part in parts if part), max_tokens)


__all__ = [
    "MAX_EMBEDDING_TOKENS",
    "build_job_embedding_text",
    "build_query_embedding_text",
    "normalize_embedding_text",
    "truncate_embedding_text",
]
