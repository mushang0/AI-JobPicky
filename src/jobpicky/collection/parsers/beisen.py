from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from gzip import decompress as gzip_decompress
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_TITLE_KEYS = ("jobAdName", "JobAdName", "jobName", "title", "name")
_ID_KEYS = ("jobAdId", "JobAdId", "jobId", "positionId", "id")
_DESCRIPTION_KEYS = (
    "description",
    "duty",
    "Duty",
    "jobDescription",
    "content",
    "responsibility",
)
_DETAIL_KEYS = (
    "detailUrl",
    "jobAdUrl",
    "JobAdUrl",
    "JobAdNameLinkUrl",
    "PostExternalLink",
    "jobUrl",
    "url",
    "link",
    "href",
)
_APPLY_KEYS = ("applyUrl", "applicationUrl", "applyLink")
_LOCATION_KEYS = (
    "locations",
    "location",
    "workLocation",
    "detailAddress",
    "cityName",
    "LocNames",
    "LocName",
    "LocIdName",
)
_DESKTOP_DISPLAY_FIELDS = [
    "Category",
    "Kind",
    "LocId",
    "DetailAddress",
    "Org",
    "HeadCount",
    "Station",
    "EndTime",
    "PostDate",
    "Salary",
    "Degree",
    "YearsOfWorking",
    "ClassificationOne",
    "ClassificationTwo",
]


def _request(url: str, data: object | None = None) -> str:
    headers = {
        "Accept": "application/json, text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
    }
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    request = Request(
        url,
        data=body,
        headers=headers,
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - URL is an input source, not a redirect target
        body = response.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip_decompress(body)
        return body.decode(response.headers.get_content_charset() or "utf-8", "replace")


def fetch_html(url: str) -> str:
    return _request(url)


def post_json(url: str, data: object) -> str:
    return _request(url, data)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and "<" in value:
        parser = _TextParser()
        parser.feed(value)
        value = " ".join(parser.parts)
    result = " ".join(str(value).split())
    return result or None


def _first(item: dict[str, object], keys: tuple[str, ...]) -> object:
    for key in keys:
        if item.get(key) not in (None, "", [], {}):
            return item[key]
    return None


def _locations(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in (_text(part) for part in value) if item]
    text = _text(value)
    return [part.strip() for part in re.split(r"[,，、|]", text or "") if part.strip()]


def _salary(value: object) -> tuple[int | None, int | None, int | None]:
    if isinstance(value, dict):
        minimum = value.get("min") or value.get("salaryMin")
        maximum = value.get("max") or value.get("salaryMax")
        months = value.get("months") or value.get("salaryMonths")
        return _number(minimum), _number(maximum), _number(months)
    text = _text(value)
    if not text:
        return None, None, None
    numbers = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", text)]
    multiplier = 1000 if re.search(r"K|千", text, re.IGNORECASE) else 1
    numbers = [number * multiplier for number in numbers]
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1]), None
    return (int(numbers[0]), None, None) if numbers else (None, None, None)


