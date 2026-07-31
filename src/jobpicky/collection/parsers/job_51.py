from __future__ import annotations

import ast
import hashlib
import html
import json
import random
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_COAPI_BASE = "https://coapi.51job.com/"
_COAPI_SCRIPT = "https://js.51jobcdn.com/in/js/2018/coapi/coapi.min.js"
_COAPI_KEY_RE = re.compile(r"window\.coapi\s*=\s*\{\s*key\s*:\s*[\"']([^\"']+)")
_CTMID_RE = re.compile(r"\bctmid\s*[=:]\s*[\"']?(\d{5,})", re.IGNORECASE)
_JOB_ID_RE = re.compile(r"(?:jobid|job_id)\s*[=:]\s*[\"']?(\d{6,})", re.IGNORECASE)
_JOB_PATH_ID_RE = re.compile(r"/(\d{7,})\.html(?:$|[?#])", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_ARRAY_RE = re.compile(r"(?:var|let|const)\s+(?:data|job\d*|jobs|jobList)\s*=\s*\[", re.IGNORECASE)
_GENERIC_ARRAY_RE = re.compile(r"(?:=|:)\s*\[(?=\s*\{)")
_MAX_HTML_BYTES = 4 * 1024 * 1024
_MAX_SCRIPT_BYTES = 2 * 1024 * 1024
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_DESCRIPTION_CHARS = 80_000
_MAX_PAGES = 200
_MAX_STATIC_IDS = 200
_LOGIN_HOSTS = frozenset({"young.yingjiesheng.com", "passport.51job.com"})
_LOGIN_MARKERS = ("/login", "/xyzlogin", "/consumer/", "passport.")
_SCRIPT_SKIP = ("jquery", "swiper", "jweixin", "ienv", "track")

PageFetcher = Callable[[str], tuple[str, str]]
JsonFetcher = Callable[[str, Mapping[str, str], Mapping[str, object]], object]


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


class _VisibleTextParser(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {"address", "article", "br", "div", "li", "p", "section", "tr", "h1", "h2", "h3"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.skip_depth += 1
        if tag in self._BLOCK_TAGS and self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in self._BLOCK_TAGS and self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


class Job51Session:
    def __init__(
        self,
        fetch: PageFetcher | None = None,
        request_json: JsonFetcher | None = None,
        public_key: str | None = None,
    ) -> None:
        self.fetch = fetch or fetch_page
        self.request_json_override = request_json
        self.public_key = public_key

    def request_json(
        self, url: str, headers: Mapping[str, str], payload: Mapping[str, object]
    ) -> object:
        if self.request_json_override is not None:
            return self.request_json_override(url, headers, payload)
        request_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "identity",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
            **headers,
        }
        request = Request(url, headers=request_headers)
        with urlopen(request, timeout=20) as response:  # noqa: S310 - public recruitment API
            body = response.read(_MAX_JSON_BYTES + 1)
            if len(body) > _MAX_JSON_BYTES:
                raise ValueError("51job API response exceeds the safe response limit")
        text = body.decode("utf-8", "replace").strip()
        if text.startswith("?"):
            text = text[text.find("(") + 1 : text.rfind(")")]
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("51job API did not return JSON") from exc

    def coapi(self, endpoint: str, params: Mapping[str, object]) -> object:
        if self.request_json_override is not None:
            return self.request_json(
                urljoin(_COAPI_BASE, endpoint),
                {"Referer": "https://campus.51job.com/"},
                params,
            )
        key = self.public_key or self._load_public_key()
        key_index = random.randint(1, 40)
        serialized = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
        signature = hashlib.md5(  # noqa: S324 - required by the public 51job client
            f"coapi{serialized}{key[key_index : key_index + 15]}".encode()
        ).hexdigest()
        query = urlencode(
            {
                "jsoncallback": "?",
                "key": key_index,
                "sign": signature,
                "params": serialized,
            }
        )
        return self.request_json(
            urljoin(_COAPI_BASE, endpoint) + "?" + query,
            {"Referer": "https://campus.51job.com/"},
            {},
        )

    def _load_public_key(self) -> str:
        _final_url, script = self.fetch(_COAPI_SCRIPT)
        match = _COAPI_KEY_RE.search(script)
        if match is None:
            raise ValueError("51job public coapi key was not found in its public client script")
        self.public_key = match.group(1)
        return self.public_key


def fetch_page(url: str) -> tuple[str, str]:
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
            raise ValueError("51job page exceeds the safe response limit")
        return response.url, body.decode(
            response.headers.get_content_charset() or "utf-8", "replace"
        )


def _text(value: object) -> str | None:
    if value is None:
        return None
    raw = value if isinstance(value, str) else str(value)
    if "<" in raw and ">" in raw:
        parser = _VisibleTextParser()
        parser.feed(raw)
        raw = " ".join(parser.parts)
    result = " ".join(html.unescape(raw).split())
    return result or None


def _description(value: object) -> str | None:
    if value is None:
        return None
    raw = value if isinstance(value, str) else str(value)
    if "<" in raw and ">" in raw:
        parser = _VisibleTextParser()
        parser.feed(raw)
        lines = [" ".join(part.split()) for part in "".join(parser.parts).splitlines()]
        result = "\n".join(line for line in lines if line)
    else:
        result = "\n".join(line.strip() for line in html.unescape(raw).splitlines() if line.strip())
    return result[:_MAX_DESCRIPTION_CHARS] or None


def _date(value: object) -> datetime | None:
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


def _valid_url(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _first(fields: Mapping[str, object], *names: str) -> object | None:
    for name in names:
        value = fields.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _locations(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = _text(item.get("name") if isinstance(item, Mapping) else item)
                if text and text not in result:
                    result.append(text)
            continue
        text = _text(value)
        if not text:
            continue
        for item in re.split(r"[,，、|;；]+", text):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return result


def _recruitment_type(text: str, page_url: str) -> str | None:
    if "实习" in text or "intern" in urlsplit(page_url).path.casefold():
        return "实习"
    if any(marker in text for marker in ("社会招聘", "社会招募", "社招")):
        return "社招"
    if any(marker in text for marker in ("校园招聘", "校园", "校招", "秋招", "春招")):
        return "校招"
    if any(marker in urlsplit(page_url).path.casefold() for marker in ("campus", "graduates")):
        return "校招"
    return None


def _salary(value: object) -> tuple[int | None, int | None]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value)
        return (number, number) if number >= 0 else (None, None)
    text = _text(value)
    if not text:
        return None, None
    numbers = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not numbers or any(marker in text for marker in ("面议", "不限", "不详")):
        return None, None
    factor = 10_000 if "万" in text else 1
    values = [int(float(number) * factor) for number in numbers[:2]]
    return (values[0], values[-1])


def _source_job_id(row: Mapping[str, object], fallback_url: str, title: str) -> str:
    value = _text(_first(row, "jobid", "jobId", "job_id", "id", "source_job_id"))
    if value:
        return value
    for candidate in (_first(row, "link", "url", "joburl", "jobUrl", "d"), fallback_url):
        if candidate:
            ids = _job_ids(str(candidate))
            if ids:
                return ids[0]
    evidence = f"{fallback_url}\n{title}"
    return "page-" + hashlib.sha1(evidence.encode("utf-8")).hexdigest()[:16]  # noqa: S324


def _normalise_job(
    row: Mapping[str, object],
    page_url: str,
    *,
    ctmid: str | None = None,
    record_kind: str = "job",
) -> dict[str, object] | None:
    title = _text(
        _first(row, "jobname", "jobName", "name", "title", "b", "职位名称", "岗位名称", "职位")
    )
    if not title:
        return None
    job_id = _source_job_id(row, page_url, title)
    candidate_link = _valid_url(_first(row, "detail_url", "detailUrl", "joburl", "jobUrl"))
    apply_url = _valid_url(_first(row, "apply_url", "applyUrl", "link", "d", "url"))
    if candidate_link and "external/apply" in candidate_link.casefold():
        apply_url = apply_url or candidate_link
        candidate_link = None
    detail_url = candidate_link or f"https://jobs.51job.com/all/{job_id}.html"
    if job_id.startswith("page-"):
        detail_url = _valid_url(_first(row, "detail_url", "detailUrl")) or page_url
    description = _description(
        _first(
            row,
            "jobinfo",
            "jobInfo",
            "jobdesc",
            "jobDesc",
            "description",
            "c",
            "detail",
            "职责描述",
            "岗位职责",
            "职位描述",
        )
    )
    location_values = _locations(
        _first(row, "jobareaname", "jobAreaName", "workareaname", "workAreaName"),
        _first(
            row,
            "address",
            "jobarea",
            "jobArea",
            "place",
            "del",
            "city",
            "工作地点",
            "工作城市",
            "城市",
            "地点",
        ),
    )
    degree = _text(_first(row, "degreefrom", "degreeFrom", "education", "edu", "学历", "学历/学位"))
    published_at = _date(_first(row, "issuedate", "issueDate", "publishdate", "publishDate"))
    salary_value = _first(row, "monthlysalary", "monthlySalary", "salary")
    salary_min, salary_max = _salary(salary_value)
    type_text = " ".join(
        item
        for item in (
            title,
            description or "",
            _text(_first(row, "term", "funtype", "funType", "jobtype", "jobType")) or "",
        )
        if item
    )
    metadata: dict[str, object] = {
        "platform": "JOB_51",
        "record_kind": record_kind,
    }
    if ctmid:
        metadata["ctmid"] = ctmid
    for key in ("status", "term", "funtype", "functype", "providesalarname"):
        value = _text(row.get(key))
        if value:
            metadata[key] = value
    job: dict[str, object] = {
        "source_job_id": job_id,
        "title": title,
        "description": description,
        "locations": location_values,
        "detail_url": detail_url,
        "apply_url": apply_url or detail_url,
        "recruitment_type": _recruitment_type(type_text, page_url),
        "education_requirement": degree,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "published_at": published_at,
        "source_ref": detail_url,
        "metadata": metadata,
    }
    return job


def _job_ids(text: str) -> list[str]:
    found = _JOB_ID_RE.findall(text)
    found.extend(_JOB_PATH_ID_RE.findall(text))
    found.extend(re.findall(r"[?&](?:jobid|job_id)=([0-9]{6,})", text, re.IGNORECASE))
    return list(dict.fromkeys(found))


def _ctmids(text: str) -> list[str]:
    found = _CTMID_RE.findall(text)
    for key, value in parse_qsl(urlsplit(text).query, keep_blank_values=True):
        if key.casefold() == "ctmid" and value.isdigit() and len(value) >= 5:
            found.append(value)
    return list(dict.fromkeys(found))


def _balanced_span(text: str, start: int, opening: str, closing: str) -> int | None:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "'\"`":
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _script_sources(page_url: str, page: str) -> list[str]:
    parser = _ScriptParser()
    parser.feed(page)
    sources: list[str] = []
    for source in parser.sources:
        absolute = urljoin(page_url, source)
        path = urlsplit(absolute).path.casefold()
        if not absolute.startswith(("http://", "https://")) or any(
            marker in path for marker in _SCRIPT_SKIP
        ):
            continue
        if absolute not in sources:
            sources.append(absolute)
    return sources[:16]


def _array_literals(text: str) -> list[str]:
    arrays: list[str] = []
    for match in _ARRAY_RE.finditer(text):
        end = _balanced_span(text, text.find("[", match.start(), match.end()), "[", "]")
        if end is not None:
            arrays.append(text[match.end() - 1 : end])
    seen = set(arrays)
    for match in _GENERIC_ARRAY_RE.finditer(text):
        end = _balanced_span(text, text.find("[", match.start(), match.end()), "[", "]")
        if end is None:
            continue
        array = text[match.end() - 1 : end]
        if array not in seen:
            arrays.append(array)
            seen.add(array)
        if len(arrays) >= 120:
            break
    return arrays


def _object_literals(array_text: str) -> list[str]:
    objects: list[str] = []
    index = 0
    while index < len(array_text):
        if array_text[index] != "{":
            index += 1
            continue
        end = _balanced_span(array_text, index, "{", "}")
        if end is None:
            break
        objects.append(array_text[index:end])
        index = end
    return objects


def _js_string(object_text: str, key: str) -> str | None:
    pattern = re.compile(
        rf"(?:[\"']{re.escape(key)}[\"']|\b{re.escape(key)}\b)\s*:\s*([\"'])(.*?)\1",
        re.DOTALL,
    )
    match = pattern.search(object_text)
    if match is None:
        return None
    token = match.group(1) + match.group(2) + match.group(1)
    try:
        value = ast.literal_eval(token)
    except (SyntaxError, ValueError):
        value = match.group(2).replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')
    return value if isinstance(value, str) else None


def _static_rows(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for array in _array_literals(text):
        try:
            value = json.loads(array)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            rows.extend(value)
            continue
        for object_text in _object_literals(array):
            row: dict[str, object] = {}
            for key in (
                "jobid",
                "jobname",
                "jobinfo",
                "jobareaname",
                "degreefrom",
                "company",
                "name",
                "title",
                "a",
                "b",
                "c",
                "d",
                "link",
                "edu",
                "del",
                "职位名称",
                "岗位名称",
                "职位",
                "职责描述",
                "岗位职责",
                "职位描述",
                "工作地点",
                "工作城市",
                "城市",
                "地点",
                "学历",
                "学历/学位",
            ):
                if item := _js_string(object_text, key):
                    row[key] = item
            if row:
                rows.append(row)
    return rows


def _api_body(value: object) -> tuple[Mapping[str, object] | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None
    body = value.get("resultbody")
    if isinstance(body, Mapping):
        return body, _text(value.get("status"))
    data = value.get("data")
    if isinstance(data, Mapping):
        return data, _text(value.get("status") or value.get("code"))
    return value, _text(value.get("status") or value.get("code"))


def _list_rows(value: object) -> tuple[list[Mapping[str, object]], int | None, str | None]:
    body, status = _api_body(value)
    if body is None:
        return [], None, status
    raw_rows = body.get("joblist") or body.get("jobList") or body.get("list")
    rows = (
        [row for row in raw_rows if isinstance(row, Mapping)] if isinstance(raw_rows, list) else []
    )
    total_value = body.get("totalnum") or body.get("totalNum") or body.get("total")
    try:
        total = int(str(total_value)) if total_value not in (None, "") else None
    except ValueError:
        total = None
    return rows, total, status


def _detail_row(value: object) -> tuple[Mapping[str, object] | None, str | None]:
    body, status = _api_body(value)
    return body, status


def _list_jobs(session: Job51Session, page_url: str, ctmid: str) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "ctmid": ctmid,
        "poscode": "",
        "jobarea": "",
        "pagesize": 2000,
        "sort": "joborder",
        "sequence": 1,
    }
    jobs: list[dict[str, object]] = []
    seen: set[str] = set()
    total: int | None = None
    page_size = 2000
    for page_number in range(1, _MAX_PAGES + 1):
        if page_number > 1:
            params["pagenum"] = page_number
            page_size = 100
            params["pagesize"] = page_size
        try:
            response = session.coapi("job_list.php", params)
        except Exception:  # noqa: BLE001 - another public source shape may still be usable
            break
        rows, total, _status = _list_rows(response)
        for row in rows:
            job = _normalise_job(row, page_url, ctmid=ctmid)
            if job is None:
                continue
            key = str(job["source_job_id"])
            if key not in seen:
                seen.add(key)
                jobs.append(job)
        if not rows or total is None or len(seen) >= total:
            break
        if page_number > 1 and len(rows) < page_size:
            break
    return jobs


def _detail_jobs(
    session: Job51Session, page_url: str, job_ids: list[str], ctmid: str | None = None
) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    seen: set[str] = set()
    for job_id in job_ids[:_MAX_STATIC_IDS]:
        try:
            response = session.coapi("job_detail.php", {"jobid": job_id})
        except Exception:  # noqa: BLE001 - preserve static rows when a detail is gone
            continue
        row, _status = _detail_row(response)
        if row is None:
            continue
        job = _normalise_job(row, page_url, ctmid=ctmid)
        if job is None:
            continue
        key = str(job["source_job_id"])
        if key not in seen:
            seen.add(key)
            jobs.append(job)
    return jobs


def _page_title(page: str) -> str | None:
    match = _TITLE_RE.search(page)
    return _text(match.group(1)) if match else None


def _visible_text(page: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(page)
    lines = [" ".join(part.split()) for part in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _is_login_page(page_url: str, title: str | None, body: str) -> bool:
    host = (urlsplit(page_url).hostname or "").casefold()
    path = urlsplit(page_url).path.casefold()
    if host in _LOGIN_HOSTS:
        return True
    if host == "xyz.51job.com" and any(marker in path for marker in _LOGIN_MARKERS):
        return True
    haystack = f"{title or ''}\n{body[:1000]}".casefold()
    return any(marker in haystack for marker in ("请登录", "用户登录", "登录后查看"))


def _announcement(page_url: str, title: str | None, body: str) -> list[dict[str, object]]:
    if not title or len(body) < 40:
        return []
    if title.casefold() in {"jobs", "job", "51job", "前程无忧"}:
        return []
    text = f"{title}\n{body}"
    if not any(
        marker in text for marker in ("招聘", "招募", "岗位", "职位", "实习", "校招", "校园")
    ):
        return []
    normalized_url = _valid_url(page_url) or page_url
    row = {
        "title": title,
        "description": body[:_MAX_DESCRIPTION_CHARS],
        "detail_url": normalized_url,
        "apply_url": normalized_url,
        "source_job_id": "page-" + hashlib.sha1(normalized_url.encode()).hexdigest()[:16],  # noqa: S324
    }
    job = _normalise_job(row, normalized_url, record_kind="51job_announcement")
    return [job] if job is not None else []


def _fetch_entry(session: Job51Session, url: str) -> tuple[str, str]:
    try:
        return session.fetch(url)
    except Exception:
        parts = urlsplit(url)
        if not parts.query:
            raise
        canonical_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        if canonical_url == url:
            raise
        return session.fetch(canonical_url)


def parse(
    url: str,
    fetch: PageFetcher = fetch_page,
    request_json: JsonFetcher | None = None,
    public_key: str | None = None,
) -> list[dict[str, object]]:
    """Parse public 51job API data, static job arrays, or an announcement page."""
    session = Job51Session(fetch=fetch, request_json=request_json, public_key=public_key)
    source_ctmids = _ctmids(url)
    direct_ids = _job_ids(url)

    if direct_ids:
        jobs = _detail_jobs(session, url, direct_ids, source_ctmids[0] if source_ctmids else None)
        if jobs:
            return jobs
    if source_ctmids:
        for ctmid in source_ctmids:
            jobs = _list_jobs(session, url, ctmid)
            if jobs:
                return jobs

    page_url, page = _fetch_entry(session, url)
    title = _page_title(page)
    visible = _visible_text(page)
    if _is_login_page(page_url, title, visible):
        raise ValueError("51job page requires login or is not a public recruitment entry")

    scripts: list[str] = []
    for source in _script_sources(page_url, page):
        try:
            _final_script_url, script = session.fetch(source)
        except Exception:  # noqa: BLE001 - page data can still be sufficient
            continue
        if len(script.encode("utf-8")) <= _MAX_SCRIPT_BYTES:
            scripts.append(script)
    public_text = "\n".join([page, *scripts])
    ctmids = list(dict.fromkeys([*source_ctmids, *_ctmids(public_text)]))
    page_job_ids = list(dict.fromkeys([*direct_ids, *_job_ids(public_text)]))

    for ctmid in ctmids:
        jobs = _list_jobs(session, page_url, ctmid)
        if jobs:
            return jobs

    jobs = _detail_jobs(session, page_url, page_job_ids, ctmids[0] if ctmids else None)
    if jobs:
        return jobs

    static_jobs: list[dict[str, object]] = []
    seen_static: set[str] = set()
    for row in _static_rows(public_text):
        job = _normalise_job(row, page_url, ctmid=ctmids[0] if ctmids else None)
        if job is None:
            continue
        key = str(job["source_job_id"])
        if key not in seen_static:
            seen_static.add(key)
            static_jobs.append(job)
    if static_jobs:
        return static_jobs

    announcement = _announcement(page_url, title, visible)
    if announcement:
        return announcement
    raise ValueError("51job page has no verified public job list, detail, or announcement")


__all__ = ["fetch_page", "parse"]
