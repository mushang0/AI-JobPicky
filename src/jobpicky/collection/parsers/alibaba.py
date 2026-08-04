"""Evidence-first adapter for the public Alibaba campus recruitment API."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .public_api import JsonRequester

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
    if isinstance(value, list):
        return [item for child in value if (item := _text(child))]
    return [item for item in re.split(r"[,，、/|;；\s]+", _text(value) or "") if item]


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def _content(response: object) -> Mapping[str, object]:
    root = _mapping(response, "Alibaba API response is not an object")
    if str(root.get("success")).lower() != "true":
        raise ValueError(f"Alibaba API returned failure {root.get('errorMsg')!r}")
    return _mapping(root.get("content"), "Alibaba API did not return content")


def _count(value: object) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Alibaba API did not return a valid job count") from exc
    if result < 0:
        raise ValueError("Alibaba API returned a negative job count")
    return result


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


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    total: int | None = None
    items: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    page = 1
    while page <= _MAX_JOBS // _PAGE_SIZE + 1:
        content = _content(
            request_json(f"{_origin(url)}{_LIST_PATH}", "POST", _list_payload(url, page))
        )
        if total is None:
            total = _count(content.get("totalCount"))
            if total > _MAX_JOBS:
                raise ValueError(f"Alibaba API returned {total} jobs, above the safe limit")
            if total == 0:
                return [], 0
        raw_items = content.get("datas")
        if raw_items is None and total == 0:
            return [], 0
        if not isinstance(raw_items, list):
            raise ValueError("Alibaba API did not return a position list")
        mapped_items = [
            _mapping(item, "Alibaba API returned an invalid position") for item in raw_items
        ]
        new_items = 0
        for item in mapped_items:
            source_job_id = _text(item.get("id"))
            if source_job_id and source_job_id not in seen_ids:
                seen_ids.add(source_job_id)
                items.append(item)
                new_items += 1
        if not mapped_items or new_items == 0:
            raise ValueError("Alibaba API returned an incomplete or repeated page")
        if len(items) >= total:
            return items[:total], total
        page += 1
    raise ValueError("Alibaba API pagination exceeded the safe page limit")


def _published_at(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        if text.isdigit():
            timestamp = float(text)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=UTC)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None


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
    requester = request_json or client.request  # type: ignore[union-attr]
    direct_id = _detail_parts(url)
    if direct_id is not None:
        return [_job({"id": direct_id}, url, requester, 1)]
    items, total = _list_jobs(url, requester)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items) or 1)) as executor:
        return list(executor.map(lambda item: _job(item, url, requester, total), items))


__all__ = ["parse"]
