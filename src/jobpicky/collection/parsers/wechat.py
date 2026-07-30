from __future__ import annotations

import gzip
import re
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

_ARTICLE_ID_RE = re.compile(r"/(?:s|mp/appmsg/show)/(?P<article_id>[A-Za-z0-9_-]+)")
_MAX_HTML_BYTES = 8 * 1024 * 1024
_MAX_DESCRIPTION_CHARS = 80_000


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.content_parts: list[str] = []
        self.meta_title: str | None = None
        self.meta_description: str | None = None
        self.publish_time: str | None = None
        self._title_depth = 0
        self._content_depth = 0
        self._skip_depth = 0
        self._publish_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id == "activity-name":
            self._title_depth = 1
        elif self._title_depth:
            self._title_depth += 1
        if element_id == "js_content":
            self._content_depth = 1
        elif self._content_depth:
            self._content_depth += 1
        if self._content_depth and tag in {"script", "style"}:
            self._skip_depth += 1
        if element_id == "publish_time":
            self._publish_depth = 1
        elif self._publish_depth:
            self._publish_depth += 1
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            value = attributes.get("content")
            if key == "og:title" and value:
                self.meta_title = value
            elif key == "description" and value:
                self.meta_description = value

    def handle_endtag(self, tag: str) -> None:
        if self._title_depth:
            self._title_depth -= 1
        if self._content_depth:
            if tag in {"script", "style"} and self._skip_depth:
                self._skip_depth -= 1
            self._content_depth -= 1
        if self._publish_depth:
            self._publish_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._content_depth and not self._skip_depth:
            self.content_parts.append(data)
        if self._publish_depth:
            self.publish_time = (self.publish_time or "") + data


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (compatible; AI-JobPicky/0.1)",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - public article URL
        body = response.read(_MAX_HTML_BYTES + 1)
        if len(body) > _MAX_HTML_BYTES:
            raise ValueError("WeChat article exceeds the safe response limit")
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return body.decode(response.headers.get_content_charset() or "utf-8", "replace")


def _text(parts: list[str]) -> str | None:
    result = " ".join(" ".join(parts).split())
    return result or None


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _article_id(url: str) -> str:
    match = _ARTICLE_ID_RE.search(urlsplit(url).path)
    if match is None:
        raise ValueError("WeChat URL has no public article id")
    return match.group("article_id")


def _recruitment_type(title: str, content: str) -> str | None:
    text = f"{title}\n{content}"
    if "实习" in text:
        return "实习"
    if any(marker in text for marker in ("社会招聘", "社会招募", "社招")):
        return "社招"
    if any(marker in text for marker in ("校园招聘", "校招", "秋招", "春招")):
        return "校招"
    return None


def parse(url: str, fetch: Callable[[str], str] = fetch_html) -> list[dict[str, object]]:
    """Treat a public WeChat recruitment article as one announcement-level record."""
    article_id = _article_id(url)
    page = fetch(url)
    parser = _ArticleParser()
    parser.feed(page)
    title = _text(parser.title_parts) or parser.meta_title or parser.meta_description
    if not title:
        raise ValueError("WeChat article has no public title")
    content = _text(parser.content_parts)
    if content and len(content) > _MAX_DESCRIPTION_CHARS:
        content = content[:_MAX_DESCRIPTION_CHARS]
        description_truncated = True
    else:
        description_truncated = False
    detail_url = urlunsplit(
        (urlsplit(url).scheme, urlsplit(url).netloc, urlsplit(url).path, urlsplit(url).query, "")
    )
    metadata = {
        "record_kind": "wechat_announcement",
        "article_id": article_id,
        "content_chars": len(content or ""),
    }
    if description_truncated:
        metadata["description_truncated"] = True
    job: dict[str, object] = {
        "source_job_id": article_id,
        "title": title,
        "description": content,
        "locations": [],
        "detail_url": detail_url,
        "apply_url": detail_url,
        "recruitment_type": _recruitment_type(title, content or ""),
        "published_at": _date(parser.publish_time),
        "source_ref": detail_url,
        "metadata": metadata,
    }
    return [job]


__all__ = ["fetch_html", "parse"]
