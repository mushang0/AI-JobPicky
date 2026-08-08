"""Evidence-first adapter for the public NetEase campus API."""

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
from .public_api_support import published_at as _published_at
from .public_api_support import text as _text

_PAGE_SIZE = 100
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/api/campuspc/position/getJobList"
_DETAIL_PATH = "/api/campuspc/position/getJobDetails"
_API_ORIGIN = "https://campus.163.com"
_HR_DETAIL_PATH = "/api/hr163/position/query"
_HR_API_ORIGIN = "https://hr.163.com"


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response, "NetEase API response is not an object")
    if root.get("code") != 200:
        raise ValueError(f"NetEase API returned code {root.get('code')!r}")
    return _mapping(root.get("data"), "NetEase API did not return data")


def _project_id(url: str) -> str:
    values = parse_qs(urlsplit(url).query).get("id", [])
    project_id = _text(values[0]) if values else None
    if not project_id or not project_id.isdigit():
        raise ValueError("NetEase recruitment URL has no numeric project id")
    return project_id


def _list_page(
    project_id: str,
    request_json: JsonRequester,
    page: int,
) -> PublicPage:
    data = _data(
        request_json(
            f"{_API_ORIGIN}{_LIST_PATH}",
            "GET",
            {"projectId": project_id, "pageSize": _PAGE_SIZE, "currentPage": page},
        )
    )
    raw_items = data.get("list")
    if not isinstance(raw_items, list):
        raise ValueError("NetEase API did not return a position list")
    raw_page_count = data.get("pages")
    return PublicPage(
        total=non_negative_int(data.get("total"), "NetEase API did not return a valid job count"),
        page_count=(
            non_negative_int(raw_page_count, "NetEase API did not return a valid page count")
            if raw_page_count is not None
            else None
        ),
        items=[_mapping(item, "NetEase API returned an invalid position") for item in raw_items],
    )


def _list_jobs(
    project_id: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(project_id, request_json, page),
        source="NetEase",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=lambda item: _text(item.get("id")),
    )


def _recruitment_type(value: str | None) -> str | None:
    if not value:
        return None
    if "实习" in value:
        return "实习"
    if any(marker in value for marker in ("校招", "校园", "应届")):
        return "校招"
    if "社招" in value or "社会" in value:
        return "社招"
    return None


def _parse_hr_detail(url: str, request_json: JsonRequester) -> list[dict[str, object]]:
    values = parse_qs(urlsplit(url).query).get("id", [])
    source_job_id = _text(values[0]) if values else None
    if not source_job_id or not source_job_id.isdigit():
        raise ValueError("NetEase HR URL has no numeric position id")
    endpoint = f"{_HR_API_ORIGIN}{_HR_DETAIL_PATH}"
    root = _mapping(
        request_json(endpoint, "GET", {"id": source_job_id}),
        "NetEase HR API response is not an object",
    )
    if root.get("code") != 200:
        raise ValueError(f"NetEase HR API returned code {root.get('code')!r}")
    detail = _mapping(root.get("data"), "NetEase HR API did not return data")
    title = _text(detail.get("name"))
    description = "\n".join(
        value
        for value in (_text(detail.get("description")), _text(detail.get("requirement")))
        if value
    )
    if not title or not description:
        raise ValueError(f"NetEase HR position {source_job_id} has no public title or description")
    source_parts = urlsplit(url)
    detail_url = urlunsplit(
        (source_parts.scheme, source_parts.netloc, source_parts.path, source_parts.query, "")
    )
    return [
        {
            "source_job_id": source_job_id,
            "title": title,
            "description": description,
            "locations": _locations(detail.get("workPlaceNameList")),
            "detail_url": detail_url,
            "apply_url": detail_url,
            "recruitment_type": _recruitment_type(_text(detail.get("workType"))),
            "education_requirement": _text(detail.get("reqEducationName")),
            "salary_min": None,
            "salary_max": None,
            "salary_months": None,
            "published_at": _published_at(detail.get("updateTime")),
            "deadline_at": None,
            "source_ref": f"{endpoint}?id={quote(source_job_id)}",
            "metadata": {
                "parser": "netease-hr",
                "platform_family": "netease-hr",
                "record_kind": "job",
                "detail_status": "public_api",
                "detail_api_route": _HR_DETAIL_PATH,
                "list_count": 1,
            },
        }
    ]


def _detail_if_needed(
    item: Mapping[str, object],
    project_id: str,
    source_url: str,
    request_json: JsonRequester,
) -> Mapping[str, object]:
    description = "\n".join(
        value
        for value in (
            _text(item.get("positionDescription")),
            _text(item.get("positionRequirement")),
        )
        if value
    )
    if description:
        return item
    source_job_id = _text(item.get("id"))
    if not source_job_id:
        raise ValueError("NetEase position has no id")
    detail = _data(
        request_json(
            f"{_API_ORIGIN}{_DETAIL_PATH}",
            "GET",
            {"id": source_job_id, "projectId": project_id},
        )
    )
    return detail


def _job(
    item: Mapping[str, object],
    project_id: str,
    source_url: str,
    request_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    detail = _detail_if_needed(item, project_id, source_url, request_json)
    source_job_id = _text(detail.get("id")) or _text(item.get("id"))
    title = _text(detail.get("positionName")) or _text(item.get("positionName"))
    if not source_job_id or not title:
        raise ValueError("NetEase position has no id or title")
    description = "\n".join(
        value
        for value in (
            _text(detail.get("positionDescription")),
            _text(detail.get("positionRequirement")),
        )
        if value
    )
    if not description:
        raise ValueError(f"NetEase position {source_job_id} has no public description")
    detail_url = urlunsplit(
        (
            urlsplit(source_url).scheme,
            urlsplit(source_url).netloc,
            "/app/detail/index",
            f"id={quote(source_job_id)}&projectId={quote(project_id)}",
            "",
        )
    )
    project_name = _text(detail.get("projectName")) or _text(item.get("projectName"))
    position_type = _text(detail.get("positionTypeName")) or _text(item.get("positionTypeName"))
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("workPlaceName") or item.get("workPlaceName")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(project_name) or _recruitment_type(position_type),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("publishTime") or item.get("publishTime")),
        "deadline_at": None,
        "source_ref": (
            f"{_API_ORIGIN}{_DETAIL_PATH}?id={quote(source_job_id)}&projectId={quote(project_id)}"
        ),
        "metadata": {
            "parser": "netease",
            "platform_family": "netease-campus",
            "record_kind": "job",
            "detail_status": "list_api" if detail is item else "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "project_id": project_id,
            "list_count": total,
        },
    }


def parse(url: str, request_json: JsonRequester | None = None) -> list[dict[str, object]]:
    """Collect all public NetEase positions for a project page."""
    requester = bind_requester(url, request_json, _request_json)
    if (urlsplit(url).hostname or "").casefold().endswith("hr.163.com"):
        return _parse_hr_detail(url, requester)
    project_id = _project_id(url)
    items, total = _list_jobs(project_id, requester)
    return map_bounded(
        items,
        lambda item: _job(item, project_id, url, requester, total),
        _MAX_WORKERS,
    )


__all__ = ["parse"]
