"""Evidence-first adapter for the public PDD campus recruitment API."""

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

_PAGE_SIZE = 10
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/api/careers/api/recruit/position/list"
_DETAIL_PATH = "/api/careers/api/recruit/position/detail"


def _result(response: object) -> Mapping[str, object]:
    root = _mapping(response, "PDD API response is not an object")
    if str(root.get("success")).lower() != "true":
        raise ValueError(f"PDD API returned failure {root.get('errorCode')!r}")
    return _mapping(root.get("result"), "PDD API did not return result")


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


def _list_page(
    url: str,
    request_json: JsonRequester,
    page: int,
) -> PublicPage:
    result = _result(
        request_json(
            f"{_origin(url)}{_LIST_PATH}",
            "POST",
            _list_payload(url, page),
        )
    )
    raw_items = result.get("list")
    if not isinstance(raw_items, list):
        raise ValueError("PDD API did not return a position list")
    return PublicPage(
        total=non_negative_int(result.get("total"), "PDD API did not return a valid job count"),
        items=[_mapping(item, "PDD API returned an invalid position") for item in raw_items],
    )


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="PDD",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=lambda item: _text(item.get("id")),
    )


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
    requester = bind_requester(url, request_json, _request_json)
    direct_ids = parse_qs(urlsplit(url).query).get("positionId", [])
    if direct_ids and direct_ids[0].strip():
        return [_detail({"id": direct_ids[0]}, url, requester, 1)]
    items, total = _list_jobs(url, requester)
    return map_bounded(items, lambda item: _detail(item, url, requester, total), max_workers)


__all__ = ["parse"]
