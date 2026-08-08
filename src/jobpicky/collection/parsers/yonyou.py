"""Evidence-first adapter for Yonyou's public campus recruitment API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .public_api import JsonRequester, request_form_json
from .public_api_support import (
    PublicPage,
    bind_requester,
    collect_pages,
    locations,
    map_bounded,
    mapping,
    non_negative_int,
    origin,
    published_at,
    text,
)

_PAGE_SIZE = 12
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_ROUTE = "/wecruit/positionInfo/listPosition"
_DETAIL_ROUTE = "/wecruit/positionInfo/listPositionDetail"
_REQUEST_QUERY = urlencode({"iSaJAx": "isAjax", "request_locale": "zh_CN"})


def _suite_id(url: str) -> str:
    first_segment = next((segment for segment in urlsplit(url).path.split("/") if segment), "")
    if not first_segment.startswith("SU"):
        raise ValueError("Yonyou source URL has no public suite id")
    return first_segment


def _endpoint(url: str, route: str) -> str:
    return f"{origin(url)}{route}/{_suite_id(url)}?{_REQUEST_QUERY}"


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    payload: dict[str, object] = {
        "isFrompb": True,
        "recruitType": 1,
        "pageSize": _PAGE_SIZE,
        "currentPage": page,
    }
    for key in (
        "projectCode",
        "workPlaceCode",
        "postTypeCode",
        "orgCode",
        "siteCode",
        "salaryCode",
        "educationCode",
        "publishDateType",
        "recruitmentType",
        "jobLevel",
        "externalSuiteKeys",
    ):
        if value := text((query.get(key) or [""])[0]):
            payload[key] = value
    return payload


def _data(response: object, message: str) -> Mapping[str, object]:
    root = mapping(response, "Yonyou API response is not an object")
    if str(root.get("state")) != "200":
        raise ValueError(f"Yonyou API returned state={root.get('state')!r}")
    return mapping(root.get("data"), message)


def _source_job_id(item: Mapping[str, object]) -> str | None:
    return text(item.get("postId"))


def _list_page(url: str, request_json: JsonRequester, page: int) -> PublicPage:
    data = _data(
        request_json(_endpoint(url, _LIST_ROUTE), "POST", _list_payload(url, page)),
        "Yonyou API did not return page data",
    )
    page_form = mapping(data.get("pageForm"), "Yonyou API did not return page data")
    raw_items = page_form.get("pageData")
    if not isinstance(raw_items, list):
        raise ValueError("Yonyou API did not return a position list")
    total = non_negative_int(
        page_form.get("dataCount"), "Yonyou API did not return a valid job count"
    )
    page_count = non_negative_int(
        page_form.get("totalPage"), "Yonyou API did not return a valid page count"
    )
    return PublicPage(
        total=total,
        page_count=max(1, page_count),
        items=[mapping(item, "Yonyou API returned an invalid position") for item in raw_items],
    )


def _list_jobs(url: str, request_json: JsonRequester) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="Yonyou",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=_source_job_id,
    )


def _description(item: Mapping[str, object]) -> str | None:
    return (
        "\n".join(
            value for key in ("workContent", "serviceCondition") if (value := text(item.get(key)))
        )
        or None
    )


def _detail_id(url: str) -> str | None:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return text((query.get("postId") or [""])[0])


def _detail_url(url: str, source_job_id: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            f"/{_suite_id(url)}/pb/posDetail.html",
            urlencode({"postId": source_job_id, "postType": "campus"}),
            "",
        )
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
        raise ValueError("Yonyou position has no postId")
    if not force_detail and _description(item):
        return item, "list_api"
    detail = _data(
        request_json(
            _endpoint(url, _DETAIL_ROUTE),
            "POST",
            {"postId": source_job_id},
        ),
        "Yonyou detail API did not return a position",
    )
    return detail, "public_api"


def _recruitment_type(item: Mapping[str, object]) -> str:
    value = " ".join(
        part
        for key in ("recruitType", "recruitTypeName", "postType", "postTypeName")
        if (part := text(item.get(key)))
    )
    if "实习" in value or "intern" in value.casefold():
        return "实习"
    return "校招"


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
    title = text(detail.get("postName")) or text(item.get("postName"))
    description = _description(detail) or _description(item)
    if not source_job_id or not title or not description:
        raise ValueError(
            f"Yonyou position {source_job_id or '<unknown>'} has no title or description"
        )
    detail_endpoint = _endpoint(url, _DETAIL_ROUTE)
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": locations(detail.get("workPlaceList") or detail.get("workPlaceStr")),
        "detail_url": _detail_url(url, source_job_id),
        "apply_url": _detail_url(url, source_job_id),
        "recruitment_type": _recruitment_type(detail),
        "education_requirement": text(detail.get("education") or detail.get("educationStr")),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": published_at(detail.get("publishDate") or item.get("publishDate")),
        "deadline_at": published_at(detail.get("endDate") or item.get("endDate")),
        "source_ref": f"{detail_endpoint}&{urlencode({'postId': source_job_id})}",
        "metadata": {
            "parser": "yonyou",
            "platform_family": "yonyou-careers",
            "record_kind": "job",
            "detail_status": detail_status,
            "api_route": _LIST_ROUTE,
            "detail_api_route": _DETAIL_ROUTE,
            "list_count": total,
            "suite_id": _suite_id(url),
            "department": text(detail.get("department")),
            "project": text(detail.get("projectName")),
            "major_requirement": text(detail.get("subject")),
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect public Yonyou campus positions without login."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, request_form_json)
    direct_id = _detail_id(url)
    if direct_id is not None:
        return [_job({"postId": direct_id}, url, requester, 1, force_detail=True)]
    items, total = _list_jobs(url, requester)
    return map_bounded(items, lambda item: _job(item, url, requester, total), max_workers)


__all__ = ["parse"]
