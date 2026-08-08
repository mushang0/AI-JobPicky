from __future__ import annotations

import base64
import binascii
import html
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

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
_LIST_PATH = "/api/outer/ats-apply/website/jobs/v2"
_DETAIL_PATH = "/api/outer/ats-apply/website/job"
_LIST_PAGE_SIZE = 30
_MAX_LIST_JOBS = 500
_MAX_API_ATTEMPTS = 2
_API_RETRY_DELAY_SECONDS = 0.25
_TRACKING_QUERY_KEYS = frozenset({"previewkey", "recommendcode", "sourcetoken"})
_DEFAULT_LOCALE = "zh-CN"
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_IGNORED_TAGS = frozenset({"script", "style"})
MokaDetailFetcher = Callable[
    [str, str, str, str, str],
    Mapping[str, object],
]
MokaJobListFetcher = Callable[
    [str, str, str, str, str, int, int, str | None],
    Mapping[str, object],
]


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


class _DescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if not self._ignored_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif not self._ignored_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


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

    def _fetch_encrypted_json(
        self,
        page_url: str,
        path: str,
        payload: Mapping[str, object],
        aes_iv: str | None,
        label: str,
    ) -> Mapping[str, object]:
        request = Request(
            f"{_origin(page_url)}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Content-Type": "application/json",
                "Origin": _origin(page_url),
                "Referer": page_url,
                "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
                "use-http-status": "0",
            },
        )
        response = None
        for attempt in range(_MAX_API_ATTEMPTS):
            try:
                response = self._opener.open(request, timeout=20)
                break
            except HTTPError as exc:
                raise ValueError(f"Moka {label} API returned HTTP {exc.code}") from exc
            except (TimeoutError, URLError):
                if attempt == _MAX_API_ATTEMPTS - 1:
                    raise
                sleep(_API_RETRY_DELAY_SECONDS)
        if response is None:
            raise ValueError(f"Moka {label} API did not return a response")
        with response:
            body = response.read(_MAX_HTML_BYTES + 1)
        if len(body) > _MAX_HTML_BYTES:
            raise ValueError(f"Moka {label} API response exceeds the safe response limit")
        try:
            response_json = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Moka {label} API did not return JSON") from exc
        return _decrypt_detail_response(response_json, aes_iv)

    def fetch_job_list(
        self,
        page_url: str,
        mode: str,
        org_id: str,
        site_id: str,
        locale: str,
        limit: int,
        offset: int,
        aes_iv: str | None,
    ) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "orgId": org_id,
            "siteId": int(site_id) if site_id.isdigit() else site_id,
            "limit": limit,
            "offset": offset,
            "needStat": True,
            "keyword": "",
            "site": "social" if mode == "social-recruitment" else "campus",
            "locale": locale,
        }
        if mode != "social-recruitment":
            payload["isCampusJob"] = True
        return self._fetch_encrypted_json(
            page_url,
            _LIST_PATH,
            payload,
            aes_iv,
            "list",
        )

    def fetch_job_detail(
        self,
        page_url: str,
        org_id: str,
        site_id: str,
        job_id: str,
        locale: str,
        aes_iv: str | None,
    ) -> Mapping[str, object]:
        payload = {
            "orgId": org_id,
            "siteId": int(site_id) if site_id.isdigit() else site_id,
            "jobId": job_id,
            "locale": locale,
        }
        return self._fetch_encrypted_json(
            page_url,
            _DETAIL_PATH,
            payload,
            aes_iv,
            "detail",
        )


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def _decrypt_detail_response(response: object, aes_iv: str | None) -> Mapping[str, object]:
    root = _mapping(response, "Moka detail API response is not an object")
    encrypted_data = root.get("data")
    key = root.get("necromancer")
    if not isinstance(encrypted_data, str) or not encrypted_data:
        raise ValueError("Moka detail API response has no encrypted data")
    if not isinstance(key, str) or not key:
        raise ValueError("Moka detail API response has no decryption key")
    if not isinstance(aes_iv, str) or not aes_iv:
        raise ValueError("Moka init-data has no AES IV")
    try:
        ciphertext = base64.b64decode(encrypted_data, validate=True)
        cipher = Cipher(
            algorithms.AES(key.encode("utf-8")),
            modes.CBC(aes_iv.encode("utf-8")),
        )
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        decoded = json.loads(plaintext.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ValueError("Moka detail API response could not be decrypted") from exc
    payload = _mapping(decoded, "Moka detail API decrypted payload is not an object")
    if payload.get("code") not in {0, 200}:
        raise ValueError(f"Moka detail API returned code {payload.get('code')!r}")
    return _mapping(payload.get("data"), "Moka detail API has no job data")


def _html_text(value: object) -> str | None:
    raw = _text(value)
    if raw is None:
        return None
    parser = _DescriptionParser()
    parser.feed(raw)
    parser.close()
    text = re.sub(r"[^\S\n]+", " ", "".join(parser.parts))
    text = re.sub(r" *\n+ *", "\n", text).strip()
    return text or None


def _detail_description(detail: Mapping[str, object]) -> str | None:
    return _html_text(detail.get("jobDescription") or detail.get("description"))


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
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_QUERY_KEYS
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))


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


