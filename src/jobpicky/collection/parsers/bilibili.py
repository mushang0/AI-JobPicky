"""Evidence-first adapter for the public Bilibili recruitment API."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .public_api import JsonRequester
from .public_api import request_json as _request_json
from .public_api_support import (
    PublicPage,
    collect_pages,
    map_bounded,
    non_negative_int,
)
from .public_api_support import (
    locations as _locations,
)
from .public_api_support import (
    mapping as _mapping,
)
from .public_api_support import (
    origin as _origin,
)
from .public_api_support import (
    published_at as _published_at,
)
from .public_api_support import (
    text as _text,
)

_PAGE_SIZE = 100
_MAX_JOBS = 500
_MAX_WORKERS = 8
_APP_KEY = "ops.ehr-api.auth"
_CSRF_PATH = "/api/auth/v1/csrf/token"
_LIST_PATH = "/api/campus/position/positionList"
_DETAIL_PATH = "/api/campus/position/detail"
_DIRECT_ID_RE = re.compile(r"/(?:campus|social)/positions/(?P<id>[^/?#]+)", re.IGNORECASE)


class BilibiliSession:
    """Small in-memory public session for Bilibili's CSRF-protected API."""

    def __init__(self, source_url: str) -> None:
        self.source_url = source_url
        self.csrf_token: str | None = None

    def request(
        self,
        endpoint: str,
        method: str,
        payload: Mapping[str, object] | None,
    ) -> object:
        headers = {
            "X-AppKey": _APP_KEY,
            "X-UserType": "2",
            "X-Channel": "campus",
        }
        if self.csrf_token:
            headers.update(
                {
                    "X-CSRF": self.csrf_token,
                    "Cookie": f"X-CSRF={self.csrf_token}",
                }
            )
        return _request_json(
            endpoint,
            self.source_url,
            method,
            payload,
            headers=headers,
        )


def _data(response: object, message: str) -> Mapping[str, object]:
    root = _mapping(response, "Bilibili API response is not an object")
    if str(root.get("code")) != "0":
        raise ValueError(f"Bilibili API returned code {root.get('code')!r}")
    return _mapping(root.get("data"), message)


def _csrf(request_json: JsonRequester, url: str) -> str:
    root = _mapping(
        request_json(f"{_origin(url)}{_CSRF_PATH}", "GET", None),
        "Bilibili CSRF response is not an object",
    )
    if str(root.get("code")) != "0":
        raise ValueError(f"Bilibili CSRF API returned code {root.get('code')!r}")
    token = _text(root.get("data"))
    if not token:
        raise ValueError("Bilibili CSRF API returned no token")
    return token


def _query_values(query: Mapping[str, list[str]], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        for raw in query.get(key, []):
            values.extend(item for item in raw.split(",") if item)
    return values


def _list_payload(url: str, page: int) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    recruit_type = _text(query.get("recruitType", [""])[0])
    return {
        "pageSize": _PAGE_SIZE,
        "pageNum": page,
        "positionName": _text(query.get("positionName", [""])[0]) or "",
        "postCode": None,
        "postCodeList": _query_values(query, "postCodeList", "postCode") or None,
        "workLocationList": _query_values(query, "workLocationList", "city") or None,
        "workTypeList": _query_values(query, "workTypeList"),
        "positionTypeList": _query_values(query, "positionTypeList"),
        "deptCodeList": None,
        "recruitType": int(recruit_type) if recruit_type and recruit_type.isdigit() else None,
        "practiceTypes": _query_values(query, "practiceTypes") or None,
        "onlyHotRecruit": 0,
    }


def _list_page(url: str, request_json: JsonRequester, page: int) -> PublicPage:
    data = _data(
        request_json(
            f"{_origin(url)}{_LIST_PATH}",
            "POST",
            _list_payload(url, page),
        ),
        "Bilibili API did not return position data",
    )
    raw_items = data.get("list")
    if not isinstance(raw_items, list):
        raise ValueError("Bilibili API did not return a position list")
    total = non_negative_int(data.get("total"), "Bilibili API did not return a valid job count")
    pages = non_negative_int(data.get("pages"), "Bilibili API did not return a valid page count")
    return PublicPage(
        total=total,
        page_count=max(1, pages),
        items=[_mapping(item, "Bilibili API returned an invalid position") for item in raw_items],
    )


def _list_jobs(url: str, request_json: JsonRequester) -> tuple[list[Mapping[str, object]], int]:
    return collect_pages(
        lambda page: _list_page(url, request_json, page),
        source="Bilibili",
        max_jobs=_MAX_JOBS,
        max_pages=_MAX_JOBS // _PAGE_SIZE + 1,
        job_id=lambda item: _text(item.get("id")),
    )


def _description(item: Mapping[str, object]) -> str | None:
    return _text(item.get("positionDescription") or item.get("positionDescriptions"))


def _recruitment_type(item: Mapping[str, object], url: str) -> str:
    if "/social/" in urlsplit(url).path.casefold():
        return "社招"
    return "实习" if "实习" in (_text(item.get("positionTypeName")) or "") else "校招"


def _direct_id(url: str) -> str | None:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    for key in ("id", "positionId"):
        if value := _text(query.get(key, [""])[0]):
            return value
    match = _DIRECT_ID_RE.search(urlsplit(url).path)
    return _text(match.group("id")) if match else None


def _detail(
    item: Mapping[str, object],
    url: str,
    request_json: JsonRequester,
    total: int,
    *,
    force_detail: bool = False,
) -> dict[str, object]:
    source_job_id = _text(item.get("id"))
    if not source_job_id:
        raise ValueError("Bilibili position has no id")
    detail_status = "list_api"
    detail = item
    if force_detail or not _description(item):
        detail = _data(
            request_json(
                f"{_origin(url)}{_DETAIL_PATH}/{source_job_id}",
                "GET",
                None,
            ),
            "Bilibili detail API did not return position data",
        )
        detail_status = "public_api"
    title = _text(detail.get("positionName")) or _text(item.get("positionName"))
    description = _description(detail)
    if not title or not description:
        raise ValueError(f"Bilibili position {source_job_id} has no title or description")
    detail_url = urlunsplit(
        (urlsplit(url).scheme, urlsplit(url).netloc, f"/campus/positions/{source_job_id}", "", "")
    )
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(detail.get("workCity") or detail.get("workLocation")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(detail, url),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": _published_at(detail.get("pushTime") or detail.get("ctime")),
        "deadline_at": _published_at(detail.get("endTime")),
        "source_ref": f"{_origin(url)}{_DETAIL_PATH}/{source_job_id}",
        "metadata": {
            "parser": "bilibili",
            "platform_family": "bilibili-careers",
            "record_kind": "job",
            "detail_status": detail_status,
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
    """Collect public Bilibili campus positions without login."""
    if not 1 <= max_workers <= _MAX_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
    session = BilibiliSession(url) if request_json is None else None
    requester = session.request if session is not None else request_json
    assert requester is not None
    csrf_token = _csrf(requester, url)
    if session is not None:
        session.csrf_token = csrf_token
    target_id = _direct_id(url)
    if target_id is not None:
        return [_detail({"id": target_id}, url, requester, 1, force_detail=True)]
    items, total = _list_jobs(url, requester)
    return map_bounded(
        items,
        lambda item: _detail(item, url, requester, total),
        max_workers,
    )


__all__ = ["BilibiliSession", "parse"]
