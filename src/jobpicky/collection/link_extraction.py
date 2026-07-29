"""Extract application links from Excel cell text and hyperlink targets."""

from __future__ import annotations

import re

_URL_RE = re.compile(r"(?i)(?:https?://|mailto:)[^\s<>\"']+")
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_TRAILING_PUNCTUATION = "，,；;。！？!?)]}"


def extract_links(value: object, hyperlink_target: str | None) -> list[str]:
    """Extract distinct links from a cell's text and its hyperlink target.

    Email addresses already contained in a matched URL (e.g. ``mailto:hr@x.com``
    or userinfo in an http URL) are not reported again as standalone links.
    """
    sources = [source for source in (value, hyperlink_target) if isinstance(source, str)]
    links: list[str] = []
    for source in sources:
        matches = []
        for match in _URL_RE.findall(source):
            matches.extend(re.split(r"[,，;；]\s*(?=(?:https?://|mailto:))", match))
        for email in _EMAIL_RE.findall(source):
            if not any(email in url_match for url_match in matches):
                matches.append(email)
        if not matches and source.strip() and hyperlink_target is None:
            matches = [source.strip()]
        for link in matches:
            link = link.rstrip(_TRAILING_PUNCTUATION)
            if link and link not in links:
                links.append(link)
    return links


__all__ = ["extract_links"]
