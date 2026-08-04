"""Evidence-first adapter for public Phenom career-site job pages."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

from .public_web import _date, _text, _url
from .public_web import _locations as _public_locations
from .public_web import fetch_html as _fetch_html

_MAX_PAGE_CHARS = 8 * 1024 * 1024
_DDO_MARKER = "phApp.ddo"


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def _ddo(page: str) -> Mapping[str, object]:
    if len(page.encode("utf-8")) > _MAX_PAGE_CHARS:
        raise ValueError("Phenom career page exceeds the safe response limit")
    marker = page.find(_DDO_MARKER)
    if marker < 0:
        raise ValueError("Phenom career page has no public job data")
    start = page.find("{", marker)
    if start < 0:
        raise ValueError("Phenom career page has invalid public job data")
    try:
        value, _ = json.JSONDecoder().raw_decode(page[start:])
    except json.JSONDecodeError as exc:
        raise ValueError("Phenom career page has invalid public job data") from exc
    return _mapping(value, "Phenom career page did not return an object")


def _detail_job(ddo: Mapping[str, object]) -> Mapping[str, object]:
    job_detail = _mapping(ddo.get("jobDetail"), "Phenom page has no public job detail")
    data = _mapping(job_detail.get("data"), "Phenom page has no public job detail data")
    return _mapping(data.get("job"), "Phenom page has no public job record")


def _locations(job: Mapping[str, object]) -> list[str]:
    locations: list[str] = []
    for value in (
        job.get("multi_location"),
        job.get("standardised_multi_location"),
        job.get("location"),
        job.get("cityStateCountry"),
        job.get("cityState"),
    ):
        for location in _public_locations(value):
            if location not in locations:
                locations.append(location)
        if locations:
            break
    if locations:
        return locations
    for value in (job.get("multi_location"), job.get("standardised_multi_location")):
        if not isinstance(value, list):
            continue
        for child in value:
            if not isinstance(child, Mapping):
                continue
            mapped_location = _text(
                child.get("location")
                or child.get("cityStateCountry")
                or child.get("cityState")
                or child.get("city")
            )
            if mapped_location and mapped_location not in locations:
                locations.append(mapped_location)
    return locations


def _recruitment_type(*values: object) -> str | None:
    text = " ".join(value for value in (_text(item) for item in values) if value)
    folded = text.casefold()
    if "实习" in text or re.search(r"\bintern(?:ship)?\b", folded):
        return "实习"
    if "社招" in text or "社会招聘" in text or re.search(r"\bsocial\b", folded):
        return "社招"
    if any(marker in text for marker in ("校招", "校园", "应届", "秋招", "春招")) or re.search(
        r"\bcampus\b", folded
    ):
        return "校招"
    return None


def _job(job: Mapping[str, object], url: str) -> dict[str, object]:
    source_job_id = _text(job.get("jobId") or job.get("reqId") or job.get("cmsJobId"))
    title = _text(job.get("title"))
    description = _text(job.get("description") or job.get("ml_Description"))
    if not source_job_id or not title or not description:
        raise ValueError("Phenom public job record has no id, title, or description")
    detail_url = urlunsplit((*urlsplit(url)[:4], ""))
    apply_url = _url(job.get("applyUrl"), url) or detail_url
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(job),
        "detail_url": detail_url,
        "apply_url": apply_url,
        "recruitment_type": _recruitment_type(title, job.get("jobType"), job.get("type")),
        "education_requirement": _text(
            job.get("education") or job.get("educationRequirement") or job.get("degree")
        ),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _date(job.get("postedDate") or job.get("dateCreated")),
        "deadline_at": _date(job.get("validThrough") or job.get("expirationDate")),
        "source_ref": detail_url,
        "metadata": {
            "parser": "phenom",
            "platform_family": "phenom-careers",
            "record_kind": "job",
            "detail_status": "embedded_public_data",
            "ats": _text(job.get("ats")),
            "ref_num": _text(job.get("refNum")),
            "job_seq_no": _text(job.get("jobSeqNo")),
        },
    }


def parse(url: str, fetch: Callable[[str], str] = _fetch_html) -> list[dict[str, object]]:
    """Parse a Phenom public detail page without calling application endpoints."""
    page = fetch(url)
    return [_job(_detail_job(_ddo(page)), url)]


__all__ = ["parse"]
