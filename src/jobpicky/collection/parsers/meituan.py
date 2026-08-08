"""Evidence-first adapter for the public Meituan recruitment API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json
from .public_api_support import (
    PublicPage,
    bind_requester,
    collect_pages,
    map_bounded,
    non_negative_int,
)
from .public_api_support import (
    locations as _locations,
)
from .public_api_support import (
    mapping as _mapping,
)
from .public_api_support import (
    origin as _origin,
)
from .public_api_support import (
    published_at as _published_at,
)
from .public_api_support import (
    text as _text,
)

_PAGE_SIZE = 500
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/api/official/job/getJobList"
_DETAIL_PATH = "/api/official/job/getJobDetail"

_ROUTE_FILTERS: dict[str, tuple[list[dict[str, object]], list[str]]] = {
    "campus": (
        [{"code": "1", "subCode": []}, {"code": "2", "subCode": []}],
        [],
    ),
    "beidou": (
        [
            {"code": "1", "subCode": ["1-3"]},
            {"code": "2", "subCode": ["2-3"]},
        ],
        ["1-3", "2-3"],
    ),
    "qihang": (
        [
            {"code": "1", "subCode": ["1-4"]},
            {"code": "2", "subCode": ["2-4"]},
        ],
        ["1-4", "2-4"],
    ),
    "trainee": (
        [
            {"code": "1", "subCode": ["1-7"]},
            {"code": "2", "subCode": ["2-7"]},
        ],
        ["1-7", "2-7"],
    ),
    "longcat": (
        [
            {"code": "1", "subCode": ["1-8"]},
            {"code": "2", "subCode": ["2-8"]},
        ],
        ["1-8", "2-8"],
    ),
    "social": ([{"code": "3", "subCode": []}], []),
}


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response, "Meituan API response is not an object")
    if root.get("status") not in (1, "1"):
        raise ValueError(f"Meituan API returned status {root.get('status')!r}")
    return _mapping(root.get("data"), "Meituan API did not return data")


def _route(url: str) -> str | None:
    path = urlsplit(url).path.casefold().rstrip("/")
    if path.startswith("/web/"):
        candidate = path.removeprefix("/web/")
        if candidate in _ROUTE_FILTERS:
            return candidate
    return None


def _query_first(query: Mapping[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        for value in query.get(key, []):
            if cleaned := _text(value):
                return cleaned
    return None


def _query_values(query: Mapping[str, list[str]], key: str) -> list[str]:
    return [
        cleaned
        for value in query.get(key, [])
        for item in value.split(",")
        if (cleaned := _text(item))
    ]


def _list_payload(url: str, route: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query)
    job_type, type_code = _ROUTE_FILTERS[route]
    job_type_payload: list[dict[str, object]] = []
    for item in job_type:
        sub_codes = item.get("subCode")
        if not isinstance(sub_codes, list):
            raise ValueError("Meituan route has an invalid job type filter")
        job_type_payload.append({"code": item.get("code"), "subCode": list(sub_codes)})
    return {
        "page": {"pageNo": page, "pageSize": _PAGE_SIZE},
        "jobShareType": _query_first(query, "jobShareType") or "1",
        "keywords": _query_first(query, "keyword", "keywords") or "",
        "cityList": [],
        "department": [],
        "jfJgList": [],
        "jobType": job_type_payload,
        "typeCode": list(type_code),
        "specialCode": _query_values(query, "hiringSpecial"),
    }


def _list_page(
    url: str,
    route: str,
    request_json: JsonRequester,
    page: int,
) -> PublicPage:
    data = _data(
        request_json(
            f"{_origin(url)}{_LIST_PATH}",
            "POST",
            _list_payload(url, route, page),
        )
    )
    page_info = _mapping(data.get("page"), "Meituan API did not return page data")
    raw_items = data.get("list")
    if not isinstance(raw_items, list):
        raise ValueError("Meituan API did not return a position list")
    items = [_mapping(item, "Meituan API returned an invalid position") for item in raw_items]
    return PublicPage(
        total=non_negative_int(
            page_info.get("totalCount"), "Meituan API did not return a valid job count"
        ),
        items=items,
        page_count=non_negative_int(
            page_info.get("totalPage"), "Meituan API did not return a valid page count"
        ),
    )


def _list_jobs(
    url: str,
    route: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, route, request_json, page),
        source="Meituan",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS,
        job_id=lambda item: _text(item.get("jobUnionId")),
    )


def _description(item: Mapping[str, object]) -> str | None:
    structured = "\n".join(
        value for key in ("jobDuty", "jobRequirement") if (value := _text(item.get(key)))
    )
    return structured or _text(item.get("desc"))


def _recruitment_type(item: Mapping[str, object], route: str) -> str | None:
    if route == "social":
        return "社招"
    project_name = _text(item.get("projectName"))
    if project_name and any(
        marker in project_name for marker in ("校招", "校园", "应届", "北斗", "启航", "管培")
    ):
        return "校招"
    if project_name and "实习" in project_name:
        return "实习"
    if _text(item.get("jobSource")) in {"1", "2"}:
        return "实习"
    return "校招"


def _detail_url(source_url: str, source_job_id: str, route: str) -> str:
    share_type = _query_first(parse_qs(urlsplit(source_url).query), "jobShareType") or "1"
    highlight_type = "social" if route == "social" else "campus"
    query = urlencode(
        {
            "jobUnionId": source_job_id,
            "jobShareType": share_type,
            "highlightType": highlight_type,
        }
    )
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/web/position/detail", query, ""))


def _detail_if_needed(
    item: Mapping[str, object],
    source_url: str,
    request_json: JsonRequester,
) -> tuple[Mapping[str, object], str]:
    if _description(item):
        return item, "list_api"
    source_job_id = _text(item.get("jobUnionId"))
    if not source_job_id:
        raise ValueError("Meituan position has no jobUnionId")
    detail = _data(
        request_json(
            f"{_origin(source_url)}{_DETAIL_PATH}",
            "POST",
            {"jobUnionId": source_job_id},
        )
    )
    return detail, "public_api"


def _job(
    item: Mapping[str, object],
    source_url: str,
    route: str,
    request_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    detail, detail_status = _detail_if_needed(item, source_url, request_json)
    source_job_id = _text(detail.get("jobUnionId")) or _text(item.get("jobUnionId"))
    title = _text(detail.get("name")) or _text(item.get("name"))
    description = _description(detail)
    if not source_job_id or not title:
        raise ValueError("Meituan position has no jobUnionId or title")
    if not description:
        raise ValueError(f"Meituan position {source_job_id} has no public description")
    detail_url = _detail_url(source_url, source_job_id, route)
    source_ref = f"{_origin(source_url)}{_DETAIL_PATH}"
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("cityList") or item.get("cityList")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(detail, route),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("firstPostTime") or item.get("firstPostTime")),
        "deadline_at": _published_at(detail.get("expiredTime") or item.get("expiredTime")),
        "source_ref": source_ref,
        "metadata": {
            "parser": "meituan",
            "platform_family": "meituan-campus",
            "record_kind": "job",
            "detail_status": detail_status,
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "recruitment_route": route,
            "list_count": total,
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect public Meituan positions from a supported recruitment route."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, _request_json)
    query = parse_qs(urlsplit(url).query)
    direct_id = _query_first(query, "jobUnionId")
    route = _route(url)
    if direct_id:
        return [_job({"jobUnionId": direct_id}, url, route or "campus", requester, 1)]
    if route is None:
        raise ValueError("Meituan URL has no supported public recruitment route")
    items, total = _list_jobs(url, route, requester)
    return map_bounded(items, lambda item: _job(item, url, route, requester, total), max_workers)


__all__ = ["parse"]
