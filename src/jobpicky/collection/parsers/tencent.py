"""Evidence-first adapter for the public Tencent campus recruitment API."""

from __future__ import annotations

import html
import math
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from .public_api import JsonRequester, request_json

_PAGE_SIZE = 1000
_MAX_JOBS = 1000
_MAX_WORKERS = 8
_LIST_PATH = "/api/v1/position/searchPosition"
_DETAIL_PATH = "/api/v1/jobDetails/getJobDetailsByPostId"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "\n", str(value)))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text).strip()
    return text or None


def _list_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in (_clean(child) for child in value) if item]
    text = _clean(value)
    return [item for item in re.split(r"[,，、|;；\s]+", text or "") if item]


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Tencent API response is not an object")
    return value


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response)
    if root.get("status") != 0:
        raise ValueError(f"Tencent API returned status {root.get('status')!r}")
    data = root.get("data")
    return _mapping(data)


def _http_json(
    endpoint: str,
    source_url: str,
    method: str,
    payload: Mapping[str, object] | None,
) -> object:
    return request_json(endpoint, source_url, method, payload)


def _filters(url: str) -> dict[str, list[int]]:
    values = parse_qs(urlsplit(url).query).get("query", [])
    filters: dict[str, list[int]] = {
        "projectIdList": [],
        "projectMappingIdList": [],
        "bgList": [],
        "workCityList": [],
        "recruitCityList": [],
        "positionFidList": [],
    }
    for value in values:
        for token in value.split(","):
            prefix, _, raw_id = token.partition("_")
            if not raw_id or not raw_id.isdigit():
                continue
            key = {
                "p": "projectIdList",
                "w": "workCityList",
                "r": "recruitCityList",
                "b": "bgList",
            }.get(prefix)
            if key is None and prefix.isdigit():
                key = "positionFidList"
            if key is not None:
                filters[key].append(int(raw_id))
    return filters


def _list_payload(url: str, page_index: int) -> dict[str, object]:
    payload: dict[str, object] = {
        **_filters(url),
        "keyword": "",
        "workCountryType": 0,
        "pageIndex": page_index,
        "pageSize": _PAGE_SIZE,
    }
    return payload


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int, dict[str, list[int]]]:
    origin = _origin(url)
    first_payload = _list_payload(url, 1)
    first = _data(request_json(f"{origin}{_LIST_PATH}", "POST", first_payload))
    total_value = first.get("count")
    if not isinstance(total_value, int) or total_value < 0:
        raise ValueError("Tencent API did not return a valid job count")
    if total_value > _MAX_JOBS:
        raise ValueError(f"Tencent API returned {total_value} jobs, above the safe limit")
    first_items = first.get("positionList")
    if not isinstance(first_items, list):
        raise ValueError("Tencent API did not return positionList")
    pages = max(1, math.ceil(total_value / _PAGE_SIZE))
    items: list[Mapping[str, object]] = [
        _mapping(item) for item in first_items if isinstance(item, Mapping)
    ]
    for page_index in range(2, pages + 1):
        response = _data(
            request_json(
                f"{origin}{_LIST_PATH}",
                "POST",
                _list_payload(url, page_index),
            )
        )
        page_items = response.get("positionList")
        if not isinstance(page_items, list):
            raise ValueError("Tencent API returned an incomplete page")
        items.extend(_mapping(item) for item in page_items if isinstance(item, Mapping))
    if len(items) < total_value:
        raise ValueError(f"Tencent API returned {len(items)} of {total_value} jobs")
    return items[:total_value], total_value, _filters(url)


def _detail(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
) -> dict[str, object]:
    source_job_id = _clean(item.get("postId"))
    title = _clean(item.get("positionTitle"))
    if not source_job_id or not title:
        raise ValueError("Tencent position has no postId or title")
    origin = _origin(url)
    detail_endpoint = f"{origin}{_DETAIL_PATH}?postId={quote(source_job_id)}"
    detail = _data(request_json(detail_endpoint, "GET", None))
    description = "\n".join(
        value for key in ("desc", "request") if (value := _clean(detail.get(key)))
    )
    if not description:
        raise ValueError(f"Tencent position {source_job_id} has no public description")
    detail_url = f"{origin}/post_detail.html?postid={quote(source_job_id)}"
    project_name = _clean(item.get("projectName")) or _clean(item.get("recruitLabelName"))
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _list_values(detail.get("workCityList") or item.get("workCities")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": (
            "实习"
            if project_name and "实习" in project_name
            else "校招"
            if project_name and any(marker in project_name for marker in ("校招", "应届"))
            else "社招"
            if project_name and "社招" in project_name
            else None
        ),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": None,
        "deadline_at": None,
        "source_ref": detail_endpoint,
        "metadata": {
            "parser": "tencent",
            "platform_family": "tencent-campus",
            "record_kind": "job",
            "detail_status": "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect all public Tencent positions for a recruitment page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = request_json or (
        lambda endpoint, method, payload: _http_json(endpoint, url, method, payload)
    )
    items, total, filters = _list_jobs(url, requester)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items) or 1)) as executor:
        jobs = list(executor.map(lambda item: _detail(item, url, requester), items))
    for job in jobs:
        metadata = job["metadata"]
        if isinstance(metadata, dict):
            metadata["list_count"] = total
            metadata["query_filters"] = filters
    return jobs


__all__ = ["parse"]
