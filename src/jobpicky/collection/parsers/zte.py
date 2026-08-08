"""Thin ZTE adapter: discover the official Moka campus source and reuse it."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from .moka import parse as parse_moka
from .public_web import fetch_html as _fetch_html

_MOKA_LINK_RE = re.compile(
    r"https://app\.mokahr\.com/campus-recruitment/zte/46903[^\"'<>\s]*",
    re.IGNORECASE,
)
_MOKA_PATH = "/campus-recruitment/zte/46903"


def _discover_moka_url(source_url: str, page: str) -> str:
    source = urlsplit(source_url)
    if (source.hostname or "").casefold() != "job.zte.com.cn":
        raise ValueError("ZTE source must use the official job.zte.com.cn host")
    for match in _MOKA_LINK_RE.finditer(html.unescape(page)):
        candidate = match.group(0).rstrip(".,;)")
        parts = urlsplit(candidate)
        if (
            parts.scheme == "https"
            and (parts.hostname or "").casefold() == "app.mokahr.com"
            and parts.path.rstrip("/") == _MOKA_PATH
        ):
            return urlunsplit(("https", "app.mokahr.com", _MOKA_PATH, "", "/jobs"))
    raise ValueError("ZTE page has no official Moka campus link")


def parse(url: str, fetch: Callable[[str], str] = _fetch_html) -> list[dict[str, object]]:
    """Parse ZTE's public campus jobs through its official Moka source."""
    moka_url = _discover_moka_url(url, fetch(url))
    jobs = parse_moka(moka_url)
    for job in jobs:
        metadata = job.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        metadata["discovery_route"] = "zte_official_page_to_moka"
        metadata["discovered_from"] = urlsplit(url)._replace(query="", fragment="").geturl()
        job["metadata"] = metadata
    return jobs


__all__ = ["parse"]
