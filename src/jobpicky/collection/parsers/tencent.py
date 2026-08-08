"""Evidence-first adapter for the public Tencent campus recruitment API."""

from __future__ import annotations

import math
from collections.abc import Mapping
from urllib.parse import parse_qs, quote, urlsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json
from .public_api_support import (
    PublicPage,
    bind_requester,
    collect_pages,
    map_bounded,
    non_negative_int,
)
from .public_api_support import locations as _list_values
from .public_api_support import mapping as _mapping
from .public_api_support import origin as _origin
from .public_api_support import text as _clean

_PAGE_SIZE = 1000
_MAX_JOBS = 1000
_MAX_WORKERS = 8
_LIST_PATH = "/api/v1/position/searchPosition"
_DETAIL_PATH = "/api/v1/jobDetails/getJobDetailsByPostId"


class _ClosedPositionError(ValueError):
    """The detail API explicitly reports that a listed position is closed."""


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response, "Tencent API response is not an object")
    if root.get("status") != 0:
        raise ValueError(f"Tencent API returned status {root.get('status')!r}")
    data = root.get("data")
    return _mapping(data, "Tencent API did not return data")


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


def _list_page(
    url: str,
    request_json: JsonRequester,
    page_index: int,
) -> PublicPage:
    data = _data(
        request_json(
            f"{_origin(url)}{_LIST_PATH}",
            "POST",
            _list_payload(url, page_index),
        )
    )
    total = non_negative_int(data.get("count"), "Tencent API did not return a valid job count")
    raw_items = data.get("positionList")
    if not isinstance(raw_items, list):
        raise ValueError("Tencent API did not return positionList")
    return PublicPage(
        total=total,
        page_count=max(1, math.ceil(total / _PAGE_SIZE)),
        items=[_mapping(item, "Tencent API returned an invalid position") for item in raw_items],
    )


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int, dict[str, list[int]]]:
    items, total = collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="Tencent",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=lambda item: _clean(item.get("postId")),
    )
    return items, total, _filters(url)


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
    response = request_json(detail_endpoint, "GET", None)
    if (
        isinstance(response, Mapping)
        and str(response.get("status")) == "404"
        and _clean(response.get("message")) == "岗位已下架"
    ):
        raise _ClosedPositionError(f"Tencent position {source_job_id} is closed")
    detail = _data(response)
    description = "\n".join(
        value
        for key in ("desc", "request", "topicDetail", "topicRequirement")
        if (value := _clean(detail.get(key)))
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


def _detail_or_skip_closed(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
) -> dict[str, object] | None:
    try:
        return _detail(item, url, request_json)
    except _ClosedPositionError:
        return None


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect all public Tencent positions for a recruitment page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, _request_json)
    items, total, filters = _list_jobs(url, requester)
    results = map_bounded(
        items,
        lambda item: _detail_or_skip_closed(item, url, requester),
        max_workers,
    )
    jobs = [job for job in results if job is not None]
    closed_position_count = len(items) - len(jobs)
    for job in jobs:
        metadata = job["metadata"]
        if isinstance(metadata, dict):
            metadata["list_count"] = total
            metadata["query_filters"] = filters
            metadata["closed_position_count"] = closed_position_count
    return jobs


__all__ = ["parse"]
