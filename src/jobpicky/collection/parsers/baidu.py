"""Evidence-first adapter for the public Baidu recruitment API."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_form_json as _request_form_json

_PAGE_SIZE = 10
_MAX_JOBS = 500
_MAX_WORKERS = 8
_LIST_PATH = "/httservice/getPostListNew"
_DETAIL_PATH = "/httservice/getPostDetail"


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


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response, "Baidu API response is not an object")
    if root.get("status") != "ok":
        raise ValueError(f"Baidu API returned status {root.get('status')!r}")
    return _mapping(root.get("data"), "Baidu API did not return an object")


def _count(value: object) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Baidu API did not return a valid job count") from exc
    if result < 0:
        raise ValueError("Baidu API returned a negative job count")
    return result


def _query_values(query: Mapping[str, list[str]], key: str) -> list[str]:
    return [
        item
        for raw in (query.get(key, []) + query.get(f"{key}[]", []))
        for item in raw.split(",")
        if item
    ]


def _recruit_type(url: str) -> str:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    if value := _text(query.get("recruitType", [""])[0]):
        return value
    return "SOCIAL" if "social" in urlsplit(url).path.casefold() else "GRADUATE"


def _project_type(url: str) -> str:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return _text(query.get("projectType", [""])[0]) or ""


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return {
        "recruitType": _recruit_type(url),
        "workPlace": _query_values(query, "workPlace"),
        "pageSize": _PAGE_SIZE,
        "keyWord": (
            _text(query.get("search", [""])[0]) or _text(query.get("keyWord", [""])[0]) or ""
        ),
        "postType": _query_values(query, "postType"),
        "curPage": page,
        "projectType": _project_type(url),
    }


def _list_jobs(
    url: str,
    request_form_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    origin = _origin(url)
    total: int | None = None
    items: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    page = 1
    while page <= _MAX_JOBS // _PAGE_SIZE + 1:
        data = _data(
            request_form_json(
                f"{origin}{_LIST_PATH}",
                "POST",
                _list_payload(url, page),
            )
        )
        if total is None:
            total = _count(data.get("total"))
            if total > _MAX_JOBS:
                raise ValueError(f"Baidu API returned {total} jobs, above the safe limit")
            if total == 0:
                return [], 0
        page_items = data.get("list")
        if not isinstance(page_items, list):
            raise ValueError("Baidu API did not return a position list")
        mapped_items = [
            _mapping(item, "Baidu API returned an invalid position") for item in page_items
        ]
        new_items = 0
        for item in mapped_items:
            source_job_id = _text(item.get("postId")) or _text(item.get("jobId"))
            if source_job_id and source_job_id not in seen_ids:
                seen_ids.add(source_job_id)
                items.append(item)
                new_items += 1
        if not mapped_items or new_items == 0:
            raise ValueError("Baidu API returned an incomplete or repeated page")
        if len(items) >= total:
            return items[:total], total
        page += 1
    raise ValueError("Baidu API pagination exceeded the safe page limit")


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


def _recruitment_type(value: str) -> str | None:
    if value == "INTERN" or "实习" in value:
        return "实习"
    if value == "SOCIAL" or "社招" in value or "社会" in value:
        return "社招"
    if value == "GRADUATE" or any(marker in value for marker in ("校招", "校园", "应届")):
        return "校招"
    return None


def _detail_parts(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    source_job_id = _text(query.get("postId", [""])[0])
    recruit_type = _text(query.get("recruitType", [""])[0])
    path_parts = [unquote(part) for part in parts.path.split("/") if part]
    if source_job_id is None and len(path_parts) >= 3 and "detail" in path_parts:
        source_job_id = _text(path_parts[-1])
        recruit_type = recruit_type or _text(path_parts[-2])
    if not source_job_id:
        return None
    return recruit_type or "GRADUATE", source_job_id


def _detail_if_needed(
    item: Mapping[str, object],
    url: str,
    recruit_type: str,
    request_form_json: JsonRequester,
) -> Mapping[str, object]:
    description = "\n".join(
        value
        for value in (_text(item.get("workContent")), _text(item.get("serviceCondition")))
        if value
    )
    if description:
        return item
    source_job_id = _text(item.get("postId")) or _text(item.get("jobId"))
    if not source_job_id:
        raise ValueError("Baidu position has no id")
    return _data(
        request_form_json(
            f"{_origin(url)}{_DETAIL_PATH}",
            "GET",
            {"postId": source_job_id, "recruitType": recruit_type},
        )
    )


def _job(
    item: Mapping[str, object],
    url: str,
    recruit_type: str,
    project_type: str,
    request_form_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    detail = _detail_if_needed(item, url, recruit_type, request_form_json)
    source_job_id = _text(detail.get("postId")) or _text(item.get("postId"))
    title = _text(detail.get("name")) or _text(item.get("name"))
    if not source_job_id or not title:
        raise ValueError("Baidu position has no id or title")
    description = "\n".join(
        value
        for value in (_text(detail.get("workContent")), _text(detail.get("serviceCondition")))
        if value
    )
    if not description:
        raise ValueError(f"Baidu position {source_job_id} has no public description")
    detail_url = urlunsplit(
        (
            urlsplit(url).scheme,
            urlsplit(url).netloc,
            f"/jobs/detail/{quote(recruit_type)}/{quote(source_job_id)}",
            "",
            "",
        )
    )
    detail_endpoint = f"{_origin(url)}{_DETAIL_PATH}"
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("workPlace") or item.get("workPlace")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(recruit_type)
        or _recruitment_type(_text(detail.get("projectType")) or ""),
        "education_requirement": _text(detail.get("education")),
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("publishDate") or detail.get("updateDate")),
        "deadline_at": None,
        "source_ref": (
            f"{detail_endpoint}?postId={quote(source_job_id)}&recruitType={quote(recruit_type)}"
        ),
        "metadata": {
            "parser": "baidu",
            "platform_family": "baidu-campus",
            "record_kind": "job",
            "detail_status": "list_api" if detail is item else "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "recruit_type_code": recruit_type,
            "project_type": project_type,
            "list_count": total,
        },
    }


def parse(
    url: str,
    request_json: JsonRequester | None = None,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[dict[str, object]]:
    """Collect all public Baidu positions for a recruitment page."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    requester = request_json or (
        lambda endpoint, method, payload: _request_form_json(endpoint, url, method, payload)
    )
    direct = _detail_parts(url)
    if direct is not None:
        recruit_type, source_job_id = direct
        return [
            _job(
                {"postId": source_job_id},
                url,
                recruit_type,
                _project_type(url),
                requester,
                1,
            )
        ]
    recruit_type = _recruit_type(url)
    project_type = _project_type(url)
    items, total = _list_jobs(url, requester)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items) or 1)) as executor:
        return list(
            executor.map(
                lambda item: _job(item, url, recruit_type, project_type, requester, total),
                items,
            )
        )


__all__ = ["parse"]
