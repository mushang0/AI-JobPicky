from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobpicky.contracts import CollectedJob, CollectionBatch
from jobpicky.contracts.common import JsonObject

from .company_profiles import find_company_profile
from .link_classification import (
    BEISEN,
    COMPANY_RECRUITMENT_SITE,
    COMPANY_WEBSITE,
    CUSTOM_RECRUITMENT_SYSTEM,
    EMAIL,
    FEISHU,
    FORM_OR_SHORT,
    GOVERNMENT_NOTICE,
    GUOPIN,
    HOTJOB,
    JOB_51,
    MOKA,
    PUBLIC_RECRUITMENT_PORTAL,
    WECHAT,
    ZHAOPIN,
    classify_link,
)
from .parsers.beisen import parse as parse_beisen
from .parsers.company_recruitment import parse as parse_company_recruitment
from .parsers.email import parse as parse_email
from .parsers.feishu import parse as parse_feishu
from .parsers.form import parse as parse_form
from .parsers.guopin import parse as parse_guopin
from .parsers.hotjob import parse as parse_hotjob
from .parsers.job_51 import parse as parse_job_51
from .parsers.moka import parse as parse_moka
from .parsers.moka import source_identity as moka_source_identity
from .parsers.public_web import parse as parse_public_web
from .parsers.wechat import parse as parse_wechat
from .parsers.zhaopin import parse as parse_zhaopin
from .quality import (
    CollectionQualityPolicy,
    assess_parsed_jobs,
    build_table_fallbacks,
    preflight_quality,
)
from .spreadsheet import SpreadsheetRow

Parser = Callable[[str], Sequence[Mapping[str, object]]]

# Keep routing visible and boring. Add a parser here only when it is implemented.
PARSERS: dict[str, Parser] = {
    BEISEN: lambda url: parse_beisen(url),
    COMPANY_RECRUITMENT_SITE: lambda url: parse_company_recruitment(url),
    COMPANY_WEBSITE: lambda url: parse_public_web(url, allow_announcement=True),
    CUSTOM_RECRUITMENT_SYSTEM: lambda url: parse_public_web(url, allow_announcement=True),
    EMAIL: lambda url: parse_email(url),
    FEISHU: lambda url: parse_feishu(url),
    FORM_OR_SHORT: lambda url: parse_form(url),
    GOVERNMENT_NOTICE: lambda url: parse_public_web(url, allow_announcement=True),
    GUOPIN: lambda url: parse_guopin(url),
    HOTJOB: lambda url: parse_hotjob(url),
    JOB_51: lambda url: parse_job_51(url),
    MOKA: lambda url: parse_moka(url),
    PUBLIC_RECRUITMENT_PORTAL: lambda url: parse_public_web(url, allow_announcement=True),
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
class SkippedLink:
    url: str
    link_type: str
    row_number: int
    reason: str
    company_name: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    batch: CollectionBatch
    unsupported: list[UnsupportedLink]
    skipped: list[SkippedLink]


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
                "feishu_record_id": row.source_record_id,
                "feishu_last_modified_at": (
                    row.source_last_modified_at.isoformat() if row.source_last_modified_at else None
                ),
                "sheet_updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "table_job_summary": row.job_directions,
                "table_row_number": row.row_number,
            }.items()
            if value is not None
        }
    )
    if row.apply_links:
        profile = find_company_profile(row.apply_links[0], row.company_name)
        if profile is not None:
            metadata.update(profile.metadata())
    return metadata


