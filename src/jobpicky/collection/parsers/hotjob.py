from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_SUITE_RE = re.compile(r"/(SU[0-9a-z]+)/", re.IGNORECASE)
_STATIC_CONFIG_RE = re.compile(r"\bsuiteKey\s*:\s*['\"](SU[0-9a-z]+)", re.IGNORECASE)
_CLIENT_ID_RE = re.compile(r"\bClientId\s*:\s*['\"]([^'\"]+)")
_PLATFORM_RE = re.compile(r"\bplatform\s*:\s*['\"]([^'\"]+)")
_WT_LIST_RE = re.compile(r"(?P<path>/wt/[^\"']*/position/list\?operational=[^\"']+)", re.IGNORECASE)
_WT_DETAIL_RE = re.compile(
    r"(?P<path>/wt/[^\"']*/position/detail\?operational=[^\"']+)", re.IGNORECASE
)
_PAGE_SIZE = 100
_MAX_PAGES = 200
_WORKERS_ENV = "JOBPICKY_HOTJOB_WORKERS"
_DEFAULT_WORKERS = 8
_MAX_WORKERS = 16
_REQUEST_RETRIES = 2


class ClosedJobError(ValueError):
    pass


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.append(source)


class _FrameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"iframe", "frame"}:
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.append(source)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.sources.append(href)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _request(
    url: str,
    data: Mapping[str, object] | None = None,
    *,
    method: str = "POST",
    headers: Mapping[str, str] | None = None,
) -> object:
    request_headers = {
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
    }
    if headers:
        request_headers.update(headers)
    body: bytes | None = None
    request_method = method
    if method == "POST":
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(
            [(key, str(value)) for key, value in (data or {}).items() if value is not None]
        ).encode()
    elif method == "GET" and data:
        parts = urlsplit(url)
        query = list(parse_qsl(parts.query, keep_blank_values=True))
        query.extend((key, str(value)) for key, value in data.items() if value is not None)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    else:
        request_method = "GET"

    for attempt in range(_REQUEST_RETRIES):
        try:
            request = Request(url, data=body, headers=request_headers, method=request_method)
            with urlopen(request, timeout=20) as response:  # noqa: S310 - public recruitment URL
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 == _REQUEST_RETRIES:
                raise
            sleep(0.25 * (attempt + 1))
    raise AssertionError("unreachable")


def _fetch_html_response(url: str) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - public recruitment URL
        html = response.read(6 * 1024 * 1024).decode(
            response.headers.get_content_charset() or "utf-8", "replace"
        )
        return response.url, html


def _fetch_html(url: str) -> str:
    return _fetch_html_response(url)[1]


def _request_get(url: str, data: Mapping[str, object] | None = None) -> object:
    return _request(url, data, method="GET")


def _text(value: object) -> str | None:
    if value is None:
        return None
    raw = value if isinstance(value, str) else str(value)
    if "<" in raw and ">" in raw:
        parser = _TextParser()
        parser.feed(raw)
        raw = " ".join(parser.parts)
    result = " ".join(raw.split())
    return result or None


