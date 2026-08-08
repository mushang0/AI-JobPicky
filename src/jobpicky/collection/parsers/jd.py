"""Evidence-first adapter for JD's public campus recruitment API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json
from .public_api_support import (
    PublicPage,
    bind_requester,
    collect_pages,
    map_bounded,
    mapping,
    non_negative_int,
    origin,
    published_at,
    text,
)

_PAGE_SIZE = 100
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/api/wx/position/page"
_INDEX_PATH = "/api/wx/position/index"
_DETAIL_PATH = "/api/wx/position/detail"
_SUPPORTED_TYPES = frozenset({"present", "internship"})


def _type(url: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    fragment_query = {}
    if "?" in parts.fragment:
        fragment_query = parse_qs(parts.fragment.split("?", 1)[1], keep_blank_values=True)
    value = text((query.get("type") or fragment_query.get("type") or [""])[0])
    return value if value in _SUPPORTED_TYPES else "present"


def _query_values(query: Mapping[str, list[str]], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        for raw in query.get(key, []):
            values.extend(item for item in raw.split(",") if item)
    return values


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    parameter: dict[str, object] = {
        "positionName": (
            text(query.get("positionName", [""])[0]) or text(query.get("keyword", [""])[0]) or ""
        ),
        "planIdList": _query_values(query, "planIdList", "planId"),
        "jobDirectionCodeList": _query_values(query, "jobDirectionCodeList", "jobDirectionCode"),
        "workCityCodeList": _query_values(query, "workCityCodeList", "workCityCode"),
        "positionDeptList": _query_values(query, "positionDeptList", "positionDept"),
    }
    return {
        "pageSize": _PAGE_SIZE,
        "pageIndex": page - 1,
        "parameter": parameter,
    }


def _data(response: object, message: str) -> Mapping[str, object]:
    root = mapping(response, "JD API response is not an object")
    if root.get("success") is not True:
        raise ValueError(f"JD API returned success={root.get('success')!r}")
    return mapping(root.get("body"), message)


def _source_job_id(item: Mapping[str, object]) -> str | None:
    return text(item.get("publishId")) or text(item.get("id"))


def _list_page(url: str, request_json: JsonRequester, page: int) -> PublicPage:
    body = _data(
        request_json(
            f"{origin(url)}{_LIST_PATH}?type={_type(url)}", "POST", _list_payload(url, page)
        ),
        "JD API did not return page data",
    )
    raw_items = body.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("JD API did not return a position list")
    total = non_negative_int(body.get("totalNumber"), "JD API did not return a valid job count")
    page_count = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    return PublicPage(
        total=total,
        page_count=page_count,
        items=[mapping(item, "JD API returned an invalid position") for item in raw_items],
    )


def _list_jobs(url: str, request_json: JsonRequester) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="JD",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=_source_job_id,
    )


def _description(item: Mapping[str, object]) -> str | None:
    return (
        "\n".join(
            value for key in ("workContent", "qualification") if (value := text(item.get(key)))
        )
        or None
    )


def _locations(item: Mapping[str, object]) -> list[str]:
    values: list[str] = []
    requirements = item.get("requirementVoList")
    if isinstance(requirements, list):
        for requirement in requirements:
            if not isinstance(requirement, Mapping):
                continue
            value = text(
                requirement.get("workCity")
                or requirement.get("workCityName")
                or requirement.get("cityName")
            )
            if value and value not in values:
                values.append(value)
    if values:
        return values
    fallback = text(item.get("workCity") or item.get("workCityName"))
    return [fallback] if fallback else []


def _recruitment_type(url: str, item: Mapping[str, object]) -> str:
    value = " ".join(
        part
        for part in (
            text(item.get("recruitType")),
            text(item.get("recruitTypeName")),
            text(item.get("positionType")),
        )
        if part
    )
    if "实习" in value or "intern" in value.casefold():
        return "实习"
    return "实习" if _type(url) == "internship" else "校招"


def _detail_id(url: str) -> str | None:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    fragment_query = {}
    if "?" in parts.fragment:
        fragment_query = parse_qs(parts.fragment.split("?", 1)[1], keep_blank_values=True)
    for values in (query.get("id", []), fragment_query.get("id", [])):
        if values and (value := text(values[0])):
            return value
    return None


def _detail_url(url: str, source_job_id: str) -> str:
    job_type = _type(url)
    return (
        f"{origin(url)}{_INDEX_PATH}?"
        f"{urlencode({'type': job_type})}#/details?"
        f"{urlencode({'type': job_type, 'id': source_job_id})}"
    )


def _detail_if_needed(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    *,
    force_detail: bool = False,
) -> tuple[Mapping[str, object], str]:
    source_job_id = _source_job_id(item)
    if not source_job_id:
        raise ValueError("JD position has no publishId")
    if not force_detail and _description(item):
        return item, "list_api"
    detail = _data(
        request_json(
            f"{origin(url)}{_DETAIL_PATH}/{quote(source_job_id, safe='')}",
            "POST",
            {},
        ),
        "JD detail API did not return a position",
    )
    return detail, "public_api"


def _job(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    total: int,
    *,
    force_detail: bool = False,
) -> dict[str, object]:
    detail, detail_status = _detail_if_needed(item, url, request_json, force_detail=force_detail)
    source_job_id = _source_job_id(detail) or _source_job_id(item)
    title = text(detail.get("positionName")) or text(item.get("positionName"))
    description = _description(detail) or _description(item)
    if not source_job_id or not title or not description:
        raise ValueError(f"JD position {source_job_id or '<unknown>'} has no title or description")
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail),
        "detail_url": _detail_url(url, source_job_id),
        "apply_url": _detail_url(url, source_job_id),
        "recruitment_type": _recruitment_type(url, detail),
        "education_requirement": text(detail.get("education")),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": published_at(detail.get("publishTime") or item.get("publishTime")),
        "deadline_at": published_at(detail.get("deadline") or item.get("deadline")),
        "source_ref": f"{origin(url)}{_DETAIL_PATH}/{quote(source_job_id, safe='')}",
        "metadata": {
            "parser": "jd",
            "platform_family": "jd-campus",
            "record_kind": "job",
            "detail_status": detail_status,
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "list_count": total,
            "job_direction": text(detail.get("jobDirection")),
            "job_category": text(detail.get("jobCategory")),
            "department": text(detail.get("positionDept")),
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect public JD graduate or internship positions."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, _request_json)
    direct_id = _detail_id(url)
    if direct_id is not None:
        return [_job({"publishId": direct_id}, url, requester, 1, force_detail=True)]
    items, total = _list_jobs(url, requester)
    return map_bounded(items, lambda item: _job(item, url, requester, total), max_workers)


__all__ = ["parse"]
