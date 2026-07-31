from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_API_ROOT = "https://gp-api.iguopin.com"
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_PAGES = 200
_MAX_JOBS = 5_000
_PAGE_SIZE = 200
_FAIR_PAGE_SIZE = 10
_TRANSIENT_MESSAGE = "当前访问人数过多"
_ACCESS_MARKERS = ("登录", "权限", "账号类型", "验证码", "访问人数过多")
_BLOCK_TAGS = frozenset({"br", "div", "li", "p", "section", "tr", "td"})

JsonFetcher = Callable[[str, Mapping[str, str], Mapping[str, object]], object]


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "template", "noscript"}:
            self._ignored_depth += 1
        if self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "template", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        if self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


class GuopinSession:
    """Small public-API client; it never carries browser login state."""

    def __init__(self, request_json: JsonFetcher | None = None) -> None:
        self._request_json_override = request_json

    def request_json(
        self,
        url: str,
        *,
        source_url: str,
        method: str = "GET",
        params: Mapping[str, object] | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        query = urlencode(
            [(key, value) for key, value in (params or {}).items() if value not in (None, "")],
            doseq=True,
        )
        request_url = urlunsplit((*urlsplit(url)[:3], query, "")) if query else url
        source_parts = urlsplit(source_url)
        origin = urlunsplit((source_parts.scheme, source_parts.netloc, "", "", ""))
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Device": "pc",
            "Origin": origin,
            "Referer": source_url,
            "Subsite": "iguopin",
            "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
            "Version": "5.2.300",
        }
        request_payload: Mapping[str, object] = payload or {}
        if method.upper() == "POST":
            headers = {**headers, "Content-Type": "application/json"}
        if self._request_json_override is not None:
            return self._request_json_override(request_url, headers, request_payload)

        body = (
            json.dumps(request_payload, ensure_ascii=False).encode()
            if method.upper() == "POST"
            else None
        )
        for attempt in range(2):
            request = Request(request_url, data=body, headers=headers, method=method.upper())
            try:
                with urlopen(request, timeout=25) as response:
                    raw = response.read(_MAX_JSON_BYTES + 1)
            except HTTPError as exc:
                raise ValueError(f"GUOPIN public API HTTP {exc.code}") from exc
            except URLError as exc:
                if attempt == 0:
                    time.sleep(0.15)
                    continue
                raise ValueError(f"GUOPIN public API request failed: {exc.reason}") from exc
            if len(raw) > _MAX_JSON_BYTES:
                raise ValueError("GUOPIN public API response exceeds the safe response limit")
            try:
                return json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError as exc:
                raise ValueError("GUOPIN public API did not return JSON") from exc
        raise ValueError("GUOPIN public API request failed")


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).replace("\u00a0", " ").split())
    return result or None


def _first(fields: Mapping[str, object], *names: str) -> object | None:
    for name in names:
        value = fields.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _number(value: object, *, positive: bool = False) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        candidate = str(value).replace(",", "").strip()
        if not re.fullmatch(r"\d+(?:\.0+)?", candidate):
            return None
        number = int(float(candidate))
    if number < 0 or (positive and number == 0):
        return None
    return number


def _date(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            parsed = datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = _text(value)
        if not text:
            return None
        normalized = text.replace("/", "-").replace("Z", "+00:00")
        parsed = None
        for candidate in (normalized, normalized.replace(" ", "T", 1)):
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            break
        if parsed is None:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(normalized, fmt)
                except ValueError:
                    continue
                break
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    if parsed is None:
        return None
    return parsed if 1900 <= parsed.year < 2200 else None


def _html_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(item) for item in value)
    raw = str(value)
    stripped = raw.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(decoded, str):
                raw = decoded
    parser = _TextParser()
    parser.feed(html.unescape(raw))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    result = "\n".join(line for line in lines if line)
    return result[:80_000] or None


def _locations(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, Mapping):
                item = _first(item, "area_cn", "city_cn", "district_cn", "name", "address")
            text = _text(item)
            if not text:
                continue
            for location in re.split(r"[,，、|;；]+", text):
                location = location.strip()
                if location and location not in result:
                    result.append(location)
    return result


def _recruitment_type(job: Mapping[str, object], source_url: str) -> str | None:
    values = [_text(_first(job, "nature_cn", "recruitment_type_cn", "recruitment_type")) or ""]
    values.append(_text(job.get("job_name")) or "")
    values.append(urlsplit(source_url).path.casefold())
    text = " ".join(values).casefold()
    if "实习" in text or "intern" in text:
        return "实习"
    if any(marker in text for marker in ("社会招聘", "社会招募", "社招", "social")):
        return "社招"
    if any(marker in text for marker in ("校园招聘", "校园", "校招", "秋招", "春招", "campus")):
        return "校招"
    return None


