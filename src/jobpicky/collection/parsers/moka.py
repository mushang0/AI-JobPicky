from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

_ROUTE_RE = re.compile(
    r"/(?:m/)?(?P<mode>campus-recruitment|social-recruitment|campus_apply|apply|"
    r"recommendation-apply)/"
    r"(?P<org>[^/?#]+)/(?P<site>\d+)(?:/|$)",
    re.IGNORECASE,
)
_JOB_FRAGMENT_RE = re.compile(r"(?:^|/)job/(?P<job_id>[^/?#]+)", re.IGNORECASE)
_CLOSED_STATUSES = frozenset({"closed", "offline", "disabled", "draft", "deleted"})
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5
_MAX_HTML_BYTES = 10 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


class _InitDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.init_data: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        attributes = dict(attrs)
        if attributes.get("id") == "init-data":
            self.init_data = attributes.get("value")


class MokaSession:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirect, HTTPCookieProcessor(CookieJar()))

    def fetch_page(self, url: str) -> tuple[str, str]:
        current_url = url
        for _ in range(_MAX_REDIRECTS):
            request = Request(
                current_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                    "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
                },
            )
            try:
                response = self._opener.open(request, timeout=20)
            except HTTPError as exc:
                if exc.code not in _REDIRECT_CODES:
                    raise
                location = exc.headers.get("Location")
                if not location:
                    raise ValueError("Moka redirect has no Location") from exc
                current_url = urljoin(current_url, location)
                continue
            with response:
                body = response.read(_MAX_HTML_BYTES + 1)
                if len(body) > _MAX_HTML_BYTES:
                    raise ValueError("Moka page exceeds the safe response limit")
                return response.url, body.decode(
                    response.headers.get_content_charset() or "utf-8", "replace"
                )
        raise ValueError("Moka page exceeded the safe redirect limit")

    def fetch_html(self, url: str) -> str:
        return self.fetch_page(url)[1]


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())
    return result or None


def _date(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed if 1900 <= parsed.year < 2200 else None


def _locations(value: object) -> list[str]:
    if not isinstance(value, list):
        value = [value]
    locations: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            item = (
                item.get("cityName") or item.get("city") or item.get("name") or item.get("address")
            )
        if text := _text(item):
            locations.append(text)
    return list(dict.fromkeys(locations))


def _route(url: str) -> tuple[str, str, str] | None:
    match = _ROUTE_RE.search(urlsplit(url).path)
    if match is None:
        return None
    return match.group("mode").casefold(), match.group("org"), match.group("site")


def source_identity(url: str) -> str | None:
    route = _route(url)
    return "/".join(route) if route else None


def _target_job_id(url: str) -> str | None:
    fragment = urlsplit(url).fragment
    match = _JOB_FRAGMENT_RE.search(fragment)
    return match.group("job_id") if match else None


def entry_identity(url: str) -> str | None:
    identity = source_identity(url)
    if identity is None:
        return None
    target_id = _target_job_id(url)
    return f"{identity}/job/{target_id}" if target_id else f"{identity}/list"


def _detail_url(url: str, job_id: str) -> str:
    parts = urlsplit(url)
    fragment = f"/job/{job_id}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment))


def _is_open(job: Mapping[str, object]) -> bool:
    status = _text(job.get("status"))
    if status and status.casefold() in _CLOSED_STATUSES:
        return False
    if status and status.casefold() == "open":
        return True
    closed_at = _date(job.get("closedAt"))
    if closed_at is None:
        return True
    opened_at = _date(job.get("openedAt"))
    return opened_at is not None and opened_at > closed_at


def _recruitment_type(mode: str) -> str:
    return "社招" if mode == "social-recruitment" else "校招"


def _normalise(
    job: Mapping[str, object],
    page_url: str,
    mode: str,
    org_id: str,
    site_id: str,
) -> dict[str, object]:
    source_job_id = _text(job.get("id"))
    title = _text(job.get("title"))
    if not source_job_id or not title:
        raise ValueError("Moka init-data job has no id or title")
    detail_url = _detail_url(page_url, source_job_id)
    department = job.get("department")
    department_name = (
        department.get("name") if isinstance(department, Mapping) else _text(department)
    )
    metadata = {
        key: value
        for key, value in {
            "org_id": org_id,
            "site_id": site_id,
            "status": _text(job.get("status")),
            "department": _text(department_name),
            "hire_mode": job.get("hireMode"),
            "source_status": "open",
        }.items()
        if value is not None
    }
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": None,
        "locations": _locations(job.get("locations") or job.get("location")),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(mode),
        "published_at": _date(
            job.get("publishedAt") or job.get("openedAt") or job.get("createdAt")
        ),
        "source_ref": detail_url,
        "metadata": metadata,
    }


def _load_init_data(page: str) -> Mapping[str, object]:
    parser = _InitDataParser()
    parser.feed(page)
    if parser.init_data is None:
        raise ValueError("Moka page has no init-data")
    candidates = [parser.init_data, html.unescape(parser.init_data)]
    data: object | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if data is None:
        raise ValueError("Moka init-data is not valid JSON")
    if not isinstance(data, Mapping):
        raise ValueError("Moka init-data is not an object")
    return data


def parse(url: str, fetch_html: Callable[[str], str] | None = None) -> list[dict[str, object]]:
    """Parse Moka jobs from public server-rendered init-data."""
    if fetch_html is None:
        page_url, page = MokaSession().fetch_page(url)
    else:
        page_url = url
        page = fetch_html(url)
    route = _route(page_url) or _route(url)
    data = _load_init_data(page)
    if route is None:
        org = data.get("org")
        org_id = _text(org.get("id")) if isinstance(org, Mapping) else None
        site_id = _text(data.get("siteId"))
        if not org_id or not site_id:
            raise ValueError("Moka URL has no public recruitment route")
        mode = "social-recruitment" if "social" in page_url.casefold() else "campus-recruitment"
    else:
        mode, org_id, site_id = route
    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, list):
        raise ValueError("Moka init-data has no job list")
    target_id = _target_job_id(url)
    jobs: list[dict[str, object]] = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, Mapping) or not _is_open(raw_job):
            continue
        if target_id is not None and _text(raw_job.get("id")) != target_id:
            continue
        jobs.append(_normalise(raw_job, page_url, mode, org_id, site_id))
    if target_id is not None and not jobs:
        raise ValueError("Moka target job is closed or absent from init-data")
    if not jobs:
        raise ValueError("Moka init-data contains no open jobs")
    return jobs


__all__ = ["MokaSession", "entry_identity", "parse", "source_identity"]
