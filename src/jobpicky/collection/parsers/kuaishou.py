"""Evidence-first adapter for the public Kuaishou campus recruitment API."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json

_PAGE_SIZE = 100
_MAX_JOBS = 500
_MAX_WORKERS = 8
_DEFAULT_SUB_PROJECT = "20271779425607"
_LIST_PATH = "/recruit/campus/e/api/v1/open/positions/simple"
_DETAIL_PATH = "/recruit/campus/e/api/v1/open/positions/find"


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


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def _result(response: object) -> Mapping[str, object]:
    root = _mapping(response, "Kuaishou API response is not an object")
    if str(root.get("code")) != "0":
        raise ValueError(f"Kuaishou API returned code {root.get('code')!r}")
    return _mapping(root.get("result"), "Kuaishou API did not return result")


def _count(value: object, field: str) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Kuaishou API did not return a valid {field}") from exc
    if result < 0:
        raise ValueError(f"Kuaishou API returned a negative {field}")
    return result


def _route_and_query(url: str) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    route = parts.path
    fragment_path, separator, fragment_query = parts.fragment.partition("?")
    if fragment_path:
        route = fragment_path
    if separator:
        query.update(parse_qs(fragment_query, keep_blank_values=True))
    return route, query


def _query_values(query: Mapping[str, list[str]], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        for raw in query.get(key, []):
            values.extend(item for item in raw.split(",") if item)
    return values


def _sub_project_codes(url: str) -> list[str]:
    _, query = _route_and_query(url)
    values = _query_values(query, "recruitSubProjectCodes", "recruitSubProjectCodes[]")
    return values or [_DEFAULT_SUB_PROJECT]


def _first_query_value(query: Mapping[str, list[str]], *keys: str) -> str | None:
    values = _query_values(query, *keys)
    return _text(values[0]) if values else None


def _list_payload(url: str, page: int) -> dict[str, object]:
    _, query = _route_and_query(url)
    payload: dict[str, object] = {
        "recruitSubProjectCodes": _sub_project_codes(url),
        "pageSize": _PAGE_SIZE,
        "pageNum": page,
    }
    for field, keys in (
        ("positionLabel", ("positionLabel",)),
        ("name", ("name", "keyword")),
    ):
        if value := _first_query_value(query, *keys):
            payload[field] = value
    for field in ("positionCategoryCodes", "workLocationCodes"):
        if values := _query_values(query, field, f"{field}[]"):
            payload[field] = values
    return payload


def _source_job_id(item: Mapping[str, object]) -> str | None:
    return _text(item.get("id")) or _text(item.get("positionId"))


def _list_jobs(
    url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    total: int | None = None
    reported_pages: int | None = None
    items: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    page = 1
    max_pages = _MAX_JOBS // _PAGE_SIZE + 1
    while page <= max_pages:
        result = _result(
            request_json(f"{_origin(url)}{_LIST_PATH}", "POST", _list_payload(url, page))
        )
        if total is None:
            total = _count(result.get("total"), "job count")
            if total > _MAX_JOBS:
                raise ValueError(f"Kuaishou API returned {total} jobs, above the safe limit")
            raw_pages = result.get("pages")
            if raw_pages is not None:
                reported_pages = _count(raw_pages, "page count")
            if total == 0:
                return [], 0
        raw_items = result.get("list")
        if not isinstance(raw_items, list):
            raise ValueError("Kuaishou API did not return a position list")
        mapped_items = [
            _mapping(item, "Kuaishou API returned an invalid position") for item in raw_items
        ]
        new_items = 0
        for item in mapped_items:
            source_job_id = _source_job_id(item)
            if not source_job_id:
                raise ValueError("Kuaishou API returned a position without an id")
            if source_job_id not in seen_ids:
                seen_ids.add(source_job_id)
                items.append(item)
                new_items += 1
        if len(items) >= total:
            return items[:total], total
        if not mapped_items or new_items == 0:
            raise ValueError("Kuaishou API returned an incomplete or repeated page")
        if reported_pages is not None and page >= reported_pages:
            raise ValueError(f"Kuaishou API returned {len(items)} of {total} jobs")
        page += 1
    raise ValueError("Kuaishou API pagination exceeded the safe page limit")


def _locations(value: object) -> list[str]:
    if isinstance(value, list):
        locations: list[str] = []
        for child in value:
            if isinstance(child, Mapping):
                location = _text(child.get("name") or child.get("label"))
            else:
                location = _text(child)
            if location:
                locations.append(location)
        return locations
    return [item for item in re.split(r"[,，、/|;；\s]+", _text(value) or "") if item]


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


def _recruitment_type(*values: object) -> str | None:
    text = " ".join(value for value in (_text(item) for item in values) if value)
    folded = text.casefold()
    if "实习" in text or "intern" in folded:
        return "实习"
    if "社招" in text or "社会" in text or "social" in folded:
        return "社招"
    if "fulltime" in folded or any(marker in text for marker in ("校招", "校园", "应届")):
        return "校招"
    return None


def _detail_id(url: str) -> str | None:
    route, query = _route_and_query(url)
    if source_job_id := _first_query_value(query, "positionId", "id"):
        return source_job_id
    path_parts = [part for part in route.split("/") if part]
    for marker in ("job-info", "job-info-base"):
        if marker in path_parts:
            index = path_parts.index(marker)
            if index + 1 < len(path_parts) and path_parts[index + 1] != "apply":
                return _text(path_parts[index + 1])
    return None


def _detail_if_needed(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
) -> Mapping[str, object]:
    description = "\n".join(
        value
        for value in (_text(item.get("description")), _text(item.get("positionDemand")))
        if value
    )
    if description:
        return item
    source_job_id = _source_job_id(item)
    if not source_job_id:
        raise ValueError("Kuaishou position has no id")
    query: dict[str, object] = {"id": source_job_id}
    _, source_query = _route_and_query(url)
    if position_status := _first_query_value(source_query, "positionStatus"):
        query["positionStatus"] = position_status
    return _result(request_json(f"{_origin(url)}{_DETAIL_PATH}", "GET", query))


def _detail_url(url: str, source_job_id: str) -> str:
    parts = urlsplit(url)
    base_path = parts.path or "/"
    if not base_path.endswith("/"):
        base_path += "/"
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            base_path,
            "",
            f"/campus/job-info/{quote(source_job_id)}",
        )
    )


def _job(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    detail = _detail_if_needed(item, url, request_json)
    source_job_id = _source_job_id(detail) or _source_job_id(item)
    title = _text(detail.get("name")) or _text(item.get("name"))
    if not source_job_id or not title:
        raise ValueError("Kuaishou position has no id or title")
    description = "\n".join(
        value
        for value in (_text(detail.get("description")), _text(detail.get("positionDemand")))
        if value
    )
    if not description:
        raise ValueError(f"Kuaishou position {source_job_id} has no public description")
    _, query = _route_and_query(url)
    project_codes = _sub_project_codes(url)
    position_nature = _text(detail.get("positionNatureCode")) or _text(
        item.get("positionNatureCode")
    )
    position_label = _text(detail.get("positionLabel")) or _text(item.get("positionLabel"))
    detail_url = _detail_url(url, source_job_id)
    source_ref = f"{_origin(url)}{_DETAIL_PATH}?id={quote(source_job_id)}"
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("workLocationDicts") or item.get("workLocationDicts")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(
            position_nature,
            _text(detail.get("recruitSubProjectCode")) or _text(item.get("recruitSubProjectCode")),
            title,
        ),
        "education_requirement": _text(
            detail.get("educationRequirement")
            or detail.get("education")
            or detail.get("degree")
            or item.get("educationRequirement")
        ),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("updateTime") or item.get("updateTime")),
        "deadline_at": None,
        "source_ref": source_ref,
        "metadata": {
            "parser": "kuaishou",
            "platform_family": "kuaishou-campus",
            "record_kind": "job",
            "detail_status": "list_api" if detail is item else "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "recruit_sub_project_codes": project_codes,
            "position_label": position_label,
            "position_nature_code": position_nature,
            "query_position_nature_code": _first_query_value(query, "positionNatureCode"),
            "list_count": total,
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect all public Kuaishou positions for a campus list or detail page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = request_json or (
        lambda endpoint, method, payload: _request_json(endpoint, url, method, payload)
    )
    direct_id = _detail_id(url)
    if direct_id is not None:
        return [_job({"id": direct_id}, url, requester, 1)]
    items, total = _list_jobs(url, requester)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items) or 1)) as executor:
        return list(executor.map(lambda item: _job(item, url, requester, total), items))


__all__ = ["parse"]