def _api_data(response: object) -> object:
    if not isinstance(response, Mapping):
        raise ValueError("GUOPIN public API response is not an object")
    code = response.get("code")
    if str(code) != "200":
        message = _text(response.get("msg") or response.get("message")) or "unknown error"
        if any(marker in message for marker in _ACCESS_MARKERS):
            raise ValueError(
                "GUOPIN public endpoint requires login or returned access-control response"
            )
        raise ValueError(f"GUOPIN public API returned code {code}: {message}")
    return response.get("data")


def _rows(data: object) -> tuple[list[Mapping[str, object]], int | None]:
    if isinstance(data, list):
        raw_rows: object = data
        total = None
    elif isinstance(data, Mapping):
        raw_rows = data.get("list")
        total = _number(data.get("total"))
    else:
        return [], None
    if not isinstance(raw_rows, list):
        return [], total
    return [row for row in raw_rows if isinstance(row, Mapping)], total


def _paginate(
    session: GuopinSession,
    source_url: str,
    endpoint: str,
    base_payload: Mapping[str, object],
    *,
    page_size: int,
    max_pages: int = _MAX_PAGES,
) -> list[Mapping[str, object]]:
    collected: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    total: int | None = None
    for page in range(1, max_pages + 1):
        payload = {**base_payload, "page": page, "page_size": page_size}
        data = _api_data(
            session.request_json(
                _API_ROOT + endpoint,
                source_url=source_url,
                method="POST",
                payload=payload,
            )
        )
        rows, page_total = _rows(data)
        if total is None:
            total = page_total
        if not rows:
            if total and not collected:
                raise ValueError("GUOPIN public API reported jobs but returned an empty page")
            break
        for row in rows:
            identifier = _text(_first(row, "job_id", "id"))
            if identifier is None or identifier in seen_ids:
                continue
            seen_ids.add(identifier)
            collected.append(row)
        if len(collected) >= _MAX_JOBS:
            raise ValueError("GUOPIN public job list exceeds the safe collection limit")
        if total is not None and len(collected) >= total:
            break
        if len(rows) < page_size:
            break
    else:
        raise ValueError("GUOPIN public job list exceeded the safe page limit")
    return collected


def _company_jobs(
    session: GuopinSession,
    source_url: str,
    company_id: str,
    *,
    project_id: str | None = None,
) -> tuple[list[Mapping[str, object]], str]:
    filters: dict[str, object] = {"company_id": [company_id]}
    if project_id:
        filters["project_id"] = project_id
    own = _paginate(session, source_url, "/api/jobs/v1/list", filters, page_size=_PAGE_SIZE)
    if own:
        return own, "jobs/v1/list:company"
    group_filters = {**filters, "company_id_with_sub": company_id}
    lower = _paginate(session, source_url, "/api/jobs/v1/list", group_filters, page_size=_PAGE_SIZE)
    return lower, "jobs/v1/list:company-with-sub"


def _job_detail_url(source_url: str, job_id: str, *, fair_id: str | None = None) -> str:
    if fair_id:
        return "https://zp.iguopin.com/job/detail?" + urlencode(
            {"id": job_id, "active": "jobfair", "active_id": fair_id}
        )
    host = (urlsplit(source_url).hostname or "").casefold()
    origin = "https://zp.iguopin.com" if host == "zp.iguopin.com" else "https://www.iguopin.com"
    return origin + "/job/detail?" + urlencode({"id": job_id})


def _normalise(
    job: Mapping[str, object],
    source_url: str,
    *,
    endpoint: str,
    fair_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, object]:
    source_job_id = _text(_first(job, "job_id", "id", "source_job_id"))
    title = _text(_first(job, "job_name", "title", "name"))
    if not source_job_id or not title:
        raise ValueError("GUOPIN public job has no id or title")
    detail_url = _job_detail_url(source_url, source_job_id, fair_id=fair_id)
    salary_min = _number(_first(job, "min_wage", "salary_min", "minSalary"))
    salary_max = _number(_first(job, "max_wage", "salary_max", "maxSalary"))
    if salary_min == 0:
        salary_min = None
    if salary_max == 0:
        salary_max = None
    metadata: dict[str, object] = {
        "platform": "GUOPIN",
        "record_kind": "job",
        "source_endpoint": endpoint,
    }
    for key, value in {
        "company_id": _text(job.get("company_id")),
        "company_name": _text(job.get("company_name")),
        "nature_cn": _text(job.get("nature_cn")),
        "recruitment_type_cn": _text(job.get("recruitment_type_cn")),
        "status": _text(job.get("status")),
        "index": _text(job.get("index")),
        "wage_unit_cn": _text(job.get("wage_unit_cn")),
        "project_id": project_id,
    }.items():
        if value is not None:
            metadata[key] = value
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": _html_text(_first(job, "contents", "description", "job_description")),
        "locations": _locations(
            job.get("district_list"),
            _first(job, "location", "locations", "work_location", "city_cn"),
        ),
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(job, source_url),
        "education_requirement": _text(_first(job, "education_cn", "education")),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_months": _number(job.get("months"), positive=True),
        "published_at": _date(
            _first(job, "create_time", "start_time", "refresh_time", "update_time")
        ),
        "deadline_at": _date(job.get("end_time")),
        "source_ref": detail_url,
        "metadata": metadata,
    }


