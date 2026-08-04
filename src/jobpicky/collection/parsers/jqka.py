"""Evidence-first adapter for the public Tonghuashun campus API."""

from __future__ import annotations

import html
import math
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json

_PAGE_SIZE = 50
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/api/v3/school_recruitment/apply/apply_list"
_DETAIL_PATH = "/api/v3/school_recruitment/apply/apply_detail"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "\n", str(value)))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text).strip()
    return text or None


def _locations(value: object) -> list[str]:
    text = _text(value) or ""
    return [item for item in re.split(r"[,，、/|;；\s]+", text) if item]


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Tonghuashun API response is not an object")
    return value


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response)
    if str(root.get("erro_code")) != "0":
        raise ValueError(f"Tonghuashun API returned error {root.get('erro_code')!r}")
    data = _mapping(root.get("ex_data"))
    if data.get("success") is False:
        raise ValueError("Tonghuashun API returned an unsuccessful response")
    return data


def _positive_int(value: object, field: str) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Tonghuashun API did not return a valid {field}") from exc
    if result < 0:
        raise ValueError(f"Tonghuashun API returned a negative {field}")
    return result


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    origin = _origin(url)
    total: int | None = None
    items: list[Mapping[str, object]] = []
    page = 1
    max_pages = math.ceil(_MAX_JOBS / _PAGE_SIZE)
    while page <= max_pages:
        payload = {"page": page, "pageCount": _PAGE_SIZE}
        data = _data(request_json(f"{origin}{_LIST_PATH}", "GET", payload))
        if total is None:
            total = _positive_int(data.get("total"), "job count")
            if total > _MAX_JOBS:
                raise ValueError(f"Tonghuashun API returned {total} jobs, above the safe limit")
        page_items = data.get("apply_show_do_list")
        if not isinstance(page_items, list):
            raise ValueError("Tonghuashun API did not return apply_show_do_list")
        mapped_items = [_mapping(item) for item in page_items if isinstance(item, Mapping)]
        if not mapped_items and len(items) < total:
            raise ValueError("Tonghuashun API returned an incomplete page")
        items.extend(mapped_items)
        if len(items) >= total:
            return items[:total], total
        page += 1
    raise ValueError("Tonghuashun API pagination exceeded the safe page limit")


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
    requester = request_json or (
        lambda endpoint, method, payload: _request_json(endpoint, url, method, payload)
    )
    items, total = _list_jobs(url, requester)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items) or 1)) as executor:
        jobs = list(executor.map(lambda item: _detail(item, url, requester, total), items))
    return jobs


__all__ = ["parse"]
