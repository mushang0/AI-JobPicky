"""Evidence-first adapter for the public NetEase campus API."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json

_PAGE_SIZE = 100
_MAX_JOBS = 500
_LIST_PATH = "/api/campuspc/position/getJobList"
_DETAIL_PATH = "/api/campuspc/position/getJobDetails"
_API_ORIGIN = "https://campus.163.com"
_HR_DETAIL_PATH = "/api/hr163/position/query"
_HR_API_ORIGIN = "https://hr.163.com"


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


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("NetEase API response is not an object")
    return value


def _data(response: object) -> Mapping[str, object]:
    root = _mapping(response)
    if root.get("code") != 200:
        raise ValueError(f"NetEase API returned code {root.get('code')!r}")
    return _mapping(root.get("data"))


def _project_id(url: str) -> str:
    values = parse_qs(urlsplit(url).query).get("id", [])
    project_id = _text(values[0]) if values else None
    if not project_id or not project_id.isdigit():
        raise ValueError("NetEase recruitment URL has no numeric project id")
    return project_id


def _count(value: object) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("NetEase API did not return a valid job count") from exc
    if result < 0:
        raise ValueError("NetEase API returned a negative job count")
    return result


def _list_jobs(
    project_id: str,
    source_url: str,
    request_json: JsonRequester,
) -> tuple[list[Mapping[str, object]], int]:
    total: int | None = None
    items: list[Mapping[str, object]] = []
    page = 1
    while page <= _MAX_JOBS:
        data = _data(
            request_json(
                f"{_API_ORIGIN}{_LIST_PATH}",
                "GET",
                {"projectId": project_id, "pageSize": _PAGE_SIZE, "currentPage": page},
            )
        )
        if total is None:
            total = _count(data.get("total"))
            if total > _MAX_JOBS:
                raise ValueError(f"NetEase API returned {total} jobs, above the safe limit")
        page_items = data.get("list")
        if not isinstance(page_items, list):
            raise ValueError("NetEase API did not return a position list")
        mapped_items = [_mapping(item) for item in page_items if isinstance(item, Mapping)]
        if not mapped_items and len(items) < total:
            raise ValueError("NetEase API returned an incomplete page")
        items.extend(mapped_items)
        if len(items) >= total:
            return items[:total], total
        page += 1
    raise ValueError("NetEase API pagination exceeded the safe page limit")


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


def _recruitment_type(value: str | None) -> str | None:
    if not value:
        return None
    if "实习" in value:
        return "实习"
    if any(marker in value for marker in ("校招", "校园", "应届")):
        return "校招"
    if "社招" in value or "社会" in value:
        return "社招"
    return None


def _parse_hr_detail(url: str, request_json: JsonRequester) -> list[dict[str, object]]:
    values = parse_qs(urlsplit(url).query).get("id", [])
    source_job_id = _text(values[0]) if values else None
    if not source_job_id or not source_job_id.isdigit():
        raise ValueError("NetEase HR URL has no numeric position id")
    endpoint = f"{_HR_API_ORIGIN}{_HR_DETAIL_PATH}"
    root = _mapping(request_json(endpoint, "GET", {"id": source_job_id}))
    if root.get("code") != 200:
        raise ValueError(f"NetEase HR API returned code {root.get('code')!r}")
    detail = _mapping(root.get("data"))
    title = _text(detail.get("name"))
    description = "\n".join(
        value
        for value in (_text(detail.get("description")), _text(detail.get("requirement")))
        if value
    )
    if not title or not description:
        raise ValueError(f"NetEase HR position {source_job_id} has no public title or description")
    source_parts = urlsplit(url)
    detail_url = urlunsplit(
        (source_parts.scheme, source_parts.netloc, source_parts.path, source_parts.query, "")
    )
    return [
        {
            "source_job_id": source_job_id,
            "title": title,
            "description": description,
            "locations": _locations(detail.get("workPlaceNameList")),
            "detail_url": detail_url,
            "apply_url": detail_url,
            "recruitment_type": _recruitment_type(_text(detail.get("workType"))),
            "education_requirement": _text(detail.get("reqEducationName")),
            "salary_min": None,
            "salary_max": None,
            "salary_months": None,
            "published_at": _published_at(detail.get("updateTime")),
            "deadline_at": None,
            "source_ref": f"{endpoint}?id={quote(source_job_id)}",
            "metadata": {
                "parser": "netease-hr",
                "platform_family": "netease-hr",
                "record_kind": "job",
                "detail_status": "public_api",
                "detail_api_route": _HR_DETAIL_PATH,
                "list_count": 1,
            },
        }
    ]


def _detail_if_needed(
    item: Mapping[str, object],
    project_id: str,
    source_url: str,
    request_json: JsonRequester,
) -> Mapping[str, object]:
    description = "\n".join(
        value
        for value in (
            _text(item.get("positionDescription")),
            _text(item.get("positionRequirement")),
        )
        if value
    )
    if description:
        return item
    source_job_id = _text(item.get("id"))
    if not source_job_id:
        raise ValueError("NetEase position has no id")
    detail = _data(
        request_json(
            f"{_API_ORIGIN}{_DETAIL_PATH}",
            "GET",
            {"id": source_job_id, "projectId": project_id},
        )
    )
    return detail


def _job(
    item: Mapping[str, object],
    project_id: str,
    source_url: str,
    request_json: JsonRequester,
    total: int,
) -> dict[str, object]:
    detail = _detail_if_needed(item, project_id, source_url, request_json)
    source_job_id = _text(detail.get("id")) or _text(item.get("id"))
    title = _text(detail.get("positionName")) or _text(item.get("positionName"))
    if not source_job_id or not title:
        raise ValueError("NetEase position has no id or title")
    description = "\n".join(
        value
        for value in (
            _text(detail.get("positionDescription")),
            _text(detail.get("positionRequirement")),
        )
        if value
    )
    if not description:
        raise ValueError(f"NetEase position {source_job_id} has no public description")
    detail_url = urlunsplit(
        (
            urlsplit(source_url).scheme,
            urlsplit(source_url).netloc,
            "/app/detail/index",
            f"id={quote(source_job_id)}&projectId={quote(project_id)}",
            "",
        )
    )
    project_name = _text(detail.get("projectName")) or _text(item.get("projectName"))
    position_type = _text(detail.get("positionTypeName")) or _text(item.get("positionTypeName"))
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("workPlaceName") or item.get("workPlaceName")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(project_name) or _recruitment_type(position_type),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("publishTime") or item.get("publishTime")),
        "deadline_at": None,
        "source_ref": (
            f"{_API_ORIGIN}{_DETAIL_PATH}?id={quote(source_job_id)}&projectId={quote(project_id)}"
        ),
        "metadata": {
            "parser": "netease",
            "platform_family": "netease-campus",
            "record_kind": "job",
            "detail_status": "list_api" if detail is item else "public_api",
            "api_route": _LIST_PATH,
            "detail_api_route": _DETAIL_PATH,
            "project_id": project_id,
            "list_count": total,
        },
    }


def parse(url: str, request_json: JsonRequester | None = None) -> list[dict[str, object]]:
    """Collect all public NetEase positions for a project page."""
    requester = request_json or (
        lambda endpoint, method, payload: _request_json(endpoint, url, method, payload)
    )
    if (urlsplit(url).hostname or "").casefold().endswith("hr.163.com"):
        return _parse_hr_detail(url, requester)
    project_id = _project_id(url)
    items, total = _list_jobs(project_id, url, requester)
    return [_job(item, project_id, url, requester, total) for item in items]


__all__ = ["parse"]
