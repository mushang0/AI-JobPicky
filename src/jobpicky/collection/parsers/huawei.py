"""Evidence-first adapter for Huawei's public campus recruitment API."""

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
    locations as _split_locations,
)
from .public_api_support import (
    mapping as _mapping,
)
from .public_api_support import (
    published_at as _published_at,
)
from .public_api_support import (
    text as _text,
)

_BASE_PATH = "/reccampportal"
_PAGE_SIZE = 30
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/services/portal/portalpub/getJob/newHr/page"
_DETAIL_PATH = "/services/portal/portalpub/getJobDetail/newHr"


def _base_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, _BASE_PATH, "", ""))


def _list_payload(url: str) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    payload: dict[str, object] = {"language": _text(query.get("language", [""])[0]) or "zh_CN"}
    for key in (
        "jobType",
        "jobTypes",
        "jobFamClsCode",
        "cityCode",
        "searchText",
        "countryCode",
        "deptCode",
    ):
        if value := _text(query.get(key, [""])[0]):
            payload[key] = value
    return payload


def _list_page(url: str, request_json: JsonRequester, page: int) -> PublicPage:
    endpoint = f"{_base_url(url)}{_LIST_PATH}/{_PAGE_SIZE}/{page}"
    root = _mapping(
        request_json(endpoint, "GET", _list_payload(url)),
        "Huawei API response is not an object",
    )
    page_info = _mapping(root.get("pageVO"), "Huawei API did not return page data")
    raw_items = root.get("result")
    if not isinstance(raw_items, list):
        raise ValueError("Huawei API did not return a position list")
    total = non_negative_int(
        page_info.get("totalRows"), "Huawei API did not return a valid job count"
    )
    pages = non_negative_int(
        page_info.get("totalPages"), "Huawei API did not return a valid page count"
    )
    return PublicPage(
        total=total,
        page_count=max(1, pages),
        items=[_mapping(item, "Huawei API returned an invalid position") for item in raw_items],
    )


def _list_jobs(url: str, request_json: JsonRequester) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="Huawei",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=lambda item: _text(item.get("jobId")),
    )


def _locations(value: object) -> list[str]:
    raw_values = _split_locations(value)
    result: list[str] = []
    for raw in raw_values:
        normalized = raw.replace("\\", "/")
        if "/" in normalized:
            normalized = normalized.rsplit("/", 1)[-1]
        if "-" in normalized and raw.replace("\\", "/").startswith("China/"):
            normalized = normalized.rsplit("-", 1)[-1]
        if normalized in {"China", "中国"}:
            continue
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _description(item: Mapping[str, object]) -> str | None:
    return (
        "\n".join(
            value
            for key in ("mainBusiness", "jobRequire", "jobDesc")
            if (value := _text(item.get(key)))
        )
        or None
    )


def _recruitment_type(item: Mapping[str, object]) -> str:
    value = _text(item.get("jobType")) or _text(item.get("jobTypeName")) or ""
    if "实习" in value:
        return "实习"
    if "社会" in value or "社招" in value:
        return "社招"
    return "校招"


def _detail_parts(url: str) -> tuple[str, str] | None:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    job_id = _text(query.get("jobId", [""])[0])
    if not job_id:
        return None
    return job_id, _text(query.get("dataSource", [""])[0]) or "1"


def _job(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    total: int,
    *,
    force_detail: bool = False,
) -> dict[str, object]:
    source_job_id = _text(item.get("jobId"))
    if not source_job_id:
        raise ValueError("Huawei position has no jobId")
    detail = item
    detail_status = "list_api"
    data_source = _text(item.get("dataSource")) or "1"
    if force_detail or not _description(item):
        detail = _mapping(
            request_json(
                f"{_base_url(url)}{_DETAIL_PATH}",
                "GET",
                {"jobId": source_job_id, "dataSource": data_source},
            ),
            "Huawei detail API did not return a position",
        )
        detail_status = "public_api"
    title = _text(detail.get("jobname")) or _text(detail.get("nameCn"))
    description = _description(detail)
    if not title or not description:
        raise ValueError(f"Huawei position {source_job_id} has no title or description")
    detail_url = urlunsplit(
        (
            urlsplit(url).scheme,
            urlsplit(url).netloc,
            f"{_BASE_PATH}/portal5/campus-recruitment-detail.html",
            urlencode({"jobId": source_job_id, "dataSource": data_source}),
            "",
        )
    )
    detail_endpoint = f"{_base_url(url)}{_DETAIL_PATH}"
    source_ref = (
        f"{detail_endpoint}?{urlencode({'jobId': source_job_id, 'dataSource': data_source})}"
    )
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("jobAddress") or detail.get("jobArea")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(detail),
        "education_requirement": _text(detail.get("degree")),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "graduation_years": [],
        "published_at": _published_at(detail.get("releaseDate") or detail.get("creationDate")),
        "deadline_at": _published_at(detail.get("expirationDate") or detail.get("endDate")),
        "source_ref": source_ref,
        "metadata": {
            "parser": "huawei",
            "platform_family": "huawei-careers",
            "record_kind": "job",
            "detail_status": detail_status,
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "list_count": total,
            "data_source": data_source,
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect public Huawei campus positions without login."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, _request_json)
    direct = _detail_parts(url)
    if direct is not None:
        source_job_id, data_source = direct
        return [
            _job(
                {"jobId": source_job_id, "dataSource": data_source},
                url,
                requester,
                1,
                force_detail=True,
            )
        ]
    items, total = _list_jobs(url, requester)
    return map_bounded(
        items,
        lambda item: _job(item, url, requester, total),
        max_workers,
    )


__all__ = ["parse"]
