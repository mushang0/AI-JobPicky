"""Read recruitment rows from a Feishu Bitable without changing the parser pipeline."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, tzinfo
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .spreadsheet import SpreadsheetRow, extract_row

_API_ROOT = "https://open.feishu.cn/open-apis/bitable/v1"
_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_RETRIES = 3
_FEISHU_DATE_TIMEZONE = ZoneInfo("Asia/Shanghai")

DEFAULT_FIELD_MAP: dict[str, str] = {
    "updated_at": "更新时间",
    "company_name": "公司名称",
    "company_nature": "企业性质",
    "industry": "行业分类",
    "job_directions": "招聘岗位",
    "locations": "工作地点",
    "deadline_at": "截止时间",
    "graduation": "届次",
    "education": "学历要求",
    "batch": "批次",
    "announcement_source": "公告来源",
    "announcement_url": "公告链接",
    "apply_url": "投递链接",
    "major_requirement": "专业要求",
    "has_written_test": "是否笔试",
}


class FeishuApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        api_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_code = api_code


@dataclass(frozen=True, slots=True)
class FeishuBitableConfig:
    app_token: str
    table_id: str
    view_id: str | None
    since_date: date
    field_map: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_FIELD_MAP))


@dataclass(frozen=True, slots=True)
class FeishuRecord:
    record_id: str
    fields: Mapping[str, object]
    last_modified_time: datetime | None


class FeishuBitableClient:
    def __init__(
        self,
        access_token: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        retries: int = _DEFAULT_RETRIES,
    ) -> None:
        if not access_token.strip():
            raise ValueError("Feishu access token is required")
        if timeout_seconds <= 0:
            raise ValueError("Feishu timeout must be positive")
        if retries < 1:
            raise ValueError("Feishu retries must be at least 1")
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds
        self._retries = retries

    def list_fields(
        self,
        app_token: str,
        table_id: str,
    ) -> list[Mapping[str, object]]:
        items: list[Mapping[str, object]] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            params: dict[str, str] = {"page_size": "100"}
            if page_token:
                params["page_token"] = page_token
            payload = self._request_json(
                "GET",
                self._resource_url(app_token, table_id, "fields"),
                query=params,
            )
            data = _data_object(payload)
            items.extend(_mapping_items(data.get("items")))
            if not data.get("has_more"):
                return items
            next_token = data.get("page_token")
            if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                raise FeishuApiError("Feishu field pagination returned an invalid page token")
            seen_tokens.add(next_token)
            page_token = next_token

    def iter_records(
        self,
        app_token: str,
        table_id: str,
        *,
        view_id: str | None = None,
        field_names: Sequence[str] | None = None,
        sort: Sequence[Mapping[str, object]] | None = None,
        page_size: int = 500,
    ) -> Iterator[FeishuRecord]:
        if not 1 <= page_size <= 500:
            raise ValueError("Feishu page_size must be between 1 and 500")
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            query = {"page_size": str(page_size)}
            if page_token:
                query["page_token"] = page_token
            body: dict[str, object] = {"automatic_fields": True}
            if view_id:
                body["view_id"] = view_id
            if field_names:
                body["field_names"] = list(field_names)
            if sort:
                body["sort"] = [dict(condition) for condition in sort]
            payload = self._request_json(
                "POST",
                self._resource_url(app_token, table_id, "records/search"),
                query=query,
                body=body,
            )
            data = _data_object(payload)
            for raw_record in _mapping_items(data.get("items")):
                record_id = raw_record.get("record_id")
                fields = raw_record.get("fields")
                if not isinstance(record_id, str) or not record_id:
                    raise FeishuApiError("Feishu record response did not contain record_id")
                if not isinstance(fields, Mapping):
                    fields = {}
                yield FeishuRecord(
                    record_id=record_id,
                    fields=dict(fields),
                    last_modified_time=_timestamp_to_datetime(raw_record.get("last_modified_time")),
                )
            if not data.get("has_more"):
                return
            next_token = data.get("page_token")
            if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                raise FeishuApiError("Feishu record pagination returned an invalid page token")
            seen_tokens.add(next_token)
            page_token = next_token

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        request_url = f"{url}?{urlencode(query)}" if query else url
        encoded_body = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": "AI-JobPicky/0.1",
        }
        if encoded_body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(request_url, data=encoded_body, headers=headers, method=method)

        for attempt in range(self._retries):
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                    raw = response.read()
            except HTTPError as exc:
                payload = _read_error_payload(exc)
                if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < self._retries:
                    time.sleep(2**attempt)
                    continue
                message = _error_message(payload) or f"HTTP {exc.code}"
                raise FeishuApiError(
                    f"Feishu API request failed: {message}",
                    status_code=exc.code,
                    api_code=_api_code(payload),
                ) from exc
            except URLError as exc:
                if attempt + 1 < self._retries:
                    time.sleep(2**attempt)
                    continue
                raise FeishuApiError("Feishu API request could not reach the service") from exc
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FeishuApiError("Feishu API returned invalid JSON") from exc
            if not isinstance(decoded, dict):
                raise FeishuApiError("Feishu API returned an invalid response")
            if decoded.get("code") != 0:
                raise FeishuApiError(
                    "Feishu API rejected the request: "
                    f"{_error_message(decoded) or 'unknown error'}",
                    api_code=_api_code(decoded),
                )
            return decoded
        raise FeishuApiError("Feishu API request exhausted retries")

    @staticmethod
    def _resource_url(app_token: str, table_id: str, suffix: str) -> str:
        return f"{_API_ROOT}/apps/{app_token}/tables/{table_id}/{suffix}"


class FeishuBitableSource:
    def __init__(self, config: FeishuBitableConfig) -> None:
        self.config = config

    def row_from_record(self, record: FeishuRecord, row_number: int) -> SpreadsheetRow | None:
        fields = self.config.field_map
        apply_value, apply_link = _text_and_link(record.fields.get(fields["apply_url"]))
        announcement_value, announcement_link = _text_and_link(
            record.fields.get(fields["announcement_url"])
        )
        values = [
            _date_text(record.fields.get(fields["updated_at"])),
            _text(record.fields.get(fields["company_name"])),
            _text(record.fields.get(fields["company_nature"])),
            _text(record.fields.get(fields["industry"])),
            _text(record.fields.get(fields["job_directions"])),
            _text(record.fields.get(fields["locations"])),
            _date_text(record.fields.get(fields["deadline_at"])),
            _text(record.fields.get(fields["graduation"])),
            _text(record.fields.get(fields["education"])),
            _text(record.fields.get(fields["batch"])),
            _text(record.fields.get(fields["announcement_source"])),
            announcement_link or announcement_value,
            apply_value or apply_link,
            _text(record.fields.get(fields["major_requirement"])),
            _text(record.fields.get(fields["has_written_test"])),
        ]
        row = extract_row(
            row_number,
            values,
            hyperlink_target=apply_link,
        )
        if row is None:
            return None
        return replace(
            row,
            source_record_id=record.record_id,
            source_last_modified_at=record.last_modified_time,
        )

    def row_is_after_cutoff(self, row: SpreadsheetRow) -> bool:
        return row.updated_at is not None and row.updated_at.date() > self.config.since_date

    def record_is_at_or_before_cutoff(self, record: FeishuRecord) -> bool:
        updated_at = _timestamp_to_datetime(
            record.fields.get(self.config.field_map["updated_at"]),
            timezone=_FEISHU_DATE_TIMEZONE,
        )
        return updated_at is not None and updated_at.date() <= self.config.since_date

    @staticmethod
    def record_hash(record: FeishuRecord) -> str:
        payload = json.dumps(
            record.fields,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _data_object(payload: Mapping[str, object]) -> dict[str, object]:
    data = payload.get("data")
    return dict(data) if isinstance(data, Mapping) else {}


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _read_error_payload(error: HTTPError) -> dict[str, object]:
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _error_message(payload: Mapping[str, object]) -> str | None:
    message = payload.get("msg") or payload.get("message") or payload.get("error_description")
    return str(message)[:240] if message else None


def _api_code(payload: Mapping[str, object]) -> int | None:
    value = payload.get("code")
    return value if isinstance(value, int) else None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, Mapping):
        for key in ("text", "name", "value"):
            if key in value:
                return _text(value[key])
        return ""
    if isinstance(value, list):
        return ", ".join(part for item in value if (part := _text(item)))
    return ""


def _text_and_link(value: object) -> tuple[str, str | None]:
    if isinstance(value, Mapping):
        link = value.get("link")
        return _text(value), link.strip() if isinstance(link, str) and link.strip() else None
    if isinstance(value, list):
        texts: list[str] = []
        links: list[str] = []
        for item in value:
            text, link = _text_and_link(item)
            if text:
                texts.append(text)
            if link and link not in links:
                links.append(link)
        return ", ".join(texts), links[0] if links else None
    return _text(value), None


def _date_text(value: object) -> str:
    parsed = _timestamp_to_datetime(value, timezone=_FEISHU_DATE_TIMEZONE)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")
    text = _text(value)
    if len(text) >= 10 and text[4] in {"-", "/"} and text[7] in {"-", "/"}:
        return text[:10].replace("/", "-")
    return text


def _timestamp_to_datetime(value: object, *, timezone: tzinfo = UTC) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return _timestamp_to_datetime(int(text), timezone=timezone)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed.astimezone(timezone)


__all__ = [
    "DEFAULT_FIELD_MAP",
    "FeishuApiError",
    "FeishuBitableClient",
    "FeishuBitableConfig",
    "FeishuBitableSource",
    "FeishuRecord",
]
