from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobpicky.contracts import CollectedJob, CollectionBatch
from jobpicky.contracts.common import JsonObject

from .link_classification import (
    BEISEN,
    COMPANY_RECRUITMENT_SITE,
    COMPANY_WEBSITE,
    CUSTOM_RECRUITMENT_SYSTEM,
    FEISHU,
    GOVERNMENT_NOTICE,
    GUOPIN,
    HOTJOB,
    JOB_51,
    MOKA,
    WECHAT,
    ZHAOPIN,
    classify_link,
)
from .parsers.beisen import parse as parse_beisen
from .parsers.feishu import parse as parse_feishu
from .parsers.guopin import parse as parse_guopin
from .parsers.hotjob import parse as parse_hotjob
from .parsers.job_51 import parse as parse_job_51
from .parsers.moka import parse as parse_moka
from .parsers.moka import source_identity as moka_source_identity
from .parsers.public_web import parse as parse_public_web
from .parsers.wechat import parse as parse_wechat
from .parsers.zhaopin import parse as parse_zhaopin
from .spreadsheet import SpreadsheetRow

Parser = Callable[[str], Sequence[Mapping[str, object]]]

# Keep routing visible and boring. Add a parser here only when it is implemented.
PARSERS: dict[str, Parser] = {
    BEISEN: lambda url: parse_beisen(url),
    COMPANY_RECRUITMENT_SITE: lambda url: parse_public_web(url),
    COMPANY_WEBSITE: lambda url: parse_public_web(url, allow_announcement=True),
    CUSTOM_RECRUITMENT_SYSTEM: lambda url: parse_public_web(url, allow_announcement=True),
    FEISHU: lambda url: parse_feishu(url),
    GOVERNMENT_NOTICE: lambda url: parse_public_web(url, allow_announcement=True),
    GUOPIN: lambda url: parse_guopin(url),
    HOTJOB: lambda url: parse_hotjob(url),
    JOB_51: lambda url: parse_job_51(url),
    MOKA: lambda url: parse_moka(url),
    WECHAT: lambda url: parse_wechat(url),
    ZHAOPIN: lambda url: parse_zhaopin(url),
}


@dataclass(frozen=True)
class UnsupportedLink:
    url: str
    link_type: str
    row_number: int
    reason: str
    company_name: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    batch: CollectionBatch
    unsupported: list[UnsupportedLink]


