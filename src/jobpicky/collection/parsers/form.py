"""Parse public form links only when the form page exposes recruitment evidence."""

from __future__ import annotations

from collections.abc import Callable

from .public_web import fetch_html
from .public_web import parse as parse_public_web


def parse(url: str, fetch: Callable[[str], str] = fetch_html) -> list[dict[str, object]]:
    """Keep a form as an announcement only when its public page proves recruitment context."""
    jobs = parse_public_web(url, fetch, allow_announcement=True)
    if not jobs:
        raise ValueError("form page has no public recruitment facts")
    return jobs


__all__ = ["fetch_html", "parse"]
