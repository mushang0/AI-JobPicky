"""Evidence-first adapter for the public Tonghuashun campus API."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote, urlsplit, urlunsplit

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
from .public_api_support import text as _text

_PAGE_SIZE = 50
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/api/v3/school_recruitment/apply/apply_list"
_DETAIL_PATH = "/api/v3/school_recruitment/apply/apply_detail"


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response, "Tonghuashun API response is not an object")
    if str(root.get("erro_code")) != "0":
        raise ValueError(f"Tonghuashun API returned error {root.get('erro_code')!r}")
    data = _mapping(root.get("ex_data"), "Tonghuashun API did not return ex_data")
    if data.get("success") is False:
        raise ValueError("Tonghuashun API returned an unsuccessful response")
    return data


def _list_page(
    url: str,
    request_json: JsonRequester,
    page: int,
) -> PublicPage:
    data = _data(
        request_json(
            f"{_origin(url)}{_LIST_PATH}",
            "GET",
            {"page": page, "pageCount": _PAGE_SIZE},
        )
    )
    raw_items = data.get("apply_show_do_list")
    if not isinstance(raw_items, list):
        raise ValueError("Tonghuashun API did not return apply_show_do_list")
    raw_page_count = data.get("pages")
    return PublicPage(
        total=non_negative_int(
            data.get("total"), "Tonghuashun API did not return a valid job count"
        ),
        page_count=(
            non_negative_int(raw_page_count, "Tonghuashun API did not return a valid page count")
            if raw_page_count is not None
            else None
        ),
        items=[
            _mapping(item, "Tonghuashun API returned an invalid position") for item in raw_items
        ],
    )


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="Tonghuashun",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=lambda item: _text(item.get("id")),
    )


def _recruitment_type(series_name: str | None, type_name: str | None) -> str | None:
    value = " ".join(item for item in (series_name, type_name) if item)
    if "实习" in value:
        return "实习"
    if any(marker in value for marker in ("校招", "校园", "应届")):
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
        raise ValueError("Tonghuashun position has no id")
    origin = _origin(url)
    detail_endpoint = f"{origin}{_DETAIL_PATH}?id={quote(source_job_id)}"
    detail = _data(request_json(detail_endpoint, "GET", None))
    title = _text(detail.get("name")) or _text(item.get("name"))
    if not title:
        raise ValueError(f"Tonghuashun position {source_job_id} has no title")
    description = "\n".join(
        value
        for value in (
            _text(detail.get("intro")),
            _text(detail.get("requirement")),
        )
        if value
    )
    if not description:
        raise ValueError(f"Tonghuashun position {source_job_id} has no public description")
    source_parts = urlsplit(url)
    detail_path = (
        "/mobile/job/detail" if source_parts.path.startswith("/mobile/") else "/job/detail"
    )
    detail_url = urlunsplit(
        (source_parts.scheme, source_parts.netloc, detail_path, f"id={source_job_id}", "")
    )
    series_name = _text(detail.get("apply_recruitment_series_name"))
    type_name = _text(detail.get("apply_type_first"))
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("base")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(series_name, type_name),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": None,
        "deadline_at": None,
        "source_ref": detail_endpoint,
        "metadata": {
            "parser": "jqka",
            "platform_family": "10jqka-campus",
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
    """Collect all public Tonghuashun positions for a recruitment page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = bind_requester(url, request_json, _request_json)
    items, total = _list_jobs(url, requester)
    return map_bounded(items, lambda item: _detail(item, url, requester, total), max_workers)


__all__ = ["parse"]
