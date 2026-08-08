"""Evidence-first adapter for the public OPPO recruitment API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json
from .public_api_support import (
    PublicPage,
    bind_requester,
    collect_pages,
    map_bounded,
    non_negative_int,
)
from .public_api_support import locations as _locations
from .public_api_support import mapping as _mapping
from .public_api_support import origin as _origin
from .public_api_support import published_at as _published_at
from .public_api_support import text as _text

_PAGE_SIZE = 10
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/openapi/position/pageNew"
_DETAIL_PATH = "/openapi/position/detail"


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response, "OPPO API response is not an object")
    if str(root.get("code")) != "0":
        raise ValueError(f"OPPO API returned code {root.get('code')!r}")
    return _mapping(root.get("data"), "OPPO API did not return data")


def _query_values(query: Mapping[str, list[str]], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        for raw in query.get(key, []):
            values.extend(item for item in raw.split(",") if item)
    return values


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    payload: dict[str, object] = {
        "pageNum": page,
        "pageSize": _PAGE_SIZE,
        "positionName": (
            _text(query.get("positionName", [""])[0])
            or _text(query.get("keyword", [""])[0])
            or _text(query.get("search", [""])[0])
            or ""
        ),
        "projectList": [],
        "positionTypeList": _query_values(query, "positionTypeList", "positionType"),
        "workCityCodeList": _query_values(query, "workCityCodeList", "workCityCode", "city"),
    }
    if share_id := _text(query.get("shareId", [""])[0]):
        payload["shareId"] = share_id
    return payload


def _source_job_id(item: Mapping[str, object]) -> str | None:
    return _text(item.get("idRecruitPosition")) or _text(item.get("idProjPosition"))


def _list_page(url: str, request_json: JsonRequester, page: int) -> PublicPage:
    data = _data(request_json(f"{_origin(url)}{_LIST_PATH}", "POST", _list_payload(url, page)))
    raw_items = data.get("records")
    if not isinstance(raw_items, list):
        raise ValueError("OPPO API did not return a position list")
    raw_pages = data.get("pages")
    return PublicPage(
        total=non_negative_int(data.get("total"), "OPPO API did not return a valid job count"),
        page_count=(
            non_negative_int(raw_pages, "OPPO API did not return a valid page count")
            if raw_pages is not None
            else None
        ),
        items=[_mapping(item, "OPPO API returned an invalid position") for item in raw_items],
    )


def _list_jobs(url: str, request_json: JsonRequester) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="OPPO",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=_source_job_id,
    )


def _description(item: Mapping[str, object]) -> str | None:
    duty = _text(item.get("positionDesc") or item.get("projectPositionDesc"))
    requirement = _text(item.get("positionRequire") or item.get("projectPositionRequire"))
    return "\n".join(value for value in (duty, requirement) if value) or None


def _detail_id(url: str) -> str | None:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    for key in ("id", "positionId", "idRecruitPosition"):
        if value := _text(query.get(key, [""])[0]):
            return value
    path_parts = [part for part in parts.path.split("/") if part]
    if "post" in path_parts:
        index = len(path_parts) - 1 - path_parts[::-1].index("post")
        if index + 1 < len(path_parts):
            return _text(path_parts[index + 1])
    return None


def _detail_if_needed(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
) -> Mapping[str, object]:
    if _description(item):
        return item
    source_job_id = _source_job_id(item)
    if not source_job_id:
        raise ValueError("OPPO position has no id")
    return _data(
        request_json(
            f"{_origin(url)}{_DETAIL_PATH}",
            "GET",
            {"id": source_job_id},
        )
    )


def _recruitment_type(*values: object) -> str | None:
    value = " ".join(item for item in (_text(value) for value in values) if item)
    folded = value.casefold()
    if "实习" in value or "intern" in folded:
        return "实习"
    if "社招" in value or "社会" in value or "social" in folded:
        return "社招"
    if any(marker in value for marker in ("校招", "校园", "应届", "博士")):
        return "校招"
    if any(marker in folded for marker in ("graduate", "campus", "doctor")):
        return "校招"
    return None


def _detail_url(url: str, source_job_id: str) -> str:
    parts = urlsplit(url)
    path = parts.path
    marker = "/campus/post" if "/campus/" in path else "/recruitment/post"
    marker_index = path.find(marker)
    base_path = path[:marker_index] + marker if marker_index >= 0 else marker
    return urlunsplit((parts.scheme, parts.netloc, f"{base_path}/{quote(source_job_id)}", "", ""))


def _job(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    detail = _detail_if_needed(item, url, request_json)
    source_job_id = _source_job_id(detail) or _source_job_id(item)
    title = _text(detail.get("positionName")) or _text(item.get("positionName"))
    description = _description(detail) or _description(item)
    if not source_job_id or not title:
        raise ValueError("OPPO position has no id or title")
    if not description:
        raise ValueError(f"OPPO position {source_job_id} has no public description")
    project_name = _text(detail.get("projectName")) or _text(item.get("projectName"))
    recruitment_type = _text(detail.get("recruitmentType")) or _text(item.get("recruitmentType"))
    detail_endpoint = f"{_origin(url)}{_DETAIL_PATH}"
    detail_url = _detail_url(url, source_job_id)
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(
            detail.get("workCityVOList")
            or detail.get("workCityName")
            or item.get("workCityVOList")
            or item.get("workCityName")
        ),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(
            detail.get("recruitmentTypeName"),
            item.get("recruitmentTypeName"),
            recruitment_type,
        ),
        "education_requirement": _text(detail.get("educationRequire"))
        or _text(item.get("educationRequire")),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("releaseTime") or item.get("releaseTime")),
        "deadline_at": None,
        "source_ref": f"{detail_endpoint}?id={quote(source_job_id)}",
        "metadata": {
            "parser": "oppo",
            "platform_family": "oppo-careers",
            "record_kind": "job",
            "detail_status": "list_api" if detail is item else "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "project_id": detail.get("projectId") or item.get("projectId"),
            "project_name": project_name,
            "position_type": _text(detail.get("positionType")) or _text(item.get("positionType")),
            "recruitment_type_code": recruitment_type,
            "position_status": detail.get("positionStatus")
            if detail.get("positionStatus") is not None
            else item.get("positionStatus"),
            "list_count": total,
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect all public OPPO campus positions for a recruitment page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, _request_json)
    direct_id = _detail_id(url)
    if direct_id is not None:
        return [_job({"idRecruitPosition": direct_id}, url, requester, 1)]
    items, total = _list_jobs(url, requester)
    return map_bounded(items, lambda item: _job(item, url, requester, total), max_workers)


__all__ = ["parse"]
