"""Small, evidence-first parser for public recruitment pages."""

from __future__ import annotations

import hashlib
import html as html_module
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_MAX_HTML_BYTES = 8 * 1024 * 1024
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_DESCRIPTION_CHARS = 80_000
_JOB_PATH_RE = re.compile(
    r"/(?:job|jobs|position|positions|vacancy|vacancies|opening|detail|recruitment/job)(?:/|$)",
    re.IGNORECASE,
)
_ID_KEYS = (
    "source_job_id",
    "jobId",
    "jobID",
    "positionId",
    "positionID",
    "postId",
    "postID",
    "jobNumber",
    "positionNumber",
    "requisitionId",
    "requisitionNumber",
    "id",
    "identifier",
)
_TITLE_KEYS = (
    "title",
    "jobTitle",
    "jobName",
    "positionName",
    "positionTitle",
    "postName",
    "name",
)
_DESCRIPTION_KEYS = (
    "description",
    "jobDescription",
    "jobDesc",
    "jobDetail",
    "detail",
    "responsibility",
    "responsibilities",
    "duty",
    "requirement",
    "requirements",
)
_DETAIL_KEYS = (
    "url",
    "detailUrl",
    "detailURL",
    "jobUrl",
    "jobURL",
    "positionUrl",
    "positionURL",
    "link",
    "href",
)
_LOCATION_KEYS = (
    "jobLocation",
    "locations",
    "location",
    "workLocation",
    "workCity",
    "city",
    "cityName",
    "place",
)
_JOB_SIGNAL_KEYS = {
    key.casefold()
    for key in (
        *_ID_KEYS,
        *_DESCRIPTION_KEYS,
        *_LOCATION_KEYS,
        "education",
        "educationRequirement",
        "employmentType",
        "salary",
        "salaryMin",
        "salaryMax",
        "department",
        "jobType",
        "positionType",
    )
}
_GENERIC_TITLES = {
    "首页",
    "home",
    "index",
    "job list",
    "jobs",
    "position list",
    "职位列表",
    "职位投递",
    "招聘官网",
    "校园招聘",
    "登录",
    "login",
    "诚聘英才",
}
_RECRUITMENT_MARKERS = (
    "招聘",
    "招募",
    "职位",
    "岗位",
    "校招",
    "社招",
    "实习",
    "recruit",
    "career",
    "position",
    "vacancy",
)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.scripts: list[tuple[str | None, str]] = []
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []
        self._title_depth = 0
        self._heading_depth = 0
        self._heading_buffer: list[str] = []
        self._script: tuple[str | None, str] | None = None
        self._script_buffer: list[str] = []
        self._anchor: tuple[str, list[str]] | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        if tag == "script":
            self._script = (attributes.get("type"), "")
            self._script_buffer = []
            return
        if self._script is not None:
            return
        if tag in {"style", "noscript", "template", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag in {"h1", "h2", "h3"}:
            self._heading_depth += 1
            self._heading_buffer = []
        if tag == "a":
            href = attributes.get("href")
            if href:
                self._anchor = (href, [])
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            value = attributes.get("content")
            if key and value:
                self.meta[key.casefold()] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            script_type = self._script[0]
            self.scripts.append((script_type, "".join(self._script_buffer)))
            self._script = None
            self._script_buffer = []
            return
        if self._script is not None:
            return
        if tag in {"style", "noscript", "template", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._title_depth = max(self._title_depth - 1, 0)
        if tag in {"h1", "h2", "h3"} and self._heading_depth:
            self._heading_depth -= 1
            value = _text(" ".join(self._heading_buffer))
            if value:
                self.heading_parts.append(value)
            self._heading_buffer = []
        if tag == "a" and self._anchor is not None:
            href, parts = self._anchor
            self.links.append((href, _text(" ".join(parts)) or ""))
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script_buffer.append(data)
            return
        if self._skip_depth:
            return
        if self._title_depth:
            self.title_parts.append(data)
        if self._heading_depth:
            self._heading_buffer.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)
        if data.strip():
            self.text_parts.append(data)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Encoding": "identity",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - public recruitment URL
        body = response.read(_MAX_HTML_BYTES + 1)
        if len(body) > _MAX_HTML_BYTES:
            raise ValueError("public recruitment page exceeds the safe response limit")
        return body.decode(response.headers.get_content_charset() or "utf-8", "replace")


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and "<" in value and ">" in value:
        parser = _TextParser()
        parser.feed(value)
        value = " ".join(parser.parts)
    result = " ".join(html_module.unescape(str(value)).split())
    return result or None


def _first(mapping: Mapping[str, object], keys: tuple[str, ...]) -> object | None:
    lower_keys = {key.casefold() for key in keys}
    for key, value in mapping.items():
        if key.casefold() in lower_keys and value not in (None, "", [], {}):
            return value
    return None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _locations(value: object) -> list[str]:
    locations: list[str] = []

    def add(item: object) -> None:
        if isinstance(item, Mapping):
            address = _mapping(item.get("address")) or item
            value = _first(address, ("name", "addressLocality", "addressRegion", "city"))
            if value is not None:
                add(value)
            return
        if isinstance(item, list):
            for child in item:
                add(child)
            return
        text = _text(item)
        if not text:
            return
        for part in re.split(r"[,，、|;；]+", text):
            part = part.strip()
            if part and part not in locations:
                locations.append(part)

    add(value)
    return locations


def _date(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("/", "-").replace("年", "-").replace("月", "-")
    normalized = normalized.replace("日", "")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=parsed.tzinfo or UTC)
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    text = _text(value)
    if not text:
        return None
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if not numbers:
        return None
    multiplier = 1000 if re.search(r"(?:K|千)", text, re.IGNORECASE) else 1
    return int(float(numbers[0]) * multiplier)


def _salary(value: object) -> tuple[int | None, int | None, int | None]:
    mapping = _mapping(value)
    if mapping is not None:
        nested = _mapping(mapping.get("value")) or mapping
        minimum = _first(nested, ("minValue", "min", "minimum", "salaryMin"))
        maximum = _first(nested, ("maxValue", "max", "maximum", "salaryMax"))
        months = _first(mapping, ("months", "salaryMonths"))
        return _integer(minimum), _integer(maximum), _integer(months)
    text = _text(value)
    if not text:
        return None, None, None
    numbers = [_integer(number) for number in re.findall(r"\d+(?:\.\d+)?", text)]
    numbers = [
        number * 1000 if re.search(r"K|千", text, re.IGNORECASE) else number
        for number in numbers
        if number is not None
    ]
    if len(numbers) >= 2:
        return numbers[0], numbers[1], None
    return (numbers[0], None, None) if numbers else (None, None, None)


def _url(value: object, page_url: str) -> str | None:
    text = _text(value)
    if not text:
        return None
    if text.startswith(("javascript:", "mailto:", "#")):
        return None
    result = urljoin(page_url, text)
    parts = urlsplit(result)
    return result if parts.scheme in {"http", "https"} and parts.netloc else None


def _recruitment_type(*values: object) -> str | None:
    text = " ".join(item for value in values if (item := _text(value)))
    if not text:
        return None
    if "实习" in text or "intern" in text.casefold():
        return "实习"
    if any(marker in text for marker in ("社会招聘", "社会招募", "社招")):
        return "社招"
    if any(marker in text for marker in ("校园招聘", "校园", "校招", "秋招", "春招")):
        return "校招"
    return None


def _json_values(page: str, scripts: list[tuple[str | None, str]]) -> list[object]:
    values: list[object] = []
    candidates: list[str] = (
        [page.strip()[:_MAX_JSON_BYTES]] if page.lstrip().startswith(("{", "[")) else []
    )
    for script_type, body in scripts:
        if len(body.encode("utf-8")) > _MAX_JSON_BYTES:
            continue
        stripped = body.strip()
        if script_type and script_type.casefold() in {"application/json", "application/ld+json"}:
            candidates.append(stripped)
        elif any(
            marker in stripped for marker in ("__INITIAL_DATA__", "__NEXT_DATA__", "initialData")
        ):
            positions = [
                position for position in (stripped.find("{"), stripped.find("[")) if position >= 0
            ]
            if positions:
                candidates.append(stripped[min(positions) :])
    for candidate in candidates:
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        values.append(value)
    return values


def _identifier(value: object) -> str | None:
    mapping = _mapping(value)
    if mapping is not None:
        value = _first(mapping, ("value", "id", "name"))
    return _text(value)


def _record_from_mapping(
    item: Mapping[str, object], page_url: str, *, json_ld: bool = False
) -> dict[str, object] | None:
    title = _text(_first(item, _TITLE_KEYS))
    if not title:
        return None
    if not json_ld and not any(key.casefold() in _JOB_SIGNAL_KEYS for key in item):
        return None
    description = _text(_first(item, _DESCRIPTION_KEYS))
    identifier = _identifier(_first(item, _ID_KEYS))
    detail_url = _url(_first(item, _DETAIL_KEYS), page_url)
    if json_ld:
        identifier = identifier or _identifier(item.get("identifier"))
        detail_url = detail_url or _url(item.get("url"), page_url)
        locations = _locations(item.get("jobLocation"))
        education = _text(item.get("educationRequirements"))
        salary_min, salary_max, salary_months = _salary(item.get("baseSalary"))
        apply_url = _url(item.get("applicationUrl"), page_url)
        published_at = _date(item.get("datePosted"))
        deadline_at = _date(item.get("validThrough"))
    else:
        locations = _locations(_first(item, _LOCATION_KEYS))
        education = _text(_first(item, ("education", "educationRequirement", "degree")))
        salary_min, salary_max, salary_months = _salary(_first(item, ("salary", "baseSalary")))
        salary_min = _integer(_first(item, ("salaryMin", "minSalary"))) or salary_min
        salary_max = _integer(_first(item, ("salaryMax", "maxSalary"))) or salary_max
        salary_months = _integer(_first(item, ("salaryMonths", "months"))) or salary_months
        apply_url = _url(_first(item, ("applyUrl", "applyURL", "applicationUrl")), page_url)
        published_at = _date(_first(item, ("publishedAt", "publishTime", "datePosted")))
        deadline_at = _date(_first(item, ("deadline", "deadlineAt", "validThrough")))
    if detail_url is None and identifier and not json_ld:
        candidate = item.get("id")
        if candidate is not None:
            detail_url = _url(str(candidate), page_url)
    return {
        "source_job_id": identifier,
        "title": title,
        "description": description,
        "locations": locations,
        "detail_url": detail_url,
        "apply_url": apply_url or detail_url,
        "recruitment_type": _recruitment_type(
            title, item.get("employmentType"), item.get("jobType"), item.get("positionType")
        ),
        "education_requirement": education,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_months": salary_months,
        "published_at": published_at,
        "deadline_at": deadline_at,
        "source_ref": detail_url or page_url,
        "metadata": {"parser": "public_web", "record_kind": "job"},
    }


def _walk(value: object) -> list[Mapping[str, object]]:
    found: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        found.append(value)
        for child in value.values():
            found.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk(child))
    return found


