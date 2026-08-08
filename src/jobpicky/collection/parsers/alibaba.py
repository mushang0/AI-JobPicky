"""Evidence-first adapter for the public Alibaba campus recruitment API."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from http.cookiejar import CookieJar
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .public_api import JsonRequester
from .public_api_support import (
    PublicPage,
    collect_pages,
    map_bounded,
    non_negative_int,
)
from .public_api_support import locations as _locations
from .public_api_support import mapping as _mapping
from .public_api_support import origin as _origin
from .public_api_support import published_at as _published_at
from .public_api_support import text as _text

_PAGE_SIZE = 100
_MAX_JOBS = 500
_MAX_WORKERS = 8
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TIMEOUT_SECONDS = 20
_LIST_PATH = "/position/search"
_DETAIL_PATH = "/position/detail"
_FILTER_ALIASES = {
    "aliStar": "aliStar",
    "workCity": "regions",
    "customDept": "customDeptCode",
    "category": "subCategories",
}


def _content(response: object) -> Mapping[str, object]:
    root = _mapping(response, "Alibaba API response is not an object")
    if str(root.get("success")).lower() != "true":
        raise ValueError(f"Alibaba API returned failure {root.get('errorMsg')!r}")
    return _mapping(root.get("content"), "Alibaba API did not return content")


def _batch_id(url: str) -> int:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    value = _text(query.get("batchId", [""])[0])
    if value and value.startswith("aliStar"):
        value = value.removeprefix("aliStar")
    if not value or not value.isdigit():
        raise ValueError("Alibaba recruitment URL has no numeric batch id")
    return int(value)


def _filter_params(url: str) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    raw = _text(query.get("filterParams", [""])[0])
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Alibaba recruitment URL has invalid filterParams") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Alibaba recruitment URL filterParams is not an object")
    return parsed


def _filter_value(value: object) -> str | list[str] | None:
    if isinstance(value, list):
        values = [item for child in value if (item := _text(child))]
        if not values:
            return None
        return values[0] if len(values) == 1 else values
    return _text(value)


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    filters = _filter_params(url)
    payload: dict[str, object] = {
        "batchId": _batch_id(url),
        "pageIndex": page,
        "pageSize": _PAGE_SIZE,
        "channel": "new_campus_group_official_site",
        "language": "zh",
    }
    if search_key := _text(query.get("search", [""])[0]) or _text(query.get("searchKey", [""])[0]):
        payload["searchKey"] = search_key
    if circle_code := _text(query.get("circleCode", [""])[0]):
        payload["referralCircleCode"] = circle_code
        payload["circleCodes"] = [circle_code]
    for key, api_key in _FILTER_ALIASES.items():
        value = _filter_value(filters.get(key))
        if value is None:
            continue
        if isinstance(value, list):
            payload[api_key] = ",".join(value) if api_key != "aliStar" else value
        else:
            payload[api_key] = value
    return payload


def _list_page(
    url: str,
    request_json: JsonRequester,
    page: int,
) -> PublicPage:
    content = _content(
        request_json(f"{_origin(url)}{_LIST_PATH}", "POST", _list_payload(url, page))
    )
    raw_items = content.get("datas")
    if not isinstance(raw_items, list):
        raise ValueError("Alibaba API did not return a position list")
    return PublicPage(
        total=non_negative_int(
            content.get("totalCount"), "Alibaba API did not return a valid job count"
        ),
        items=[_mapping(item, "Alibaba API returned an invalid position") for item in raw_items],
    )


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="Alibaba",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=lambda item: _text(item.get("id")),
    )


def _recruitment_type(*values: str) -> str | None:
    text = " ".join(values)
    if "实习" in text or "intern" in text.casefold():
        return "实习"
    if "社招" in text or "社会" in text or "social" in text.casefold():
        return "社招"
    if any(marker in text for marker in ("校招", "校园", "应届", "freshman", "campus")):
        return "校招"
    return None


def _detail_parts(url: str) -> str | None:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if position_id := _text(query.get("positionId", [""])[0]):
        return position_id
    path_parts = [unquote(part) for part in parts.path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[-2] == "position":
        return _text(path_parts[-1])
    return None


def _detail_if_needed(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
) -> Mapping[str, object]:
    description = "\n".join(
        value for value in (_text(item.get("description")), _text(item.get("requirement"))) if value
    )
    if description:
        return item
    source_job_id = _text(item.get("id"))
    if not source_job_id:
        raise ValueError("Alibaba position has no id")
    return _content(
        request_json(
            f"{_origin(url)}{_DETAIL_PATH}",
            "POST",
            {
                "id": int(source_job_id) if source_job_id.isdigit() else source_job_id,
                "channel": "new_campus_group_official_site",
                "language": "zh",
            },
        )
    )


def _job(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    detail = _detail_if_needed(item, url, request_json)
    source_job_id = _text(detail.get("id")) or _text(item.get("id"))
    title = _text(detail.get("name")) or _text(item.get("name"))
    if not source_job_id or not title:
        raise ValueError("Alibaba position has no id or title")
    description = "\n".join(
        value
        for value in (_text(detail.get("description")), _text(detail.get("requirement")))
        if value
    )
    if not description:
        raise ValueError(f"Alibaba position {source_job_id} has no public description")
    detail_url = urlunsplit(
        (
            urlsplit(url).scheme,
            urlsplit(url).netloc,
            f"/campus/position/{quote(source_job_id)}",
            "",
            "",
        )
    )
    category = _text(detail.get("categoryType")) or _text(item.get("categoryType")) or ""
    batch_name = _text(detail.get("batchName")) or _text(item.get("batchName")) or ""
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("workLocations") or item.get("workLocations")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(category, batch_name),
        "education_requirement": _text(detail.get("degree")),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("publishTime") or detail.get("modifyTime")),
        "deadline_at": None,
        "source_ref": f"{_origin(url)}{_DETAIL_PATH}",
        "metadata": {
            "parser": "alibaba",
            "platform_family": "alibaba-campus",
            "record_kind": "job",
            "detail_status": "list_api" if detail is item else "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "batch_id": _batch_id(url) if "batchId" in urlsplit(url).query else None,
            "category_type": category,
            "list_count": total,
        },
    }


class _AlibabaClient:
    """Bootstrap a public CSRF token and cookie without persisting session state."""

    def __init__(self, source_url: str) -> None:
        self.source_url = source_url
        self.origin = _origin(source_url)
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        request = Request(
            source_url,
            headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"},
        )
        with self.opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("Alibaba recruitment page exceeds the safe response limit")
        shell = raw.decode("utf-8", "replace")
        match = re.search(r"__token__\s*:\s*\"([^\"]+)\"", shell)
        if match is None:
            raise ValueError("Alibaba recruitment page has no public bootstrap token")
        self.token = match.group(1)

    def request(self, endpoint: str, method: str, payload: Mapping[str, object] | None) -> object:
        request_url = f"{endpoint}?{urlencode({'_csrf': self.token})}"
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        )
        request = Request(
            request_url,
            data=body,
            method=method.upper(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json" if body is not None else "",
                "Origin": self.origin,
                "Referer": self.source_url,
                "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
            },
        )
        with self.opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("Alibaba recruitment API response exceeds the safe response limit")
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ValueError("Alibaba recruitment API did not return JSON") from exc


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect all public Alibaba positions for a batch page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    client = _AlibabaClient(url) if request_json is None else None
    if request_json is not None:
        requester = request_json
    else:
        assert client is not None
        requester = client.request
    direct_id = _detail_parts(url)
    if direct_id is not None:
        return [_job({"id": direct_id}, url, requester, 1)]
    items, total = _list_jobs(url, requester)
    return map_bounded(items, lambda item: _job(item, url, requester, total), max_workers)


__all__ = ["parse"]
