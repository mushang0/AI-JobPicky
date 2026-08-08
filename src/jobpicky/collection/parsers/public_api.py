"""Bounded standard-library transport for public recruitment APIs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TIMEOUT_SECONDS = 20

JsonRequester = Callable[[str, str, Mapping[str, object] | None], object]


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _query_url(endpoint: str, payload: Mapping[str, object]) -> str:
    query = {key: value for key, value in payload.items() if value is not None and value != []}
    if not query:
        return endpoint
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(query, doseq=True)}"


def request_json(
    endpoint: str,
    source_url: str,
    method: str,
    payload: Mapping[str, object] | None,
    *,
    headers: Mapping[str, str] | None = None,
) -> object:
    """Fetch a public JSON endpoint with bounded response and no session state."""
    normalized_method = method.upper()
    query_payload = payload if normalized_method == "GET" else None
    request_url = _query_url(endpoint, query_payload or {})
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None and normalized_method != "GET"
        else None
    )
    request_headers = {
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/json" if body is not None else "",
        "Origin": _origin(source_url),
        "Referer": source_url,
        "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
    }
    request_headers.update(headers or {})
    request = Request(
        request_url,
        data=body,
        method=normalized_method,
        headers=request_headers,
    )
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310 - public API
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("public recruitment API response exceeds the safe response limit")
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ValueError("public recruitment API did not return JSON") from exc


def request_form_json(
    endpoint: str,
    source_url: str,
    method: str,
    payload: Mapping[str, object] | None,
) -> object:
    """Fetch a public JSON endpoint whose browser client submits form data."""
    normalized_method = method.upper()
    query_payload = payload if normalized_method == "GET" else None
    request_url = _query_url(endpoint, query_payload or {})
    form_pairs: list[tuple[str, str]] = []
    if payload is not None and normalized_method != "GET":
        for key, value in payload.items():
            if value is None or value == []:
                continue
            if isinstance(value, list):
                form_pairs.extend((f"{key}[]", str(item)) for item in value)
            else:
                form_pairs.append((key, str(value)))
    body = urlencode(form_pairs).encode("utf-8") if form_pairs else None
    request = Request(
        request_url,
        data=body,
        method=normalized_method,
        headers={
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Origin": _origin(source_url),
            "Referer": source_url,
            "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
        },
    )
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310 - public API
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("public recruitment API response exceeds the safe response limit")
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ValueError("public recruitment API did not return JSON") from exc


__all__ = ["JsonRequester", "request_form_json", "request_json"]