def _non_negative_int(value: object, message: str) -> int:
    if isinstance(value, bool):
        raise ValueError(message)
    if not isinstance(value, (int, str)):
        raise ValueError(message)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if result < 0:
        raise ValueError(message)
    return result


def _list_items(response: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw_jobs = response.get("jobs")
    if not isinstance(raw_jobs, list):
        raise ValueError("Moka list API has no job list")
    jobs: list[Mapping[str, object]] = []
    for raw_job in raw_jobs:
        jobs.append(_mapping(raw_job, "Moka list API returned an invalid job"))
    return jobs


def _fetch_all_list_jobs(
    fetch_job_list: MokaJobListFetcher,
    page_url: str,
    mode: str,
    org_id: str,
    site_id: str,
    locale: str,
    aes_iv: str | None,
) -> tuple[list[object], int]:
    first_response = fetch_job_list(
        page_url,
        mode,
        org_id,
        site_id,
        locale,
        _LIST_PAGE_SIZE,
        0,
        aes_iv,
    )
    stats = _mapping(first_response.get("jobStats"), "Moka list API has no job statistics")
    total = _non_negative_int(stats.get("total"), "Moka list API has no valid job count")
    if total > _MAX_LIST_JOBS:
        raise ValueError("Moka list API exceeds the safe job limit")

    all_jobs: list[object] = []
    seen_ids: set[str] = set()
    for offset in range(0, total, _LIST_PAGE_SIZE):
        response = (
            first_response
            if offset == 0
            else fetch_job_list(
                page_url,
                mode,
                org_id,
                site_id,
                locale,
                _LIST_PAGE_SIZE,
                offset,
                aes_iv,
            )
        )
        page_jobs = _list_items(response)
        for job in page_jobs:
            job_id = _text(job.get("id"))
            if not job_id:
                raise ValueError("Moka list API returned a job without an id")
            if job_id in seen_ids:
                raise ValueError("Moka list API returned duplicate jobs")
            seen_ids.add(job_id)
            all_jobs.append(job)
    if len(all_jobs) != total:
        raise ValueError("Moka list API returned an incomplete job list")
    return all_jobs, total


def _normalise(
    job: Mapping[str, object],
    page_url: str,
    mode: str,
    org_id: str,
    site_id: str,
    list_count: int | None = None,
) -> dict[str, object]:
    source_job_id = _text(job.get("id"))
    title = _text(job.get("title"))
    if not source_job_id or not title:
        raise ValueError("Moka init-data job has no id or title")
    detail_url = _detail_url(page_url, source_job_id)
    description = _html_text(job.get("jobDescription") or job.get("description"))
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
    if list_count is not None:
        metadata["list_count"] = list_count
        metadata["list_api_route"] = _LIST_PATH
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
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


def _enrich_job_detail(
    job: dict[str, object],
    page_url: str,
    org_id: str,
    site_id: str,
    locale: str,
    fetch_job_detail: MokaDetailFetcher,
    populated_status: str = "init-data",
) -> None:
    metadata = job.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        job["metadata"] = metadata
    if job.get("description"):
        metadata["detail_status"] = populated_status
        return
    try:
        detail = fetch_job_detail(page_url, org_id, site_id, str(job["source_job_id"]), locale)
        description = _detail_description(detail)
    except Exception as exc:  # noqa: BLE001 - one unavailable detail must not drop the job
        metadata["detail_status"] = "failed"
        metadata["detail_error_type"] = type(exc).__name__
        return
    if description:
        job["description"] = description
        metadata["detail_status"] = "api"
    else:
        metadata["detail_status"] = "empty"


def parse(
    url: str,
    fetch_html: Callable[[str], str] | None = None,
    fetch_job_detail: MokaDetailFetcher | None = None,
) -> list[dict[str, object]]:
    """Parse Moka jobs and best-effort fetch their public detail descriptions."""
    session: MokaSession | None = None
    if fetch_html is None:
        session = MokaSession()
        page_url, page = session.fetch_page(url)
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
    initial_jobs = data.get("jobs")
    if not isinstance(initial_jobs, list):
        raise ValueError("Moka init-data has no job list")
    locale = _text(data.get("locale")) or _DEFAULT_LOCALE
    detail_fetcher = fetch_job_detail
    list_fetcher: MokaJobListFetcher | None = None
    aes_iv = _text(data.get("aesIv"))
    if detail_fetcher is None and session is not None:
        moka_session = session

        def load_job_detail(
            detail_page_url: str,
            detail_org_id: str,
            detail_site_id: str,
            detail_job_id: str,
            detail_locale: str,
        ) -> Mapping[str, object]:
            return moka_session.fetch_job_detail(
                detail_page_url,
                detail_org_id,
                detail_site_id,
                detail_job_id,
                detail_locale,
                aes_iv,
            )

        detail_fetcher = load_job_detail

    target_id = _target_job_id(url)
    raw_jobs: list[object] = initial_jobs
    list_count: int | None = None
    direct_from_api = False
    if session is not None:
        moka_session = session

        def load_job_list(
            list_page_url: str,
            list_mode: str,
            list_org_id: str,
            list_site_id: str,
            list_locale: str,
            list_limit: int,
            list_offset: int,
            list_aes_iv: str | None,
        ) -> Mapping[str, object]:
            return moka_session.fetch_job_list(
                list_page_url,
                list_mode,
                list_org_id,
                list_site_id,
                list_locale,
                list_limit,
                list_offset,
                list_aes_iv,
            )

        list_fetcher = load_job_list

    if target_id is not None and detail_fetcher is not None:
        raw_jobs = [
            detail_fetcher(page_url, org_id, site_id, target_id, locale),
        ]
        direct_from_api = session is not None
    elif target_id is None and list_fetcher is not None:
        raw_jobs, list_count = _fetch_all_list_jobs(
            list_fetcher,
            page_url,
            mode,
            org_id,
            site_id,
            locale,
            aes_iv,
        )

    jobs: list[dict[str, object]] = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, Mapping) or not _is_open(raw_job):
            continue
        if target_id is not None and _text(raw_job.get("id")) != target_id:
            continue
        normalized = _normalise(raw_job, page_url, mode, org_id, site_id, list_count)
        if direct_from_api:
            metadata = normalized["metadata"]
            if isinstance(metadata, dict):
                metadata["detail_status"] = "api"
        elif detail_fetcher is not None:
            _enrich_job_detail(
                normalized,
                page_url,
                org_id,
                site_id,
                locale,
                detail_fetcher,
                "list-api" if list_count is not None else "init-data",
            )
        jobs.append(normalized)
    if target_id is not None and not jobs:
        raise ValueError("Moka target job is closed or absent from public data")
    if not jobs:
        raise ValueError("Moka init-data contains no open jobs")
    return jobs


__all__ = ["MokaSession", "entry_identity", "parse", "source_identity"]