def _json_jobs(values: list[object], page_url: str) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for value in values:
        for item in _walk(value):
            types = item.get("@type")
            is_job_posting = types == "JobPosting" or (
                isinstance(types, list) and "JobPosting" in types
            )
            job = _record_from_mapping(item, page_url, json_ld=is_job_posting)
            if job is None:
                continue
            key = (
                job.get("source_job_id"),
                job.get("detail_url"),
                job.get("title"),
            )
            if key in seen:
                continue
            seen.add(key)
            jobs.append(job)
    return jobs


def _is_generic_title(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    return not normalized or normalized in {item.casefold() for item in _GENERIC_TITLES}


def _detail_id(url: str) -> str | None:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key in ("id", "jobId", "positionId", "postId", "job_id"):
        if query.get(key):
            return query[key]
    path_parts = [part for part in parts.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[-1].casefold() not in {"detail", "index"}:
        return path_parts[-1]
    return None


def _static_jobs(page: _PageParser, page_url: str) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    seen: set[str] = set()
    for href, anchor_text in page.links:
        detail_url = _url(href, page_url)
        if detail_url is None:
            continue
        path = urlsplit(detail_url).path
        if not _JOB_PATH_RE.search(path) or path.rstrip("/").split("/")[-1].casefold() in {
            "jobs",
            "positions",
            "list",
            "index",
            "home",
        }:
            continue
        title = _text(anchor_text)
        if not title or len(title) < 2 or _is_generic_title(title):
            continue
        if title.casefold() in {"详情", "查看", "申请", "立即投递", "apply", "more"}:
            continue
        if not re.search(
            r"(?:岗位|职位|招聘|实习|工程师|经理|分析师|设计师|开发|顾问|专员|助理|"
            r"teacher|engineer|manager|analyst|developer|designer|intern|consultant|specialist)",
            title,
            re.IGNORECASE,
        ):
            continue
        if detail_url in seen:
            continue
        seen.add(detail_url)
        source_job_id = _detail_id(detail_url)
        jobs.append(
            {
                "source_job_id": source_job_id,
                "title": title,
                "description": None,
                "locations": [],
                "detail_url": detail_url,
                "apply_url": detail_url,
                "recruitment_type": _recruitment_type(title, page.title_parts),
                "education_requirement": None,
                "salary_min": None,
                "salary_max": None,
                "salary_months": None,
                "published_at": None,
                "deadline_at": None,
                "source_ref": detail_url,
                "metadata": {"parser": "public_web", "record_kind": "job"},
            }
        )
    return jobs


def _aircas_jobs(page_html: str, page_url: str) -> list[dict[str, object]]:
    """Read the public server-rendered cards used by the AIRCAS portal."""
    if "viewPositionInfo" not in page_html:
        return []
    jobs: list[dict[str, object]] = []
    origin = urlunsplit((*urlsplit(page_url)[:2], "", "", ""))
    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", page_html, re.IGNORECASE | re.DOTALL):
        attributes, body = match.groups()
        if "box-title" not in attributes:
            continue
        identifier = re.search(r"viewPositionInfo\(&quot;([^&]+)&quot;", attributes)
        if identifier is None:
            continue
        title = _text(body)
        if not title:
            continue
        detail_url = f"{origin}/system/userInfo/positionInfo?id={identifier.group(1)}"
        jobs.append(
            {
                "source_job_id": identifier.group(1),
                "title": title,
                "description": None,
                "locations": [],
                "detail_url": detail_url,
                "apply_url": detail_url,
                "recruitment_type": _recruitment_type(title, page_html),
                "education_requirement": None,
                "salary_min": None,
                "salary_max": None,
                "salary_months": None,
                "published_at": None,
                "deadline_at": None,
                "source_ref": detail_url,
                "metadata": {"parser": "public_web", "record_kind": "job"},
            }
        )
    return jobs


def _page_title(page: _PageParser) -> str | None:
    return (
        page.heading_parts[0]
        if page.heading_parts
        else _text(page.meta.get("og:title")) or _text(" ".join(page.title_parts))
    )


def _body_text(page: _PageParser) -> str | None:
    text = _text("\n".join(page.text_parts))
    return text[:_MAX_DESCRIPTION_CHARS] if text else None


def _looks_like_detail(url: str) -> bool:
    path = urlsplit(url).path
    return bool(
        _JOB_PATH_RE.search(path)
        and path.rstrip("/").split("/")[-1].casefold()
        not in {
            "jobs",
            "positions",
            "list",
            "index",
            "home",
            "campus",
            "school",
            "intern",
            "recruit",
            "portal",
        }
    )


def _announcement(url: str, page: _PageParser) -> dict[str, object] | None:
    title = _page_title(page)
    body = _body_text(page)
    haystack = f"{title or ''}\n{body or ''}".casefold()
    if _is_generic_title(title) or not any(
        marker.casefold() in haystack for marker in _RECRUITMENT_MARKERS
    ):
        return None
    identifier = (
        "announcement:"
        + hashlib.sha256(urlunsplit((*urlsplit(url)[:4], "")).encode()).hexdigest()[:20]
    )
    return {
        "source_job_id": identifier,
        "title": title,
        "description": body,
        "locations": [],
        "detail_url": urlunsplit((*urlsplit(url)[:4], "")),
        "apply_url": None,
        "recruitment_type": _recruitment_type(title, body),
        "education_requirement": None,
        "salary_min": None,
        "salary_max": None,
        "salary_months": None,
        "published_at": None,
        "deadline_at": None,
        "source_ref": url,
        "metadata": {"parser": "public_web", "record_kind": "public_announcement"},
    }


def parse(
    url: str,
    fetch: Callable[[str], str] = fetch_html,
    *,
    allow_announcement: bool = False,
) -> list[dict[str, object]]:
    """Parse only public, verifiable job records from a page."""
    page_html = fetch(url)
    page = _PageParser()
    page.feed(page_html)
    jobs = _json_jobs(_json_values(page_html, page.scripts), url)
    if not jobs and (urlsplit(url).hostname or "").casefold() == "zhaopin.aircas.ac.cn":
        if urlsplit(url).path.rstrip("/").casefold() in {"", "/index"}:
            listing_url = urljoin(
                url,
                "/system/userInfo/positionSearchByCondition?pageIndex=1&queryKey=",
            )
            jobs = _aircas_jobs(fetch(listing_url), listing_url)
        else:
            jobs = _aircas_jobs(page_html, url)
    if not jobs:
        jobs = _static_jobs(page, url)
    if not jobs and _looks_like_detail(url):
        title = _page_title(page)
        if title and not _is_generic_title(title):
            detail_url = urlunsplit((*urlsplit(url)[:4], ""))
            jobs = [
                {
                    "source_job_id": _detail_id(url),
                    "title": title,
                    "description": _body_text(page),
                    "locations": [],
                    "detail_url": detail_url,
                    "apply_url": detail_url,
                    "recruitment_type": _recruitment_type(title, _body_text(page)),
                    "education_requirement": None,
                    "salary_min": None,
                    "salary_max": None,
                    "salary_months": None,
                    "published_at": None,
                    "deadline_at": None,
                    "source_ref": detail_url,
                    "metadata": {"parser": "public_web", "record_kind": "job"},
                }
            ]
    if not jobs and allow_announcement:
        announcement = _announcement(url, page)
        if announcement is not None:
            jobs = [announcement]
    return jobs


__all__ = ["fetch_html", "parse"]