def _date(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("/", "-")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(normalized, fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed if 1900 <= parsed.year < 2200 else None


def _locations(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    item = item.get("name") or item.get("nameCh") or item.get("cityName")
                if text := _text(item):
                    result.append(text)
            continue
        if text := _text(value):
            result.extend(part.strip() for part in re.split(r"[,，、|]", text) if part.strip())
    return list(dict.fromkeys(result))


def _number(value: object) -> int | None:
    try:
        return int(float(str(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


def _recruit_type(value: object, page_url: str) -> tuple[str, str]:
    text = _text(value) or ""
    lowered = text.casefold()
    if lowered in {"1", "campus", "school", "校招", "校园"}:
        return "校招", "1"
    if lowered in {"12", "intern", "实习"}:
        return "实习", "12"
    if lowered in {"2", "social", "society", "社招", "社会"}:
        return "社招", "2"
    if lowered in {"13", "overseas", "海外"}:
        return "海外", "13"
    path = urlsplit(page_url).path.casefold()
    if "intern" in path:
        return "实习", "12"
    if any(marker in path for marker in ("social", "society")):
        return "社招", "2"
    if "overseas" in path:
        return "海外", "13"
    return "校招", "1"


def _suite_key(url: str) -> str | None:
    match = _SUITE_RE.search(urlsplit(url).path + "/")
    return match.group(1) if match else None


def _modern_config(url: str) -> tuple[str, str | None, str | None, str] | None:
    final_url, html = _fetch_html_response(url)
    if suite := _suite_key(final_url):
        return suite, None, None, final_url
    parser = _ScriptParser()
    parser.feed(html)
    for source in parser.sources[:8]:
        script = _fetch_html(urljoin(final_url, source))
        suite_match = _STATIC_CONFIG_RE.search(script)
        if suite_match:
            client_match = _CLIENT_ID_RE.search(script)
            platform_match = _PLATFORM_RE.search(script)
            return (
                suite_match.group(1),
                client_match.group(1) if client_match else None,
                platform_match.group(1) if platform_match else None,
                final_url,
            )
    return None


def _resolve_source(
    url: str, fetch: Callable[[str, Mapping[str, object]], object]
) -> tuple[str, str, str | None, str | None]:
    """Return a suite URL, suite key, and optional modern API headers."""
    suite = _suite_key(url)
    if suite:
        return url, suite, None, None

    parts = urlsplit(url)
    last_error: Exception | None = None
    for scheme in (parts.scheme, "https"):
        try:
            resolved = fetch(
                urlunsplit((scheme, parts.netloc, "/wecruit/common/getSLD", "", "")),
                {"sld": parts.netloc},
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            continue
        if isinstance(resolved, Mapping):
            data = resolved.get("data")
            link_data = data.get("linkData") if isinstance(data, Mapping) else None
            link = link_data.get("link") if isinstance(link_data, Mapping) else None
            if isinstance(link, str) and _suite_key(link):
                return link, _suite_key(link) or "", None, None

    config = _modern_config(url)
    if config is not None:
        modern_suite, client_id, platform, final_url = config
        return final_url, modern_suite, client_id, platform
    if last_error is not None:
        raise ValueError("Hotjob entry did not expose a public suite") from last_error
    raise ValueError("Hotjob entry did not expose a public suite")


def _query_value(url: str, *names: str) -> str | None:
    values = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    for name in names:
        value = values.get(name)
        if value:
            return value
    return None


def _wt_candidate(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return "/wt/" in path or path.rstrip("/") == ""


def _wt_page(url: str, fetch_html: Callable[[str], str]) -> tuple[str, str]:
    page_url = url
    html = fetch_html(page_url)
    frames = _FrameParser()
    frames.feed(html)
    for source in frames.sources[:4]:
        frame_url = urljoin(page_url, source)
        if "/wt/" in urlsplit(frame_url).path.casefold():
            page_url = frame_url
            html = fetch_html(page_url)
            break
    if _WT_LIST_RE.search(html) is None or _WT_DETAIL_RE.search(html) is None:
        links = _LinkParser()
        links.feed(html)
        for source in links.sources[:40]:
            candidate = urljoin(page_url, source)
            path = urlsplit(candidate).path.casefold()
            if not re.search(r"recruit(?:campus|social|interns)", path):
                continue
            candidate_html = fetch_html(candidate)
            if _WT_LIST_RE.search(candidate_html) and _WT_DETAIL_RE.search(candidate_html):
                return candidate, candidate_html
    return page_url, html


def _wt_recruit_type(html: str, page_url: str) -> str:
    for tag in re.findall(r"<input\b[^>]*>", html, re.IGNORECASE):
        attributes = dict(re.findall(r"([\w:-]+)\s*=\s*['\"]([^'\"]*)['\"]", tag, re.IGNORECASE))
        if attributes.get("id", "").casefold() == "recruittypev" and attributes.get("value"):
            return _recruit_type(attributes["value"], page_url)[1]
    return _recruit_type(_query_value(page_url, "recruitType", "postType"), page_url)[1]


def _wt_url(template: str, params: Mapping[str, object]) -> str:
    parts = urlsplit(template.replace("&amp;", "&"))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _normalise_wt(
    listing: Mapping[str, object],
    detail: Mapping[str, object] | None,
    page_url: str,
    recruit_type: str,
    *,
    detail_status: str,
) -> dict[str, object]:
    item = dict(listing)
    if detail:
        item.update(detail)
    item["workPlaceStr"] = item.get("workPlace")
    item["company"] = item.get("companyName") or item.get("orgName")
    item["departmentName"] = item.get("orgName")
    item["postTypeName"] = item.get("postType")
    item["workContent"] = item.get("workConcet") or item.get("workContent")
    item["recruitType"] = item.get("recruitType") or recruit_type
    job = _normalise(
        item,
        None,
        page_url,
        "wt",
        recruit_type,
        modern=False,
        detail_status=detail_status,
    )
    job["detail_url"] = page_url
    job["apply_url"] = page_url
    job["source_ref"] = page_url
    return job


def _parse_wt(
    url: str,
    fetch: Callable[[str, Mapping[str, object]], object],
    fetch_get: Callable[[str, Mapping[str, object]], object],
    fetch_html: Callable[[str], str],
) -> list[dict[str, object]] | None:
    page_url, html = _wt_page(url, fetch_html)
    list_match = _WT_LIST_RE.search(html)
    detail_match = _WT_DETAIL_RE.search(html)
    if list_match is None or detail_match is None:
        return None
    recruit_type = _wt_recruit_type(html, page_url)
    list_template = urljoin(page_url, list_match.group("path"))
    detail_template = urljoin(page_url, detail_match.group("path"))
    rows: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    for page in range(1, _MAX_PAGES + 1):
        response = fetch_get(
            _wt_url(
                list_template,
                {
                    "positionType": "",
                    "comPart": "",
                    "brandCode": "1",
                    "trademark": "0",
                    "recruitType": recruit_type,
                    "projectId": "",
                    "lanType": "",
                    "positionName": "",
                    "workPlace": "",
                    "keyWord": "",
                    "page": page,
                },
            ),
            {},
        )
        if not isinstance(response, Mapping):
            raise ValueError("Hotjob WT list API returned an invalid response")
        raw_rows = response.get("postList")
        if not isinstance(raw_rows, list):
            raise ValueError("Hotjob WT list API returned no post list")
        if not raw_rows:
            if page == 1:
                raise ValueError("Hotjob WT list API returned no jobs")
            break
        for row in raw_rows:
            if not isinstance(row, Mapping):
                continue
            source_job_id = _text(row.get("postId"))
            if source_job_id and source_job_id not in seen_ids:
                seen_ids.add(source_job_id)
                rows.append(row)
        total_pages = _number(response.get("pageCount"))
        if total_pages is not None:
            if total_pages > _MAX_PAGES:
                raise ValueError("Hotjob WT list exceeds the safe pagination limit")
            if page >= total_pages:
                break
        elif len(raw_rows) < 10:
            break
    else:
        raise ValueError("Hotjob WT list exceeded the safe pagination limit")

    if not rows:
        raise ValueError("Hotjob WT list contained no usable jobs")

    def parse_row(row: Mapping[str, object]) -> dict[str, object]:
        post_id = _text(row.get("postId"))
        if not post_id:
            raise ValueError("Hotjob WT row has no postId")
        try:
            response = fetch_get(
                _wt_url(
                    detail_template,
                    {
                        "recruitType": _text(row.get("recruitType")) or recruit_type,
                        "postId": post_id,
                    },
                ),
                {},
            )
            detail = response.get("postInfo") if isinstance(response, Mapping) else None
            if not isinstance(detail, Mapping):
                raise ValueError("Hotjob WT detail API returned no post info")
        except (HTTPError, URLError, TimeoutError, ValueError):
            return _normalise_wt(
                row, None, page_url, recruit_type, detail_status="unavailable-fallback"
            )
        return _normalise_wt(row, detail, page_url, recruit_type, detail_status="ok")

    with ThreadPoolExecutor(max_workers=min(_workers(), len(rows))) as executor:
        return list(executor.map(parse_row, rows))


def _canonical_url(url: str, suite: str, post_id: str, recruit_type: str, modern: bool) -> str:
    parts = urlsplit(url)
    route = "mc/detail" if "/mc/" in parts.path.lower() and not modern else "pb/posDetail.html"
    query_name = "recruitType" if route.startswith("mc/") else "postType"
    value = {
        "1": "campus",
        "12": "intern",
        "2": "social",
        "13": "overseas",
    }.get(recruit_type, recruit_type)
    query = urlencode({"postId": post_id, query_name: value})
    return urlunsplit((parts.scheme, parts.netloc, f"/{suite}/{route}", query, ""))


def _normalise(
    listing: Mapping[str, object],
    detail: Mapping[str, object] | None,
    page_url: str,
    suite: str,
    recruit_type: str,
    *,
    modern: bool,
    detail_status: str,
) -> dict[str, object]:
    item: Mapping[str, object] = detail or listing
    post_id = _text(item.get("postId") or listing.get("postId"))
    title = _text(item.get("postName") or listing.get("postName"))
    if not post_id or not title:
        raise ValueError("Hotjob response returned a job without postId or postName")
    recruitment_type, numeric_type = _recruit_type(
        item.get("recruitType") or listing.get("recruitType") or recruit_type, page_url
    )
    canonical = _canonical_url(page_url, suite, post_id, numeric_type, modern)
    descriptions = [
        ("岗位职责", item.get("workContent")),
        ("申请要求", item.get("applyPositionContent")),
        ("专业要求", item.get("subject")),
    ]
    description = (
        "\n\n".join(f"{label}\n{text}" for label, value in descriptions if (text := _text(value)))
        or None
    )
    metadata = {
        key: value
        for key, value in {
            "company": _text(item.get("company") or listing.get("company")),
            "department": _text(
                item.get("departmentName")
                or item.get("department")
                or listing.get("departmentName")
            ),
            "project_name": _text(item.get("projectName") or listing.get("projectName")),
            "post_type": _text(item.get("postTypeName") or listing.get("postTypeName")),
            "recruitment_type_code": _number(item.get("recruitType") or listing.get("recruitType")),
            "detail_status": detail_status,
        }.items()
        if value is not None
    }
    education = _text(
        item.get("education")
        or item.get("educationStr")
        or listing.get("education")
        or listing.get("educationStr")
    )
    return {
        "source_job_id": post_id,
        "title": title,
        "description": description,
        "locations": _locations(
            item.get("workPlaceList"),
            item.get("workPlaceStr"),
            listing.get("workPlaceStr"),
        ),
        "detail_url": canonical,
        "apply_url": canonical,
        "recruitment_type": recruitment_type,
        "education_requirement": education,
        "published_at": _date(item.get("publishDate") or listing.get("publishDate")),
        "deadline_at": _date(item.get("endDate") or listing.get("endDate")),
        "source_ref": canonical,
        "metadata": metadata,
    }


def _response_data(response: object, endpoint: str) -> Mapping[str, object]:
    if not isinstance(response, Mapping) or str(response.get("state")) not in {"200", "200.0"}:
        state = response.get("state") if isinstance(response, Mapping) else None
        raise ValueError(f"Hotjob {endpoint} API returned state {state!r}")
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise ValueError(f"Hotjob {endpoint} API returned no data")
    return data


def _detail(
    page_url: str,
    suite: str,
    post_id: str,
    recruit_type: str,
    fetch: Callable[[str, Mapping[str, object]], object],
) -> Mapping[str, object]:
    endpoint = urlunsplit(
        (
            urlsplit(page_url).scheme,
            urlsplit(page_url).netloc,
            f"/wecruit/positionInfo/listPositionDetail/{suite}",
            "",
            "",
        )
    )
    data = _response_data(
        fetch(endpoint, {"postId": post_id, "recruitType": recruit_type}),
        "detail",
    )
    if data.get("postId") is None or not _text(data.get("postName")):
        raise ClosedJobError("Hotjob job is closed or unavailable")
    return data


def _workers() -> int:
    value = os.environ.get(_WORKERS_ENV)
    if value is None:
        return _DEFAULT_WORKERS
    try:
        workers = int(value)
    except ValueError as exc:
        raise ValueError(f"{_WORKERS_ENV} must be an integer") from exc
    if workers < 1:
        raise ValueError(f"{_WORKERS_ENV} must be at least 1")
    if workers > _MAX_WORKERS:
        raise ValueError(f"{_WORKERS_ENV} must be at most {_MAX_WORKERS}")
    return workers


def _list_page(
    page_url: str,
    suite: str,
    page: int,
    recruit_type: str,
    *,
    page_size: int,
    is_pb: bool,
    modern: bool,
    fetch: Callable[[str, Mapping[str, object]], object],
    client_id: str | None,
    platform: str | None,
) -> Mapping[str, object]:
    parts = urlsplit(page_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    data: dict[str, object] = {
        "recruitType": recruit_type,
        "pageSize": page_size,
        "currentPage": page,
    }
    if is_pb:
        data["isFrompb"] = "true"
    if query.get("projectCode"):
        data["projectCode"] = query["projectCode"]
    if query.get("projectId"):
        data["externalProjectStr"] = query["projectId"]
    for key in ("postKey", "orgCode", "workPlaceCode", "postTypeCode"):
        if query.get(key):
            data[key] = query[key]
    endpoint = urlunsplit(
        (parts.scheme, parts.netloc, f"/wecruit/positionInfo/listPosition/{suite}", "", "")
    )
    if modern:
        headers = {
            "ClientId": client_id or "",
            "platform": platform or "",
            "Accept-Language": "zh-cn",
        }
        response = _request(endpoint, data, method="GET", headers=headers)
    else:
        response = fetch(endpoint, data)
    return _response_data(response, "list")


def _collect_rows(
    page_url: str,
    suite: str,
    recruit_type: str,
    *,
    is_pb: bool,
    modern: bool,
    fetch: Callable[[str, Mapping[str, object]], object],
    client_id: str | None,
    platform: str | None,
) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    total_pages: int | None = None
    page_size = _PAGE_SIZE
    for page in range(1, _MAX_PAGES + 1):
        data = _list_page(
            page_url,
            suite,
            page,
            recruit_type,
            page_size=page_size,
            is_pb=is_pb,
            modern=modern,
            fetch=fetch,
            client_id=client_id,
            platform=platform,
        )
        page_form = data.get("pageForm")
        if not isinstance(page_form, Mapping):
            raise ValueError("Hotjob list API returned no page form")
        page_rows = page_form.get("pageData")
        if not isinstance(page_rows, list):
            raise ValueError("Hotjob list API returned no page data")
        server_page_size = _number(page_form.get("pageSize"))
        if server_page_size and server_page_size > 0:
            page_size = server_page_size
        if not page_rows:
            if page == 1:
                raise ValueError("Hotjob list API returned no jobs")
            if total_pages is not None and page <= total_pages:
                raise ValueError("Hotjob list pagination ended before totalPage")
            break
        for row in page_rows:
            if not isinstance(row, Mapping):
                continue
            row_id = _text(row.get("postId"))
            if row_id and row_id not in seen_ids:
                seen_ids.add(row_id)
                rows.append(row)
        candidate_total = _number(page_form.get("totalPage"))
        if candidate_total is not None:
            total_pages = candidate_total
            if total_pages > _MAX_PAGES:
                raise ValueError("Hotjob list exceeds the safe pagination limit")
            if page >= total_pages:
                break
        elif len(page_rows) < _PAGE_SIZE:
            break
    else:
        raise ValueError("Hotjob list exceeded the safe pagination limit")
    if not rows:
        raise ValueError("Hotjob list contained no usable jobs")
    return rows


def parse(
    url: str,
    fetch: Callable[[str, Mapping[str, object]], object] = _request,
    fetch_get: Callable[[str, Mapping[str, object]], object] = _request_get,
    fetch_html: Callable[[str], str] = _fetch_html,
) -> list[dict[str, object]]:
    """Parse a Hotjob suite, mobile detail, or public list entry."""
    if _wt_candidate(url):
        wt_jobs = _parse_wt(url, fetch, fetch_get, fetch_html)
        if wt_jobs is not None:
            return wt_jobs
    page_url, suite, client_id, platform = _resolve_source(url, fetch)
    modern = client_id is not None or platform is not None
    parts = urlsplit(page_url)
    recruit_label, recruit_type = _recruit_type(
        _query_value(page_url, "recruitType", "postType"), page_url
    )
    del recruit_label
    post_id = _query_value(page_url, "postId", "postid", "id")
    if post_id:
        detail = _detail(page_url, suite, post_id, recruit_type, fetch)
        return [
            _normalise(
                detail,
                detail,
                page_url,
                suite,
                recruit_type,
                modern=modern,
                detail_status="direct",
            )
        ]

    is_pb = "/pb/" in parts.path.lower() or parts.path.casefold().endswith("/pb")
    root_without_type = (
        _suite_key(url) is None and _query_value(url, "recruitType", "postType") is None
    )
    candidate_types = [recruit_type]
    if root_without_type:
        candidate_types.extend(
            candidate for candidate in ("1", "2", "12", "13") if candidate not in candidate_types
        )
    all_rows: list[Mapping[str, object]] | None = None
    last_error: ValueError | None = None
    for candidate_type in candidate_types:
        try:
            all_rows = _collect_rows(
                page_url,
                suite,
                candidate_type,
                is_pb=is_pb,
                modern=modern,
                fetch=fetch,
                client_id=client_id,
                platform=platform,
            )
            recruit_type = candidate_type
            break
        except ValueError as exc:
            last_error = exc
            if not root_without_type or "no jobs" not in str(exc):
                raise
    if all_rows is None:
        raise last_error or ValueError("Hotjob list contained no usable jobs")

    def parse_row(row: Mapping[str, object]) -> dict[str, object] | None:
        row_id = _text(row.get("postId"))
        if not row_id:
            raise ValueError("Hotjob list row has no postId")
        try:
            detail = _detail(page_url, suite, row_id, recruit_type, fetch)
        except ClosedJobError:
            return None
        except (HTTPError, URLError, TimeoutError, ValueError):
            return _normalise(
                row,
                None,
                page_url,
                suite,
                recruit_type,
                modern=modern,
                detail_status="unavailable-fallback",
            )
        return _normalise(
            row,
            detail,
            page_url,
            suite,
            recruit_type,
            modern=modern,
            detail_status="ok",
        )

    with ThreadPoolExecutor(max_workers=min(_workers(), len(all_rows))) as executor:
        jobs = [job for job in executor.map(parse_row, all_rows) if job is not None]
    if not jobs:
        raise ValueError("Hotjob list contained no open jobs")
    return jobs


__all__ = ["ClosedJobError", "parse"]