def source_id_for_entry(company_name: str, url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    hostname = (parts.hostname or "").lower()
    port = parts.port
    netloc = hostname
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    normalized_url = urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    moka_identity = moka_source_identity(url) if classify_link(url) == MOKA else None
    evidence = (
        f"moka\n{moka_identity}"
        if moka_identity is not None
        else f"{company_name.strip().casefold()}\n{normalized_url}"
    )
    return f"entry-{hashlib.sha256(evidence.encode()).hexdigest()[:20]}"


def _value(fields: Mapping[str, object], name: str) -> object | None:
    value = fields.get(name)
    return value if value not in (None, "", [], {}) else None


def _string(fields: Mapping[str, object], name: str) -> str | None:
    value = _value(fields, name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _website_job_key(fields: Mapping[str, object]) -> str | None:
    source_job_id = _string(fields, "source_job_id")
    if source_job_id:
        return f"source_job_id:{source_job_id}"
    detail_url = _string(fields, "detail_url")
    return f"detail_url:{detail_url}" if detail_url else None


def _metadata(row: SpreadsheetRow, website: Mapping[str, object]) -> JsonObject:
    metadata: JsonObject = {}
    website_metadata = website.get("metadata")
    if isinstance(website_metadata, dict):
        metadata.update(cast(JsonObject, website_metadata))
    metadata.update(
        {
            key: value
            for key, value in {
                "industry": row.industry,
                "batch": row.batch,
                "announcement_source": row.announcement_source,
                "announcement_url": row.announcement_url,
                "major_requirement": row.major_requirement,
                "has_written_test": row.has_written_test,
                "sheet_updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "table_job_summary": row.job_directions,
                "table_row_number": row.row_number,
            }.items()
            if value is not None
        }
    )
    return metadata


def merge_job_fields(
    source_id: str,
    row: SpreadsheetRow,
    website: Mapping[str, object],
) -> CollectedJob:
    title = _string(website, "title")
    if title is None:
        raise ValueError("website parser returned a job without title")
    if row.company_name is None:
        raise ValueError("spreadsheet row has no company name")

    website_locations = _value(website, "locations")
    locations = (
        [item.strip() for item in website_locations if isinstance(item, str) and item.strip()]
        if isinstance(website_locations, list)
        else row.locations
    )
    website_graduation_years = _value(website, "graduation_years")
    graduation_years = (
        [item for item in website_graduation_years if isinstance(item, int)]
        if isinstance(website_graduation_years, list)
        else row.graduation_years
    )

    salary_min = website.get("salary_min")
    salary_max = website.get("salary_max")
    salary_months = website.get("salary_months")
    published_at = website.get("published_at")
    deadline_at = website.get("deadline_at")
    website_metadata = website.get("metadata")
    record_kind = (
        website_metadata.get("record_kind") if isinstance(website_metadata, Mapping) else None
    )
    apply_url = _string(website, "apply_url")
    if apply_url is None and not (
        isinstance(record_kind, str) and record_kind.endswith("_announcement")
    ):
        apply_url = _string(website, "detail_url")
    return CollectedJob(
        source_id=source_id,
        source_job_id=_string(website, "source_job_id"),
        company_name=row.company_name,
        company_nature=row.company_nature,
        title=title,
        locations=locations,
        description=_string(website, "description"),
        detail_url=_string(website, "detail_url"),
        apply_url=apply_url,
        recruitment_type=_string(website, "recruitment_type") or row.recruitment_type,
        education_requirement=_string(website, "education_requirement")
        or row.education_requirement,
        salary_min=salary_min if isinstance(salary_min, int) else None,
        salary_max=salary_max if isinstance(salary_max, int) else None,
        salary_months=salary_months if isinstance(salary_months, int) else None,
        graduation_years=graduation_years,
        published_at=published_at if isinstance(published_at, datetime) else None,
        deadline_at=deadline_at if isinstance(deadline_at, datetime) else row.deadline_at,
        source_ref=_string(website, "source_ref") or f"table-row:{row.row_number}",
        metadata=_metadata(row, website),
    )


def run_pipeline(source_id: str, rows: Sequence[SpreadsheetRow]) -> PipelineResult:
    items: list[CollectedJob] = []
    unsupported: list[UnsupportedLink] = []
    warnings: list[str] = []
    seen_job_keys: set[str] = set()

    for row in rows:
        if not row.apply_links:
            warnings.append(f"row {row.row_number}: no application link")
            continue
        for url in row.apply_links:
            link_type = classify_link(url)
            parser = PARSERS.get(link_type)
            if parser is None:
                unsupported.append(
                    UnsupportedLink(
                        url=url,
                        link_type=link_type,
                        row_number=row.row_number,
                        reason=f"no parser implemented for link type {link_type}",
                        company_name=row.company_name,
                    )
                )
                continue
            try:
                website_jobs = parser(url)
            except Exception as exc:  # noqa: BLE001 - one source link must not stop the sheet
                unsupported.append(
                    UnsupportedLink(
                        url=url,
                        link_type=link_type,
                        row_number=row.row_number,
                        reason=f"parser failed: {type(exc).__name__}: {exc}",
                        company_name=row.company_name,
                    )
                )
                continue
            if not website_jobs:
                unsupported.append(
                    UnsupportedLink(
                        url=url,
                        link_type=link_type,
                        row_number=row.row_number,
                        reason="parser returned no jobs",
                        company_name=row.company_name,
                    )
                )
                continue
            for website_job in website_jobs:
                job_key = _website_job_key(website_job)
                if job_key is not None and job_key in seen_job_keys:
                    continue
                try:
                    items.append(merge_job_fields(source_id, row, website_job))
                    if job_key is not None:
                        seen_job_keys.add(job_key)
                except Exception as exc:  # noqa: BLE001 - retain the row/link failure
                    unsupported.append(
                        UnsupportedLink(
                            url=url,
                            link_type=link_type,
                            row_number=row.row_number,
                            reason=f"job fields invalid: {type(exc).__name__}: {exc}",
                            company_name=row.company_name,
                        )
                    )

    warnings.extend(
        f"row {failure.row_number}, {failure.link_type}, {failure.url}: {failure.reason}"
        for failure in unsupported
    )
    return PipelineResult(
        batch=CollectionBatch(
            source_id=source_id,
            items=items,
            complete=not unsupported and not warnings,
            method="spreadsheet+platform-parser",
            warnings=warnings,
            metrics={
                "spreadsheet_rows": len(rows),
                "collected_jobs": len(items),
                "unsupported_links": len(unsupported),
            },
        ),
        unsupported=unsupported,
    )


def run_pipeline_by_source(rows: Sequence[SpreadsheetRow]) -> list[PipelineResult]:
    grouped: dict[str, list[SpreadsheetRow]] = {}
    for row in rows:
        if row.company_name is None:
            continue
        for url in row.apply_links:
            source_id = source_id_for_entry(row.company_name, url)
            grouped.setdefault(source_id, []).append(replace(row, apply_links=[url]))
    return [run_pipeline(source_id, source_rows) for source_id, source_rows in grouped.items()]


__all__ = [
    "PARSERS",
    "PipelineResult",
    "UnsupportedLink",
    "merge_job_fields",
    "run_pipeline",
    "run_pipeline_by_source",
    "source_id_for_entry",
]
