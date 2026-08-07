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
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit
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
_DETAIL_PATH = "/api/outer/ats-apply/website/job"
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
        request = Request(
            f"{_origin(page_url)}{_DETAIL_PATH}",
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
        try:
            response = self._opener.open(request, timeout=20)
        except HTTPError as exc:
            raise ValueError(f"Moka detail API returned HTTP {exc.code}") from exc
        with response:
            body = response.read(_MAX_HTML_BYTES + 1)
        if len(body) > _MAX_HTML_BYTES:
            raise ValueError("Moka detail API response exceeds the safe response limit")
        try:
            response_json = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ValueError("Moka detail API did not return JSON") from exc
        return _decrypt_detail_response(response_json, aes_iv)


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
) -> None:
    metadata = job.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        job["metadata"] = metadata
    if job.get("description"):
        metadata["detail_status"] = "init-data"
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
    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, list):
        raise ValueError("Moka init-data has no job list")
    locale = _text(data.get("locale")) or _DEFAULT_LOCALE
    detail_fetcher = fetch_job_detail
    if detail_fetcher is None and session is not None:
        moka_session = session
        aes_iv = _text(data.get("aesIv"))

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
    jobs: list[dict[str, object]] = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, Mapping) or not _is_open(raw_job):
            continue
        if target_id is not None and _text(raw_job.get("id")) != target_id:
            continue
        normalized = _normalise(raw_job, page_url, mode, org_id, site_id)
        if detail_fetcher is not None:
            _enrich_job_detail(normalized, page_url, org_id, site_id, locale, detail_fetcher)
        jobs.append(normalized)
    if target_id is not None and not jobs:
        raise ValueError("Moka target job is closed or absent from init-data")
    if not jobs:
        raise ValueError("Moka init-data contains no open jobs")
    return jobs


__all__ = ["MokaSession", "entry_identity", "parse", "source_identity"]
