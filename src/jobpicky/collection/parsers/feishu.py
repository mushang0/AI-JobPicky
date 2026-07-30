from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_DETAIL_RE = re.compile(r"/(?:[^/?#]+/)?position/(\d+)/detail/?$")
_CHROMIUM_ENV = "JOBPICKY_CHROMIUM_PATH"
_CHROMIUM_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)
_MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
_PAGE_SIZE = 100
_MAX_PAGES = 100
_WORKERS_ENV = "JOBPICKY_FEISHU_WORKERS"
_DEFAULT_WORKERS = 4


class ClosedJobError(ValueError):
    pass


class BrowserUnavailableError(RuntimeError):
    pass


class BrowserRenderError(RuntimeError):
    pass


class _DetailLinkParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and _DETAIL_RE.search(urlsplit(href).path):
            self.links.append(urljoin(self.page_url, href))


def _chromium_path() -> str:
    configured = os.environ.get(_CHROMIUM_ENV)
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
        raise BrowserUnavailableError(f"{_CHROMIUM_ENV} does not point to a file")
    for candidate in _CHROMIUM_CANDIDATES:
        if executable := shutil.which(candidate):
            return executable
    if _MAC_CHROME.is_file():
        return str(_MAC_CHROME)
    raise BrowserUnavailableError(f"Chromium not found; install it or set {_CHROMIUM_ENV}")


def render_html(url: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - executable is resolved above
            [
                _chromium_path(),
                "--headless=new",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--no-first-run",
                "--disable-default-apps",
                "--virtual-time-budget=10000",
                "--incognito",
                "--dump-dom",
                url,
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserRenderError("Chromium timed out rendering Feishu") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise BrowserRenderError(f"Chromium failed rendering Feishu (exit {result.returncode})")
    return result.stdout


def fetch_json(url: str, website_path: str) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (compatible; JobPicky/0.1)",
            "website-path": website_path,
        },
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310 - public recruitment URLs only
        return json.load(response)


def _api_url(page_url: str, source_job_id: str) -> str:
    parts = urlsplit(page_url)
    query = urlencode(
        {
            "portal_type": 2,
            "source_job_post_id": source_job_id,
            "with_recommend": "false",
        }
    )
    return urlunsplit((parts.scheme, parts.netloc, f"/api/v1/job/posts/{source_job_id}", query, ""))


def _listing_page_url(url: str, page: int) -> str:
    parts = urlsplit(url.replace("&amp;", "&"))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"current": str(page), "limit": str(_PAGE_SIZE)})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def discover_detail_urls(url: str, render: Callable[[str], str] = render_html) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    for page in range(1, _MAX_PAGES + 1):
        page_url = _listing_page_url(url, page)
        parser = _DetailLinkParser(page_url)
        parser.feed(render(page_url))
        page_links = list(dict.fromkeys(parser.links))
        new_links = [link for link in page_links if link not in seen]
        if not new_links:
            break
        discovered.extend(new_links)
        seen.update(new_links)
        if len(page_links) < _PAGE_SIZE:
            break
        time.sleep(1)
    return discovered


def _name(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("i18n_name", "name", "en_name"):
        name = value.get(key)
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _recruitment_type(detail: Mapping[str, object]) -> str | None:
    recruit_type = detail.get("recruit_type")
    name = _name(recruit_type)
    if name == "正式" and isinstance(recruit_type, Mapping):
        return _name(recruit_type.get("parent"))
    return name


def _published_at(value: object) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    published_at = datetime.fromtimestamp(value / 1000, tz=UTC)
    return published_at if 2000 <= published_at.year < 2200 else None


def _normalise(detail: Mapping[str, object], page_url: str) -> dict[str, object]:
    description = detail.get("description")
    requirement = detail.get("requirement")
    sections = [
        f"{label}\n{text.strip()}"
        for label, text in (("职位描述", description), ("职位要求", requirement))
        if isinstance(text, str) and text.strip()
    ]
    city_list = detail.get("city_list")
    locations = (
        [name for item in city_list if (name := _name(item))] if isinstance(city_list, list) else []
    )
    job_post_info = detail.get("job_post_info")
    required_degree = (
        job_post_info.get("required_degree") if isinstance(job_post_info, Mapping) else None
    )
    metadata = {
        key: value
        for key, value in {
            "department": _name(detail.get("department_info")),
            "job_category": _name(detail.get("job_category")),
            "job_function": _name(detail.get("job_function")),
            "job_subject": _name(detail.get("job_subject")),
            "required_degree_code": required_degree,
            "channel_online_status": detail.get("channel_online_status"),
        }.items()
        if value is not None
    }
    return {
        "source_job_id": str(detail["id"]),
        "title": str(detail["title"]).strip(),
        "description": "\n\n".join(sections) or None,
        "locations": locations,
        "detail_url": page_url,
        "apply_url": page_url,
        "recruitment_type": _recruitment_type(detail),
        "published_at": _published_at(detail.get("publish_time")),
        "source_ref": page_url,
        "metadata": metadata,
    }


def _parse_detail(url: str, fetch: Callable[[str, str], object]) -> dict[str, object]:
    match = _DETAIL_RE.search(urlsplit(url).path)
    if match is None:
        raise ValueError("not a Feishu detail URL")
    source_job_id = match.group(1)
    parts = [part for part in urlsplit(url).path.split("/") if part]
    response = fetch(_api_url(url, source_job_id), parts[0])
    if not isinstance(response, Mapping) or response.get("code") != 0:
        raise ValueError("Feishu detail API returned an invalid response")
    data = response.get("data")
    detail = data.get("job_post_detail") if isinstance(data, Mapping) else None
    if not isinstance(detail, Mapping):
        raise ClosedJobError("Feishu job is unavailable")
    if detail.get("channel_online_status") == 0:
        raise ClosedJobError("Feishu job is closed")
    if not detail.get("id") or not detail.get("title"):
        raise ValueError("Feishu detail API returned a job without id or title")
    return _normalise(detail, url)


def _worker_count() -> int:
    value = os.environ.get(_WORKERS_ENV)
    if value is None:
        return _DEFAULT_WORKERS
    try:
        workers = int(value)
    except ValueError as exc:
        raise ValueError(f"{_WORKERS_ENV} must be an integer") from exc
    if workers < 1:
        raise ValueError(f"{_WORKERS_ENV} must be at least 1")
    return workers


def parse(
    url: str,
    fetch: Callable[[str, str], object] = fetch_json,
    render: Callable[[str], str] = render_html,
) -> list[dict[str, object]]:
    """Parse a Feishu detail or discover and parse one rendered listing."""
    if _DETAIL_RE.search(urlsplit(url).path):
        return [_parse_detail(url, fetch)]

    def parse_open_job(detail_url: str) -> dict[str, object] | None:
        try:
            return _parse_detail(detail_url, fetch)
        except ClosedJobError:
            return None

    detail_urls = discover_detail_urls(url, render)
    with ThreadPoolExecutor(max_workers=_worker_count()) as executor:
        return [job for job in executor.map(parse_open_job, detail_urls) if job is not None]


__all__ = [
    "BrowserRenderError",
    "BrowserUnavailableError",
    "ClosedJobError",
    "discover_detail_urls",
    "fetch_json",
    "parse",
    "render_html",
]