def _normalise_rows(
    rows: list[Mapping[str, object]],
    source_url: str,
    *,
    endpoint: str,
    fair_id: str | None = None,
    project_id: str | None = None,
) -> list[dict[str, object]]:
    if not rows:
        raise ValueError("GUOPIN public job list is empty")
    jobs: list[dict[str, object]] = []
    for row in rows:
        try:
            jobs.append(
                _normalise(
                    row,
                    source_url,
                    endpoint=endpoint,
                    fair_id=fair_id,
                    project_id=project_id,
                )
            )
        except ValueError:
            continue
    if not jobs:
        raise ValueError("GUOPIN public job list contains no usable jobs")
    return jobs


def _query(url: str, name: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(name)
    return values[0].strip() if values and values[0].strip() else None


def _custom_site_config(
    session: GuopinSession,
    source_url: str,
    domain: str,
) -> Mapping[str, object]:
    data = _api_data(
        session.request_json(
            _API_ROOT + "/api/activity/exclusive/v1/info",
            source_url=source_url,
            params={"domain": domain},
        )
    )
    if not isinstance(data, Mapping):
        raise ValueError("GUOPIN custom site has no public configuration")
    return data


def parse(
    url: str,
    request_json: JsonFetcher | None = None,
) -> list[dict[str, object]]:
    """Parse public GUOPIN job details, company pages, and recruitment pages."""
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    path = parts.path.rstrip("/") or "/"
    session = GuopinSession(request_json)

    if host == "zp.iguopin.com" and path.casefold() == "/detail/companydetail":
        fair_id = _query(url, "id")
        company_id = _query(url, "companyId")
        if not fair_id or not company_id:
            raise ValueError("GUOPIN job-fair page has no public company or fair id")
        rows = _paginate(
            session,
            url,
            "/api/activity/jobfair/company/v1/jobs-list",
            {"company_id": company_id, "jobfair_id": fair_id, "search_type": 2},
            page_size=_FAIR_PAGE_SIZE,
        )
        return _normalise_rows(
            rows,
            url,
            endpoint="activity/jobfair/company/v1/jobs-list",
            fair_id=fair_id,
        )

    if path.casefold() == "/job/detail" and _query(url, "id"):
        job_id = _query(url, "id")
        assert job_id is not None
        data = _api_data(
            session.request_json(
                _API_ROOT + "/api/jobs/v1/info",
                source_url=url,
                params={"id": job_id},
            )
        )
        if not isinstance(data, Mapping):
            raise ValueError("GUOPIN public job detail is empty")
        return _normalise_rows([data], url, endpoint="jobs/v1/info")

    if path.casefold() == "/job/list":
        keyword = _query(url, "keyword")
        filters: dict[str, object] = {}
        if keyword:
            filters["keyword"] = keyword
        rows = _paginate(session, url, "/api/jobs/v1/list", filters, page_size=_PAGE_SIZE)
        if not rows and keyword:
            rows = _paginate(
                session,
                url,
                "/api/jobs/v1/list",
                {**filters, "with_offline": True},
                page_size=_PAGE_SIZE,
            )
        return _normalise_rows(rows, url, endpoint="jobs/v1/list:keyword")

    is_company_page = host == "www.iguopin.com" and path.casefold() in {
        "/company/jobs",
        "/company",
    }
    company_id = _query(url, "id") or _query(url, "companyId")
    is_custom_site = host.endswith(".iguopin.com") and host not in {
        "www.iguopin.com",
        "zp.iguopin.com",
    }
    if is_company_page and not company_id:
        raise ValueError("GUOPIN company page has no public company id")
    if is_company_page and company_id:
        rows, endpoint = _company_jobs(session, url, company_id)
        return _normalise_rows(rows, url, endpoint=endpoint)

    if is_custom_site:
        domain = host.split(".", 1)[0]
        config = _custom_site_config(session, url, domain)
        configured_company_id = _text(config.get("company_id"))
        project_id = _text(config.get("project_id"))
        if not configured_company_id:
            raise ValueError("GUOPIN custom site has no public company id")
        rows, endpoint = _company_jobs(
            session,
            url,
            configured_company_id,
            project_id=project_id,
        )
        return _normalise_rows(rows, url, endpoint=endpoint, project_id=project_id)

    raise ValueError("GUOPIN URL has no supported public job route")


__all__ = ["GuopinSession", "parse"]
