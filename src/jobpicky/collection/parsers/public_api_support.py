"""Shared mechanics for public JSON recruitment API adapters."""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar
from urllib.parse import urlsplit, urlunsplit

from .public_api import JsonRequester

JsonTransport = Callable[
    [str, str, str, Mapping[str, object] | None],
    object,
]
PageFetcher = Callable[[int], "PublicPage"]
T = TypeVar("T")


@dataclass(frozen=True)
class PublicPage:
    """A normalized list page produced by a platform-specific envelope parser."""

    total: int
    items: list[Mapping[str, object]]
    page_count: int | None = None


def origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = html.unescape(re.sub(r"<[^>]+>", "\n", str(value)))
    cleaned = cleaned.replace("\u200b", "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*", "\n", cleaned).strip()
    return cleaned or None


def mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def non_negative_int(value: object, message: str) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if result < 0:
        raise ValueError(message)
    return result


def locations(value: object) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for child in value:
            if isinstance(child, Mapping):
                location = text(
                    child.get("name")
                    or child.get("label")
                    or child.get("cityName")
                    or child.get("workCityName")
                    or child.get("workLocation")
                )
            else:
                location = text(child)
            if location:
                result.append(location)
        return result
    return [item for item in re.split(r"[,，、/|;；\s]+", text(value) or "") if item]


def published_at(value: object) -> datetime | None:
    value_text = text(value)
    if not value_text:
        return None
    try:
        if value_text.isdigit():
            timestamp = float(value_text)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=UTC)
        parsed = datetime.fromisoformat(value_text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def bind_requester(
    source_url: str,
    override: JsonRequester | None,
    transport: JsonTransport,
) -> JsonRequester:
    if override is not None:
        return override
    return lambda endpoint, method, payload: transport(endpoint, source_url, method, payload)


def collect_pages(
    fetch_page: PageFetcher,
    *,
    source: str,
    max_jobs: int,
    max_pages: int,
    job_id: Callable[[Mapping[str, object]], str | None],
) -> tuple[list[Mapping[str, object]], int]:
    """Collect bounded pages while rejecting missing, repeated, or partial data."""
    first_page = fetch_page(1)
    total = first_page.total
    if total > max_jobs:
        raise ValueError(f"{source} API returned {total} jobs, above the safe limit")
    if total == 0:
        return [], 0
    reported_pages = first_page.page_count if first_page.page_count is not None else max_pages
    if reported_pages < 1 or reported_pages > max_pages:
        raise ValueError(f"{source} API returned an unsafe page count")

    items: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    for page_number in range(1, reported_pages + 1):
        page = first_page if page_number == 1 else fetch_page(page_number)
        if not page.items:
            raise ValueError(f"{source} API returned an incomplete page")
        new_items = 0
        for item in page.items:
            source_job_id = job_id(item)
            if not source_job_id:
                raise ValueError(f"{source} API returned a position without an id")
            if source_job_id in seen_ids:
                continue
            seen_ids.add(source_job_id)
            items.append(item)
            new_items += 1
        if new_items == 0:
            raise ValueError(f"{source} API returned an incomplete or repeated page")
        if len(items) >= total:
            return items[:total], total
    raise ValueError(f"{source} API returned {len(items)} of {total} jobs")


def map_bounded(
    items: list[Mapping[str, object]],
    mapper: Callable[[Mapping[str, object]], T],
    max_workers: int,
) -> list[T]:
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items) or 1)) as executor:
        return list(executor.map(mapper, items))


__all__ = [
    "JsonTransport",
    "PublicPage",
    "bind_requester",
    "collect_pages",
    "locations",
    "map_bounded",
    "mapping",
    "non_negative_int",
    "origin",
    "published_at",
    "text",
]
