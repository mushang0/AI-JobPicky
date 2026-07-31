from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_GRACE_API = "https://fe.zhaopin.com/grace/api/dsc/search-job-list"
_ZHAOKAO_API = "https://zkapi.zhaopin.com/zhaokao/api/"
_MAX_HTML_BYTES = 4 * 1024 * 1024
_MAX_SCRIPT_BYTES = 1 * 1024 * 1024
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_DESCRIPTION_CHARS = 80_000
_MAX_PAGES = 200
_PAGE_SIZE = 100
_GRACE_CONFIG_RE = re.compile(r"globalData(?:\$[12])?\s*=\s*\{", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<(?:script|link)[^>]+(?:src|href)=[\"']([^\"']+\.js[^\"']*)", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_CLOSED_STATUS = frozenset({"closed", "offline", "disabled", "deleted"})

PageFetcher = Callable[[str], tuple[str, str]]
JsonFetcher = Callable[[str, Mapping[str, str], Mapping[str, object]], object]


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {"address", "article", "br", "div", "li", "p", "section", "tr", "h1", "h2", "h3"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
        if tag in self._BLOCK_TAGS and self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in self._BLOCK_TAGS and self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


@dataclass(frozen=True)
class _GraceConfig:
    company_id: str
    company_number: str
    xiaozhao_id: str
    scene: str
    fallback_ids: tuple[str, ...] = ()


class ZhaopinSession:
    def fetch_page(self, url: str) -> tuple[str, str]:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
            },
        )
        with urlopen(request, timeout=20) as response:  # noqa: S310 - public recruitment URL
            body = response.read(_MAX_HTML_BYTES + 1)
            if len(body) > _MAX_HTML_BYTES:
                raise ValueError("Zhaopin page exceeds the safe response limit")
            return response.url, body.decode(
                response.headers.get_content_charset() or "utf-8", "replace"
            )

    def request_json(
        self, url: str, headers: Mapping[str, str], payload: Mapping[str, object]
    ) -> object:
        request_headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
            **headers,
        }
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        with urlopen(request, timeout=20) as response:  # noqa: S310 - public API
            body = response.read(_MAX_JSON_BYTES + 1)
            if len(body) > _MAX_JSON_BYTES:
                raise ValueError("Zhaopin API response exceeds the safe response limit")
        try:
            return json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ValueError("Zhaopin API did not return JSON") from exc


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())
    return result or None