def merge_job_fields(
    source_id: str,
    row: SpreadsheetRow,
    website: Mapping[str, object],
    *,
    collection_mode: str = "PARSED",
    quality_reasons: Sequence[str] = (),
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
    table_url = row.apply_links[0] if row.apply_links else None
    detail_url = _string(website, "detail_url") or table_url
    apply_url = _string(website, "apply_url")
    if apply_url is None and not (
        isinstance(record_kind, str) and record_kind.endswith("_announcement")
    ):
        apply_url = detail_url
    return CollectedJob(
        source_id=source_id,
        source_job_id=_string(website, "source_job_id"),
        company_name=row.company_name,
        company_nature=row.company_nature,
        title=title,
        locations=locations,
        description=_string(website, "description") or row.job_directions,
        detail_url=detail_url,
        apply_url=apply_url,
        recruitment_type=row.recruitment_type or _string(website, "recruitment_type"),
        education_requirement=_string(website, "education_requirement")
        or row.education_requirement,
        salary_min=salary_min if isinstance(salary_min, int) else None,
        salary_max=salary_max if isinstance(salary_max, int) else None,
        salary_months=salary_months if isinstance(salary_months, int) else None,
        graduation_years=graduation_years,
        published_at=published_at if isinstance(published_at, datetime) else None,
        deadline_at=deadline_at if isinstance(deadline_at, datetime) else row.deadline_at,
        source_ref=_string(website, "source_ref")
        or (
            f"feishu-record:{row.source_record_id}"
            if row.source_record_id
            else f"table-row:{row.row_number}"
        ),
        metadata={
            **_metadata(row, website),
            "collection_mode": collection_mode,
            **({"quality_reasons": list(quality_reasons)} if quality_reasons else {}),
        },
    )


def run_pipeline(
    source_id: str,
    rows: Sequence[SpreadsheetRow],
    *,
    policy: CollectionQualityPolicy | None = None,
    now: datetime | None = None,
) -> PipelineResult:
    quality_policy = policy or CollectionQualityPolicy()
    items: list[CollectedJob] = []
    unsupported: list[UnsupportedLink] = []
    skipped: list[SkippedLink] = []
    warnings: list[str] = []
    seen_job_keys: set[str] = set()

    def add_fallback(
        row: SpreadsheetRow,
        url: str,
        link_type: str,
        reason_codes: Sequence[str],
    ) -> bool:
        try:
            items.extend(
                build_table_fallbacks(source_id, row, url, link_type, reason_codes=reason_codes)
            )
            return True
        except Exception as exc:  # noqa: BLE001 - retain the row/link failure
            unsupported.append(
                UnsupportedLink(
                    url=url,
                    link_type=link_type,
                    row_number=row.row_number,
                    reason=f"table fallback failed: {type(exc).__name__}: {exc}",
                    company_name=row.company_name,
                )
            )
            return False

    def note_fallback(
        row: SpreadsheetRow,
        url: str,
        link_type: str,
        reason_codes: Sequence[str],
    ) -> None:
        if add_fallback(row, url, link_type, reason_codes):
            warnings.append(
                f"row {row.row_number}, {link_type}, {url}: table fallback, "
                f"{', '.join(reason_codes)}"
            )
        else:
            warnings.append(
                f"row {row.row_number}, {link_type}, {url}: table fallback rejected, "
                f"{', '.join(reason_codes)}"
            )

    for row in rows:
        if not row.apply_links:
            warnings.append(f"row {row.row_number}: no application link")
            continue
        for url in row.apply_links:
            link_type = classify_link(url)
            preflight = preflight_quality(link_type, row, quality_policy, now=now)
            if preflight is not None:
                if preflight.decision == "SKIP_STALE":
                    skipped.append(
                        SkippedLink(
                            url=url,
                            link_type=link_type,
                            row_number=row.row_number,
                            reason=", ".join(preflight.reason_codes),
                            company_name=row.company_name,
                        )
                    )
                    warnings.append(
                        f"row {row.row_number}, {link_type}, {url}: skipped, "
                        f"{', '.join(preflight.reason_codes)}"
                    )
                else:
                    note_fallback(row, url, link_type, preflight.reason_codes)
                continue

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
                note_fallback(row, url, link_type, ("NO_PARSER",))
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
                note_fallback(row, url, link_type, ("PARSER_FAILED",))
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
                note_fallback(row, url, link_type, ("PARSER_EMPTY",))
                continue

            decision = assess_parsed_jobs(
                link_type,
                row,
                website_jobs,
                quality_policy,
                now=now,
            )
            if decision.decision == "SKIP_STALE":
                skipped.append(
                    SkippedLink(
                        url=url,
                        link_type=link_type,
                        row_number=row.row_number,
                        reason=", ".join(decision.reason_codes),
                        company_name=row.company_name,
                    )
                )
                warnings.append(
                    f"row {row.row_number}, {link_type}, {url}: skipped, "
                    f"{', '.join(decision.reason_codes)}"
                )
                continue
            if decision.decision == "FALLBACK_TO_TABLE":
                note_fallback(row, url, link_type, decision.reason_codes)
                continue

            prepared: list[tuple[CollectedJob, str | None]] = []
            try:
                for website_job in website_jobs:
                    job_key = _website_job_key(website_job)
                    if job_key is not None and job_key in seen_job_keys:
                        continue
                    prepared.append(
                        (
                            merge_job_fields(
                                source_id,
                                row,
                                website_job,
                                quality_reasons=decision.reason_codes,
                            ),
                            job_key,
                        )
                    )
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
                note_fallback(row, url, link_type, ("JOB_FIELDS_INVALID",))
                continue
            for item, job_key in prepared:
                items.append(item)
                if job_key is not None:
                    seen_job_keys.add(job_key)

    warnings.extend(
        f"row {failure.row_number}, {failure.link_type}, {failure.url}: {failure.reason}"
        for failure in unsupported
    )
    return PipelineResult(
        batch=CollectionBatch(
            source_id=source_id,
            items=items,
            complete=not unsupported and not warnings and not skipped,
            method="spreadsheet+platform-parser",
            warnings=warnings,
            metrics={
                "spreadsheet_rows": len(rows),
                "collected_jobs": len(items),
                "unsupported_links": len(unsupported),
                "table_fallback_jobs": sum(
                    item.metadata.get("collection_mode") == "TABLE_FALLBACK" for item in items
                ),
                "skipped_stale": len(skipped),
                "parsed_jobs": sum(
                    item.metadata.get("collection_mode") == "PARSED" for item in items
                ),
            },
        ),
        unsupported=unsupported,
        skipped=skipped,
    )


def run_pipeline_by_source(
    rows: Sequence[SpreadsheetRow],
    *,
    policy: CollectionQualityPolicy | None = None,
    now: datetime | None = None,
) -> list[PipelineResult]:
    grouped: dict[str, list[SpreadsheetRow]] = {}
    for row in rows:
        if row.company_name is None:
            continue
        for url in row.apply_links:
            source_id = source_id_for_entry(row.company_name, url)
            grouped.setdefault(source_id, []).append(replace(row, apply_links=[url]))
    return [
        run_pipeline(source_id, source_rows, policy=policy, now=now)
        for source_id, source_rows in grouped.items()
    ]


__all__ = [
    "PARSERS",
    "PipelineResult",
    "SkippedLink",
    "UnsupportedLink",
    "merge_job_fields",
    "run_pipeline",
    "run_pipeline_by_source",
    "source_id_for_entry",
]
