"""Evidence-first adapter for Xiaohongshu's public campus API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json
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

_PAGE_SIZE = 100
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/websiterecruit/position/pageQueryPosition"
_DETAIL_PATH = "/websiterecruit/position/queryPositionDetail"
_RECRUIT_TYPES = frozenset({"campus", "intern"})


def _recruit_type(url: str) -> str:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    raw_values = query.get("recruitType") or query.get("campusRecruitTypes") or []
    raw = text(raw_values[0]) if raw_values else None
    if not raw:
        return "campus"
    normalized = raw.casefold()
    if normalized in {"intern", "internship", "term_intern"}:
        return "intern"
    if normalized in {"campus", "school", "school_recruit", "term_campus"}:
        return "campus"
    if normalized in {"social", "club_recruit", "term_social"}:
        raise ValueError("Xiaohongshu social recruitment is outside the campus parser")
    return "campus"


def _filter_value(query: Mapping[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        if values := query.get(key):
            return text(values[0])
    return None


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    payload: dict[str, object] = {
        "label": _filter_value(query, "label") or "all",
        "pageNum": page,
        "pageSize": _PAGE_SIZE,
        "recruitType": _recruit_type(url),
    }
    for output_key, query_keys in (
        ("themeCode", ("themeCode",)),
        ("positionName", ("positionName", "keyword", "keywords")),
        ("jobType", ("jobType", "jobTypes")),
        ("workplaceIds", ("workplaceIds", "workplace")),
        ("jobProjectId", ("jobProjectId", "jobProject")),
    ):
        if value := _filter_value(query, *query_keys):
            payload[output_key] = value
    return payload


def _root_data(response: object, message: str) -> Mapping[str, object]:
    root = mapping(response, "Xiaohongshu API response is not an object")
    if root.get("success") is not True:
        raise ValueError(f"Xiaohongshu API returned success={root.get('success')!r}")
    return mapping(root.get("data"), message)


def _source_job_id(item: Mapping[str, object]) -> str | None:
    return text(item.get("positionId"))


def _list_page(url: str, request_json: JsonRequester, page: int) -> PublicPage:
    data = _root_data(
        request_json(f"{origin(url)}{_LIST_PATH}", "POST", _list_payload(url, page)),
        "Xiaohongshu API did not return page data",
    )
    raw_items = data.get("list")
    if not isinstance(raw_items, list):
        raise ValueError("Xiaohongshu API did not return a position list")
    total = non_negative_int(data.get("total"), "Xiaohongshu API did not return a valid job count")
    page_count = non_negative_int(
        data.get("totalPage"), "Xiaohongshu API did not return a valid page count"
    )
    return PublicPage(
        total=total,
        page_count=max(1, page_count),
        items=[mapping(item, "Xiaohongshu API returned an invalid position") for item in raw_items],
    )


def _list_jobs(url: str, request_json: JsonRequester) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="Xiaohongshu",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=_source_job_id,
    )


def _description(item: Mapping[str, object]) -> str | None:
    return (
        "\n".join(value for key in ("duty", "qualification") if (value := text(item.get(key))))
        or None
    )


def _detail_url(url: str, source_job_id: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/campus/position/{source_job_id}", "", ""))


def _detail_id(url: str) -> str | None:
    path_parts = [part for part in urlsplit(url).path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[-2] == "position" and path_parts[-1].isdigit():
        return path_parts[-1]
    return None


def _detail_if_needed(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    *,
    force_detail: bool = False,
) -> tuple[Mapping[str, object], str]:
    source_job_id = _source_job_id(item)
    if not source_job_id:
        raise ValueError("Xiaohongshu position has no positionId")
    if not force_detail and _description(item):
        return item, "list_api"
    detail = _root_data(
        request_json(
            f"{origin(url)}{_DETAIL_PATH}",
            "GET",
            {"positionId": source_job_id},
        ),
        "Xiaohongshu detail API did not return a position",
    )
    return detail, "public_api"


def _recruitment_type(item: Mapping[str, object], url: str) -> str:
    value = " ".join(
        part
        for key in ("recruitType", "recruitTypeName", "positionType")
        if (part := text(item.get(key)))
    )
    if "实习" in value or "intern" in value.casefold() or _recruit_type(url) == "intern":
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
    title = text(detail.get("positionName")) or text(item.get("positionName"))
    description = _description(detail) or _description(item)
    if not source_job_id or not title or not description:
        raise ValueError(
            f"Xiaohongshu position {source_job_id or '<unknown>'} has no title or description"
        )
    recruit_type = _recruitment_type(detail, url)
    detail_endpoint = f"{origin(url)}{_DETAIL_PATH}"
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": locations(detail.get("workplace") or item.get("workplace")),
        "detail_url": _detail_url(url, source_job_id),
        "apply_url": _detail_url(url, source_job_id),
        "recruitment_type": recruit_type,
        "education_requirement": text(detail.get("education")),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": published_at(detail.get("publishTime") or item.get("publishTime")),
        "deadline_at": None,
        "source_ref": f"{detail_endpoint}?{urlencode({'positionId': source_job_id})}",
        "metadata": {
            "parser": "xiaohongshu",
            "platform_family": "xiaohongshu-careers",
            "record_kind": "job",
            "detail_status": detail_status,
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "list_count": total,
            "recruit_type": recruit_type,
            "job_type": text(detail.get("jobType") or item.get("jobType")),
            "job_project": text(detail.get("jobProjectName") or item.get("jobProjectName")),
            "recruit_status": text(detail.get("recruitStatus") or item.get("recruitStatus")),
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect public Xiaohongshu campus or internship positions."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, _request_json)
    direct_id = _detail_id(url)
    if direct_id is not None:
        return [_job({"positionId": direct_id}, url, requester, 1, force_detail=True)]
    items, total = _list_jobs(url, requester)
    return map_bounded(items, lambda item: _job(item, url, requester, total), max_workers)


__all__ = ["parse"]