def _html_text(value: object) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    if "<" not in raw or ">" not in raw:
        return raw
    parser = _TextExtractor()
    parser.feed(raw)
    lines = [" ".join(part.split()) for part in "".join(parser.parts).splitlines()]
    result = "\n".join(line for line in lines if line)
    return result or None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _first(mapping: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _valid_url(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return text


def _date(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            parsed = datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
        return parsed if 2000 <= parsed.year < 2200 else None
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("/", "-").replace("年", "-").replace("月", "-")
    normalized = normalized.replace("日", "")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=parsed.tzinfo or UTC)
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _locations(*values: object) -> list[str]:
    locations: list[str] = []
    for value in values:
        text = _text(value)
        if not text:
            continue
        for item in re.split(r"[|,，;；]+", text):
            item = item.strip()
            if item and item not in locations:
                locations.append(item)
    return locations


def _recruitment_type(text: str, scene: str | None = None) -> str | None:
    if "实习" in text:
        return "实习"
    if any(marker in text for marker in ("社会招聘", "社会招募", "社招")):
        return "社招"
    if any(marker in text for marker in ("校园招聘", "校园", "校招", "秋招", "春招")):
        return "校招"
    return "校招" if scene == "cam" else None


def _description(value: object) -> str | None:
    result = _html_text(value)
    return result[:_MAX_DESCRIPTION_CHARS] if result else None


def _detail_url(source_url: str, job_id: str, candidate: object = None) -> str:
    return _valid_url(candidate) or f"https://xiaoyuan.zhaopin.com/job/{job_id}"


def _job_record(
    raw: Mapping[str, object],
    source_url: str,
    *,
    source_page: str,
    scene: str | None = None,
    site_name: str | None = None,
) -> dict[str, object]:
    nested_data = _mapping(raw.get("jobDetailData"))
    nested_position = _mapping(nested_data.get("position")) if nested_data else None
    nested_base = _mapping(nested_position.get("base")) if nested_position else None
    nested_date = _mapping(nested_position.get("date")) if nested_position else None
    nested_location = _mapping(nested_position.get("workLocation")) if nested_position else None
    nested_job_type = _mapping(nested_position.get("jobType")) if nested_position else None

    source_job_id = _text(
        _first(
            raw,
            "positionNumber",
            "number",
            "jobNumber",
            "id",
        )
        or _first(nested_base or {}, "positionNumber", "jobNumber", "id")
    )
    title = _text(
        _first(raw, "positionName", "name", "jobName", "title")
        or _first(nested_base or {}, "positionName", "name", "title")
    )
    if not source_job_id or not title:
        raise ValueError("Zhaopin public job has no id or title")

    nested_desc = _mapping(nested_position.get("desc")) if nested_position else None
    description = _description(
        _first(
            raw,
            "jobDesc",
            "jobDescHighlight",
            "jobSummary",
            "detail",
            "jobDescription",
        )
        or _first(nested_desc or {}, "description", "descriptionHighlight")
    )
    if description is None and nested_desc:
        description = _description(_first(nested_desc or {}, "description", "descriptionHighlight"))

    city = _first(raw, "positionWorkCity", "workCity", "cityName", "prvCityArea")
    address = _first(raw, "workAddress", "address")
    if nested_location:
        city = city or _first(nested_location, "positionWorkCity", "cityName")
        address = address or _first(nested_location, "workAddress", "address")
    detail_url = _detail_url(
        source_url,
        source_job_id,
        _first(raw, "positionURL", "positionUrl", "url")
        or _first(nested_base or {}, "positionUrl", "positionURL", "url"),
    )
    apply_url = _valid_url(
        _first(raw, "deliveryPath", "applyUrl", "applyURL")
        or _first(nested_base or {}, "deliveryPath", "applyUrl")
    )
    education = _text(_first(raw, "education", "eduRecord", "minEducationName"))
    education = education or _text(_first(nested_base or {}, "education", "minEducationName"))
    work_type = _text(_first(raw, "workType", "jobGroupName", "jobLevel"))
    work_type = work_type or _text(_first(nested_base or {}, "workType"))
    type_hint = " ".join(
        item for item in (title, work_type, _text(_first(raw, "jobTypeName")), site_name) if item
    )
    published = _date(
        _first(raw, "positionPublishTime", "firstPublishTime", "publishTime", "jobPostingTime")
        or _first(nested_date or {}, "positionPublishTime", "firstPublishTime")
    )
    deadline = _date(_first(raw, "dateEnd", "applyEndTime") or _first(nested_date or {}, "dateEnd"))
    salary_min = _integer(_first(raw, "minSalary") or _first(nested_base or {}, "minSalary"))
    salary_max = _integer(_first(raw, "maxSalary") or _first(nested_base or {}, "maxSalary"))
    company = _mapping(raw.get("company"))
    metadata: dict[str, object] = {
        "platform": "ZHAOPIN",
        "source_page": source_page,
    }
    for key, value in {
        "company_number": _first(raw, "companyNumber") or _first(company or {}, "companyNumber"),
        "company_name": _first(raw, "companyName") or _first(company or {}, "campusOrgName"),
        "job_type": _first(raw, "jobTypeName") or _first(nested_job_type or {}, "jobTypeLevelName"),
        "position_status": _first(raw, "positionStatus", "status"),
        "site_name": site_name,
    }.items():
        if value not in (None, "", [], {}):
            metadata[key] = value
    return {
        "source_job_id": source_job_id,
        "title": title,
        "description": description,
        "locations": _locations(city, address),
        "detail_url": detail_url,
        "apply_url": apply_url or detail_url,
        "recruitment_type": _recruitment_type(type_hint, scene),
        "education_requirement": education,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "published_at": published,
        "deadline_at": deadline,
        "source_ref": detail_url,
        "metadata": metadata,
    }


def _load_initial_data(page: str) -> Mapping[str, object]:
    raw = _assigned_object(
        page, "window.__INITIAL_DATA__", "Zhaopin page has no public initial data"
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Zhaopin initial data is not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Zhaopin initial data is not an object")
    return data


def _load_position_data(page: str) -> Mapping[str, object]:
    raw = _assigned_object(
        page, "window.$positionData", "Zhaopin mobile page has no public position data"
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Zhaopin mobile position data is not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Zhaopin mobile position data is not an object")
    return data


def _assigned_object(page: str, marker: str, missing_message: str) -> str:
    marker_start = page.find(marker)
    if marker_start < 0:
        raise ValueError(missing_message)
    start = page.find("{", marker_start + len(marker))
    if start < 0:
        raise ValueError(missing_message)
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(page)):
        character = page[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return page[start : index + 1]
    raise ValueError(missing_message)


def _parse_mobile_position(page_url: str, page: str) -> list[dict[str, object]]:
    data = _load_position_data(page)
    position = _mapping(data.get("position")) or data
    return [_job_record(position, page_url, source_page="xiaoyuan_mobile_detail")]


def _parse_initial_page(url: str, page_url: str, page: str) -> list[dict[str, object]]:
    data = _load_initial_data(page)
    main = _mapping(data.get("main")) or {}
    position = _mapping(main.get("positionDetail"))
    if position:
        if _text(_first(position, "positionNumber", "positionName")):
            return [_job_record(position, page_url, source_page="xiaoyuan_detail")]
        if main.get("positionError") is True:
            raise ValueError("Zhaopin position is unavailable")

    company = _mapping(data.get("company")) or {}
    state = _mapping(company.get("recruitingPositionsState")) or {}
    raw_jobs: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    for key in ("list", "hotPositionsList", "positionList"):
        values = state.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            item = _mapping(value)
            item_id = _text(_first(item or {}, "positionNumber", "number", "jobNumber", "id"))
            if item is not None and item_id and item_id not in seen_ids:
                raw_jobs.append(item)
                seen_ids.add(item_id)
    if raw_jobs:
        return [_job_record(item, page_url, source_page="xiaoyuan_company") for item in raw_jobs]
    if _integer(state.get("count")):
        raise ValueError("Zhaopin company page has jobs but no public job records")
    raise ValueError("Zhaopin page has no public open jobs")


def _field_from_config(chunk: str, key: str) -> str:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*[\"']([^\"']*)[\"']", chunk)
    return match.group(1) if match else ""


def _discover_grace_config(
    page_url: str,
    page: str,
    fetch_page: PageFetcher,
) -> _GraceConfig | None:
    texts = [page]
    urls: list[str] = []
    for reference in _SCRIPT_RE.findall(page):
        script_url = urljoin(page_url, reference)
        hostname = urlsplit(script_url).hostname or ""
        if hostname.endswith(("zhaopin.com", "zhaopin.cn")) and script_url not in urls:
            urls.append(script_url)
    for script_url in urls[:12]:
        try:
            _, script = fetch_page(script_url)
        except Exception:  # noqa: BLE001 - another public bundle may contain the config
            continue
        texts.append(script[:_MAX_SCRIPT_BYTES])
    fallback_ids: list[str] = []
    for text in texts:
        if "dscSearchJobList" not in text or "orgNumbers" not in text:
            continue
        for static_match in re.finditer(r"\bcompanyOutId\s*:\s*[\"'](\d{4,12})[\"']", text):
            fallback_ids.append(static_match.group(1))
        for static_match in re.finditer(
            r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*[\"'](\d{4,12})[\"']", text
        ):
            fallback_ids.append(static_match.group(1))
        for number_match in re.finditer(r"orgNumbers\s*(?:=|:)\s*(?:\[)?([A-Za-z_$][\w$]*)", text):
            variable = number_match.group(1)
            window = text[max(0, number_match.start() - 6_000) : number_match.start()]
            assignment_match = re.search(
                rf"\b{re.escape(variable)}\s*=\s*[\"']?(\d{{4,12}})[\"']?\s*[,;)]",
                window,
            )
            if assignment_match:
                fallback_ids.append(assignment_match.group(1))
    fallback_ids = list(dict.fromkeys(fallback_ids))
    for text in texts:
        config_match = _GRACE_CONFIG_RE.search(text)
        if config_match is None:
            continue
        chunk = text[config_match.start() : config_match.start() + 8_000]
        company_id = _field_from_config(chunk, "companyId")
        company_number = _field_from_config(chunk, "companyNumber")
        xiaozhao_id = _field_from_config(chunk, "xiaozhaoId")
        scene = _field_from_config(chunk, "scene")
        if company_id and scene:
            return _GraceConfig(
                company_id,
                company_number,
                xiaozhao_id,
                scene,
                tuple(fallback_ids),
            )
    return None


def _api_code(response: object) -> int | None:
    mapping = _mapping(response)
    value = mapping.get("code") if mapping else None
    parsed = _integer(value)
    if parsed is not None:
        return parsed
    text = _text(value)
    return int(text) if text and text.isdigit() else None


def _grace_candidates(config: _GraceConfig) -> list[str]:
    values = [config.xiaozhao_id, *config.fallback_ids, config.company_number, config.company_id]
    return list(dict.fromkeys(value for value in values if value))


def _parse_grace(
    url: str,
    page_url: str,
    page: str,
    config: _GraceConfig,
    request_json: JsonFetcher,
) -> list[dict[str, object]]:
    origin = urlunsplit((urlsplit(page_url).scheme, urlsplit(page_url).netloc, "", "", ""))
    headers = {"Origin": origin, "Referer": page_url}
    title_match = _TITLE_RE.search(page)
    site_name = _html_text(title_match.group(1)) if title_match else None
    primary_source = 2 if config.scene == "cam" else 1
    source_variants = (primary_source, 1 if primary_source == 2 else 2)
    response: object | None = None
    empty_response: object | None = None
    selected_org: str | None = None
    selected_shape = "list"
    selected_source = primary_source
    errors: list[str] = []
    for org in _grace_candidates(config):
        for source in source_variants:
            for shape in ("list", "string"):
                payload: dict[str, object] = {
                    "orgNumbers": [org] if shape == "list" else org,
                    "jobSource": source,
                    "pageIndex": 1,
                    "pageSize": _PAGE_SIZE,
                }
                try:
                    candidate = request_json(_GRACE_API, headers, payload)
                except Exception as exc:  # noqa: BLE001 - try the public identifier variants
                    errors.append(f"{org}/{source}/{shape}: {type(exc).__name__}")
                    continue
                if _api_code(candidate) != 200:
                    errors.append(f"{org}/{source}/{shape}: code={_api_code(candidate)}")
                    continue
                candidate_mapping = _mapping(candidate) or {}
                candidate_data = _mapping(candidate_mapping.get("data")) or {}
                candidate_jobs = candidate_data.get("jobList")
                if isinstance(candidate_jobs, list) and candidate_jobs:
                    response = candidate
                    selected_org = org
                    selected_shape = shape
                    selected_source = source
                    break
                empty_response = empty_response or candidate
            if response is not None:
                break
        if response is not None:
            break
    if response is None:
        response = empty_response
    if response is None or selected_org is None:
        if empty_response is not None:
            raise ValueError("Zhaopin Grace API contains no public open jobs")
        detail = ", ".join(errors[:3])
        raise ValueError(f"Zhaopin Grace API unavailable ({detail})")

    jobs: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    current = response
    for page_index in range(1, _MAX_PAGES + 1):
        response_mapping = _mapping(current)
        data = _mapping(response_mapping.get("data")) if response_mapping else None
        if data is None:
            raise ValueError("Zhaopin Grace API has no job data")
        raw_jobs = data.get("jobList")
        if not isinstance(raw_jobs, list):
            raise ValueError("Zhaopin Grace API has no job list")
        for value in raw_jobs:
            raw_job = _mapping(value)
            if raw_job is None:
                continue
            job = _mapping(raw_job.get("job")) or raw_job
            status = _text(_first(job, "status", "positionStatus"))
            if status and status.casefold() in _CLOSED_STATUS:
                continue
            job_id = _text(_first(job, "jobNumber", "number", "id"))
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append(
                _job_record(
                    {**raw_job, **job},
                    page_url,
                    source_page="grace_api",
                    scene=config.scene,
                    site_name=site_name,
                )
            )
        page_info = _mapping(data.get("pageInfo")) or {}
        total_page = _integer(page_info.get("totalPage")) or page_index
        if page_index >= total_page:
            break
        next_index = page_index + 1
        current = request_json(
            _GRACE_API,
            headers,
            {
                "orgNumbers": [selected_org] if selected_shape == "list" else selected_org,
                "jobSource": selected_source,
                "pageIndex": next_index,
                "pageSize": _PAGE_SIZE,
            },
        )
        if _api_code(current) != 200:
            raise ValueError(f"Zhaopin Grace pagination failed at page {next_index}")
    if not jobs:
        raise ValueError("Zhaopin Grace API contains no public open jobs")
    return jobs


def _parse_zhaokao(
    url: str,
    page_url: str,
    request_json: JsonFetcher,
) -> list[dict[str, object]]:
    parts = urlsplit(page_url)
    origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    headers = {"Origin": origin, "Referer": page_url}
    site_response = request_json(_ZHAOKAO_API + "site/portal/pc/site", headers, {})
    site_response_mapping = _mapping(site_response) or {}
    site_data = _mapping(site_response_mapping.get("data"))
    site_name = _text(site_data.get("siteName")) if site_data else None
    jobs_response = request_json(
        _ZHAOKAO_API + "site/portal/pc/job-info/portal-list-reformc", headers, {}
    )
    if _api_code(jobs_response) != 200:
        raise ValueError("Zhaopin Zhaokao API is unavailable")
    jobs_response_mapping = _mapping(jobs_response) or {}
    raw_jobs = jobs_response_mapping.get("data")
    if not isinstance(raw_jobs, list):
        raise ValueError("Zhaopin Zhaokao API has no job list")
    jobs: list[dict[str, object]] = []
    for value in raw_jobs:
        job = _mapping(value)
        if job is None:
            continue
        status = _text(job.get("status"))
        if status and status.casefold() in _CLOSED_STATUS:
            continue
        source_job_id = _text(_first(job, "id", "jobNumber"))
        if not source_job_id or not _text(job.get("jobName")):
            continue
        detail_url = f"{origin}/zk/#/pages/position-detail/index?id={source_job_id}"
        record = _job_record(
            job,
            page_url,
            source_page="zhaokao_api",
            scene=None,
            site_name=site_name,
        )
        record["detail_url"] = detail_url
        record["apply_url"] = detail_url
        record["source_ref"] = detail_url
        jobs.append(record)
    if not jobs:
        raise ValueError("Zhaopin Zhaokao API contains no public open jobs")
    return jobs


def parse(
    url: str,
    fetch_page: PageFetcher | None = None,
    request_json: JsonFetcher | None = None,
) -> list[dict[str, object]]:
    """Parse public Zhaopin job pages without login or browser-only state."""
    session = ZhaopinSession()
    fetcher = fetch_page or session.fetch_page
    page_url, page = fetcher(url)
    if "$positionData" in page:
        return _parse_mobile_position(page_url, page)
    if "__INITIAL_DATA__" in page:
        return _parse_initial_page(url, page_url, page)
    if "/zk" in urlsplit(page_url).path.casefold():
        return _parse_zhaokao(url, page_url, request_json or session.request_json)
    config = _discover_grace_config(page_url, page, fetcher)
    if config is None:
        raise ValueError("Zhaopin page has no stable public parser")
    return _parse_grace(url, page_url, page, config, request_json or session.request_json)


__all__ = ["ZhaopinSession", "parse"]