def _number(value: object) -> int | None:
    try:
        return int(float(str(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


def _date(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    match = re.fullmatch(r"/Date\((\d+)(?:[+-]\d+)?\)/", text)
    if match:
        value = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC)
        return value if value.year < 2200 else None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            value = datetime.strptime(text, fmt).replace(tzinfo=UTC)
            return value if 1900 <= value.year < 2200 else None
        except ValueError:
            continue
    return None


def _normalise(item: dict[str, object], page_url: str) -> dict[str, object]:
    detail_url = _text(_first(item, _DETAIL_KEYS))
    apply_url = _text(_first(item, _APPLY_KEYS))
    salary_min, salary_max, salary_months = _salary(item.get("salary") or item.get("SalaryName"))
    salary_min = _number(item.get("salaryMin")) or salary_min
    salary_max = _number(item.get("salaryMax")) or salary_max
    salary_months = _number(item.get("salaryMonths")) or salary_months
    return {
        "source_job_id": _text(_first(item, _ID_KEYS)),
        "title": _text(_first(item, _TITLE_KEYS)),
        "description": _text(_first(item, _DESCRIPTION_KEYS)),
        "detail_url": urljoin(page_url, detail_url) if detail_url else None,
        "apply_url": urljoin(page_url, apply_url) if apply_url else None,
        "locations": _locations(_first(item, _LOCATION_KEYS)),
        "recruitment_type": _text(
            item.get("recruitmentType")
            or item.get("kind")
            or item.get("KindName")
            or item.get("Category")
        ),
        "education_requirement": _text(
            item.get("educationRequirement") or item.get("education") or item.get("DegreeStr")
        ),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_months": salary_months,
        "published_at": _date(
            item.get("published_at")
            or item.get("ToPostDate")
            or item.get("PostDate")
            or item.get("PostDateStr")
        ),
        "deadline_at": _date(
            item.get("deadline_at")
            or item.get("ToEndDate")
            or item.get("EndTime")
            or item.get("EndTimeStr")
        ),
        "company_name": _text(item.get("companyName") or item.get("tenantName")),
    }


def _mobile_json(text: str) -> object:
    raw = text.encode("latin1") if text.startswith("\x1f") else text.encode()
    if raw[:2] == b"\x1f\x8b":
        text = gzip_decompress(raw).decode("utf-8", "replace")
    return json.loads(text)


def _mobile_endpoint(url: str, path: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(params), ""))


def _mobile_detail_url(
    page_url: str, source_job_id: str, query: dict[str, str], item: dict[str, object]
) -> str | None:
    supplied_url = _text(_first(item, _DETAIL_KEYS))
    if supplied_url:
        return urljoin(page_url, supplied_url)

    parts = urlsplit(page_url)
    if parts.path.lower().endswith(("job.html", "joblist.html")):
        legacy_query = urlencode(
            {
                "adId": source_job_id,
                "jc": query["jc"],
                "c1": query["c1"],
                "c2": query["c2"],
                "ky": query["ky"],
            }
        )
        return urljoin(page_url, f"jobxq.html?{legacy_query}")

    if parts.scheme and parts.netloc:
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        detail_query = urlencode({"id": source_job_id, "jc": query["jc"], "isReward": "false"})
        return f"{origin}/#/jobdetail?{detail_query}"
    return None


def _parse_mobile(url: str, fetch: Callable[[str], str]) -> list[dict[str, object]]:
    parts = urlsplit(url)
    fragment_query = parts.fragment.split("?", 1)[1] if "?" in parts.fragment else ""
    query = dict(parse_qsl(parts.query or fragment_query, keep_blank_values=True))
    # Some imported links contain a mangled paging parameter in the keyword
    # value (for example ``ky=π=1``). It makes an otherwise valid filtered
    # listing return no rows.
    if "=" in query.get("ky", ""):
        query["ky"] = ""
    query.setdefault("pi", "1")
    query.setdefault("ps", "1000")
    query.setdefault("jc", "2")
    query.setdefault("c1", "")
    query.setdefault("c2", "-1")
    query.setdefault("ky", "")
    query.setdefault("c", "")
    listing_url = _mobile_endpoint(url, "/JobAd/_SearchJobAd", query)
    listing = _mobile_json(fetch(listing_url))
    items = listing.get("DataResult", []) if isinstance(listing, dict) else []
    if not isinstance(items, list):
        return []

    results: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_job_id = _text(_first(item, _ID_KEYS))
        if not source_job_id:
            continue
        detail = _mobile_json(fetch(_mobile_endpoint(url, "/JobAd/_Info", {"adid": source_job_id})))
        combined = dict(item)
        if isinstance(detail, dict):
            combined.update(detail)
        job = _normalise(combined, url)
        require = _text(combined.get("Require") or combined.get("RequireStr"))
        if require:
            description = _text(job.get("description"))
            job["description"] = f"{description}\n{require}" if description else require
        job["detail_url"] = _mobile_detail_url(url, source_job_id, query, combined)
        # The detail page already contains the apply action. The legacy endpoint
        # redirects to login and is not a useful job-level URL.
        job["apply_url"] = None
        results.append(job)
    return results


def _json_objects(value: object, page_url: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if _first(node, _TITLE_KEYS) is not None:
                found.append(_normalise(node, page_url))
                return
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return found


def _embedded_json(html: str, page_url: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for match in re.finditer(r"<script\b[^>]*>(.*?)</script>", html, re.IGNORECASE | re.DOTALL):
        body = match.group(1).strip()
        if not body:
            continue
        if not body.startswith(("{", "[")):
            positions = [position for position in (body.find("{"), body.find("[")) if position >= 0]
            start = min(positions) if positions else -1
            body = body[start:].rstrip("; ") if start >= 0 else ""
        if not body:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(body)
            results.extend(_json_objects(value, page_url))
        except json.JSONDecodeError:
            continue
    return results


def _static_html(html: str, page_url: str) -> list[dict[str, object]]:
    # Deliberately small fallback for server-rendered job cards; modern portals
    # normally expose the same fields in embedded JSON or a client-side API.
    matches = re.finditer(
        r"<(?:article|li|div)[^>]+class=[\"'][^\"']*(?:job|position)[^\"']*[\"'][^>]*>(.*?)</(?:article|li|div)>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    results: list[dict[str, object]] = []
    for match in matches:
        fragment = match.group(1)
        title_match = re.search(r"<h[1-6]|<a\b", fragment, re.IGNORECASE)
        if not title_match:
            continue
        parser = _TextParser()
        parser.feed(fragment)
        title = " ".join(" ".join(parser.parts).split())
        if not title:
            continue
        link_match = re.search(r"<a\b[^>]+href=[\"']([^\"']+)", fragment, re.IGNORECASE)
        results.append(
            {
                "source_job_id": None,
                "title": title,
                "description": title,
                "detail_url": urljoin(page_url, link_match.group(1)) if link_match else None,
                "apply_url": None,
                "locations": [],
                "recruitment_type": None,
                "education_requirement": None,
                "salary_min": None,
                "salary_max": None,
                "salary_months": None,
                "company_name": None,
            }
        )
    return results


def _portal_id(html: str) -> str | None:
    for match in re.finditer(r"<script\b[^>]*>(.*?)</script>", html, re.IGNORECASE | re.DOTALL):
        body = match.group(1)
        marker = re.search(r"\bBSGlobal\s*=\s*", body)
        if not marker:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(body[marker.end() :].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            portal_id = value.get("PortalId")
            if portal_id:
                return str(portal_id)
    return None


def _desktop_category(url: str) -> list[str]:
    parts = [part.lower() for part in urlsplit(url).path.split("/") if part]
    categories = {"social": "1", "campus": "2", "intern": "3"}
    return [categories[part] for part in parts if part in categories][:1]


def _desktop_detail_url(page_url: str, source_job_id: str) -> str:
    parts = urlsplit(page_url)
    business = next(
        (part for part in parts.path.split("/") if part.lower() in {"social", "campus", "intern"}),
        "jobs",
    )
    origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    return f"{origin}/{business}/detail?{urlencode({'jobAdId': source_job_id})}"


def _desktop_fallback_url(url: str) -> str | None:
    parts = urlsplit(url)
    path = parts.path.lower()
    if path.rstrip("/").split("/")[-1] in {"jobs", "detail"}:
        return None
    if "social" in path:
        category = "social"
    elif "intern" in path or "shixi" in path:
        category = "intern"
    else:
        category = "campus"
    return urlunsplit((parts.scheme, parts.netloc, f"/{category}/jobs", "", ""))


def _parse_desktop(
    url: str,
    html: str,
    post: Callable[[str, object], str],
) -> list[dict[str, object]]:
    portal_id = _portal_id(html)
    if not portal_id:
        return []
    parts = urlsplit(url)
    api_url = urlunsplit((parts.scheme, parts.netloc, "/api/Jobad/GetJobAdPageList", "", ""))
    payload = {
        "Category": _desktop_category(url),
        "PageIndex": 0,
        "PageSize": 1000,
        "KeyWords": "",
        "SpecialType": 0,
        "PortalId": portal_id,
        "DisplayFields": _DESKTOP_DISPLAY_FIELDS,
    }
    try:
        response = _mobile_json(post(api_url, payload))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    items = response.get("Data", []) if isinstance(response, dict) else []
    if not isinstance(items, list):
        return []

    wanted_id = dict(parse_qsl(parts.query, keep_blank_values=True)).get("jobAdId")
    results: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_job_id = _text(item.get("Id") or _first(item, _ID_KEYS))
        if wanted_id and wanted_id not in {str(item.get("Id")), str(item.get("JobAdId"))}:
            continue
        if not source_job_id:
            continue
        job = _normalise(item, url)
        job["source_job_id"] = source_job_id
        job["description"] = _text(item.get("Duty"))
        require = _text(item.get("Require"))
        if require:
            description = _text(job.get("description"))
            job["description"] = f"{description}\n{require}" if description else require
        job["detail_url"] = _desktop_detail_url(url, source_job_id)
        job["apply_url"] = None
        results.append(job)
    return results


def parse(
    url: str,
    fetch: Callable[[str], str] | None = None,
    post: Callable[[str, object], str] | None = None,
) -> list[dict[str, object]]:
    fetcher = fetch or fetch_html
    parts = urlsplit(url)
    if ".m.zhiye.com" in (parts.hostname or ""):
        return _parse_mobile(url, fetcher)
    html = fetcher(url)
    if parts.path.lower().split("/")[-1] in {"jobs", "detail"}:
        desktop_jobs = _parse_desktop(url, html, post or post_json)
        if desktop_jobs:
            return desktop_jobs
    fallback_url = _desktop_fallback_url(url)
    if fallback_url:
        fallback_html = fetcher(fallback_url)
        fallback_jobs = _parse_desktop(fallback_url, fallback_html, post or post_json)
        if fallback_jobs:
            return fallback_jobs
        fallback_jobs = _embedded_json(fallback_html, fallback_url) or _static_html(
            fallback_html, fallback_url
        )
        if fallback_jobs:
            return fallback_jobs
    return _embedded_json(html, url) or _static_html(html, url)


__all__ = ["fetch_html", "parse"]
