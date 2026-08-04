"""Evidence-first adapter for the public PDD campus recruitment API."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json

_PAGE_SIZE = 10
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/api/careers/api/recruit/position/list"
_DETAIL_PATH = "/api/careers/api/recruit/position/detail"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "\n", str(value)))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text).strip()
    return text or None


def _locations(value: object) -> list[str]:
    return [item for item in re.split(r"[,，、/|;；\s]+", _text(value) or "") if item]


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("PDD API response is not an object")
    return value


def _result(response: object) -> Mapping[str, object]:
    root = _mapping(response)
    if str(root.get("success")).lower() != "true":
        raise ValueError(f"PDD API returned failure {root.get('errorCode')!r}")
    return _mapping(root.get("result"))


def _count(value: object) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("PDD API did not return a valid job count") from exc
    if result < 0:
        raise ValueError("PDD API returned a negative job count")
    return result


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query)
    payload: dict[str, object] = {"page": page, "pageSize": _PAGE_SIZE}
    recruit_types = query.get("recruitType", [])
    if recruit_types and (recruit_type := recruit_types[0]):
        payload["recruitTypeList"] = [recruit_type]
    for query_key in ("jobList", "workLocationList", "labelList"):
        values = [item for value in query.get(query_key, []) for item in value.split(",") if item]
        if values:
            payload[query_key] = values
    names = query.get("name", [])
    if names and (name := names[0]):
        payload["name"] = name
    return payload


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    origin = _origin(url)
    total: int | None = None
    items: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    page = 1
    while page <= _MAX_JOBS // _PAGE_SIZE + 1:
        result = _result(
            request_json(
                f"{origin}{_LIST_PATH}",
                "POST",
                _list_payload(url, page),
            )
        )
        if total is None:
            total = _count(result.get("total"))
            if total > _MAX_JOBS:
                raise ValueError(f"PDD API returned {total} jobs, above the safe limit")
            if total == 0:
                return [], 0
        page_items = result.get("list")
        if not isinstance(page_items, list):
            raise ValueError("PDD API did not return a position list")
        mapped_items = [_mapping(item) for item in page_items if isinstance(item, Mapping)]
        new_items = 0
        for item in mapped_items:
            job_id = _text(item.get("id"))
            if job_id and job_id not in seen_ids:
                seen_ids.add(job_id)
                items.append(item)
                new_items += 1
        if not mapped_items or new_items == 0:
            raise ValueError("PDD API returned an incomplete or repeated page")
        if len(items) >= total:
            return items[:total], total
        page += 1
    raise ValueError("PDD API pagination exceeded the safe page limit")


def _published_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)  # type: ignore[arg-type]
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _recruitment_type(value: str | None) -> str | None:
    if not value:
        return None
    if "实习" in value:
        return "实习"
    if any(marker in value for marker in ("校招", "应届", "管培", "校园")):
        return "校招"
    if "社招" in value or "社会" in value:
        return "社招"
    return None


def _detail(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    source_job_id = _text(item.get("id"))
    if not source_job_id:
        raise ValueError("PDD position has no id")
    origin = _origin(url)
    detail_endpoint = f"{origin}{_DETAIL_PATH}"
    detail = _result(request_json(detail_endpoint, "POST", {"id": source_job_id}))
    if detail.get("normal") is False:
        raise ValueError(f"PDD position {source_job_id} is not active")
    title = _text(detail.get("name")) or _text(item.get("name"))
    if not title:
        raise ValueError(f"PDD position {source_job_id} has no title")
    description = "\n".join(
        value
        for value in (
            _text(detail.get("jobDuty")),
            _text(detail.get("serveRequirement")),
            _text(detail.get("bonus")),
        )
        if value
    )
    if not description:
        raise ValueError(f"PDD position {source_job_id} has no public description")
    detail_url = urlunsplit(
        (
            urlsplit(url).scheme,
            urlsplit(url).netloc,
            "/campus/grad/detail",
            f"positionId={quote(source_job_id)}",
            "",
        )
    )
    recruitment_type_name = _text(detail.get("recruitTypeName")) or _text(
        item.get("recruitTypeName")
    )
    return {
        "source_job_id": source_job_id,
        "title": _text(detail.get("name")) or title,
        "description": description,
        "locations": _locations(detail.get("workLocationName") or item.get("workLocationName")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(recruitment_type_name),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("releaseTime") or item.get("releaseTime")),
        "deadline_at": None,
        "source_ref": detail_endpoint,
        "metadata": {
            "parser": "pdd",
            "platform_family": "pdd-global-hr",
            "record_kind": "job",
            "detail_status": "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "list_count": total,
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect all public PDD positions for a recruitment page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = request_json or (
        lambda endpoint, method, payload: _request_json(endpoint, url, method, payload)
    )
    direct_ids = parse_qs(urlsplit(url).query).get("positionId", [])
    if direct_ids and direct_ids[0].strip():
        return [_detail({"id": direct_ids[0]}, url, requester, 1)]
    items, total = _list_jobs(url, requester)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items) or 1)) as executor:
        return list(executor.map(lambda item: _detail(item, url, requester, total), items))


__all__ = ["parse"]
