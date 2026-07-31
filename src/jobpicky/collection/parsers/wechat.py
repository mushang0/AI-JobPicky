from __future__ import annotations

import gzip
import re
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from jobpicky.collection.link_classification import classify_link

_ARTICLE_ID_RE = re.compile(r"/(?:s|mp/appmsg/show)/(?P<article_id>[A-Za-z0-9_-]+)")
_URL_RE = re.compile(r"(?i)(?:https?://|//)[^\s<>\"']+")
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_MAX_HTML_BYTES = 8 * 1024 * 1024
_MAX_FETCH_ATTEMPTS = 3
_MAX_DESCRIPTION_CHARS = 80_000
_TRAILING_PUNCTUATION = "，,；;。！？!?)]}>'\""
_BLOCK_TAGS = {
    "br",
    "dd",
    "div",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "section",
    "td",
    "th",
    "tr",
}
_APPLICATION_MARKERS = (
    "投递",
    "报名",
    "申请",
    "网申",
    "应聘",
    "简历",
    "招聘链接",
    "报名链接",
    "投递方式",
    "报名方式",
)
_QR_MARKERS = ("二维码", "扫码", "扫描", "长按识别", "识别二维码")
_WECHAT_CONTACT_MARKERS = ("微信号", "加微信", "添加微信", "联系微信", "微信联系")


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.content_parts: list[str] = []
        self.blocks: list[str] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.meta_title: str | None = None
        self.meta_description: str | None = None
        self.publish_time: str | None = None
        self._title_depth = 0
        self._content_depth = 0
        self._skip_depth = 0
        self._publish_depth = 0
        self._block_parts: list[str] = []
        self._link_stack: list[dict[str, object]] = []

    def _flush_block(self) -> None:
        text = _text(self._block_parts)
        if text:
            self.blocks.append(text)
        self._block_parts.clear()

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
        if self._content_depth and tag in _BLOCK_TAGS:
            self._flush_block()
        if self._content_depth and tag == "a":
            self._link_stack.append({"href": attributes.get("href") or "", "text": []})
        if self._content_depth and tag == "img":
            image_url = (
                attributes.get("data-src")
                or attributes.get("data-original")
                or attributes.get("src")
            )
            if image_url:
                self.images.append({"url": image_url, "alt": attributes.get("alt") or ""})
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
        if tag == "a" and self._link_stack:
            link = self._link_stack.pop()
            href = link.get("href")
            if isinstance(href, str) and href.strip():
                text = link.get("text")
                self.links.append(
                    {
                        "href": href.strip(),
                        "text": (_text(text) or "") if isinstance(text, list) else "",
                    }
                )
        if self._content_depth and tag in _BLOCK_TAGS:
            self._flush_block()
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
            self._block_parts.append(data)
            for link in self._link_stack:
                text = link.get("text")
                if isinstance(text, list):
                    text.append(data)
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
    for attempt in range(1, _MAX_FETCH_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - public article URL
                body = response.read(_MAX_HTML_BYTES + 1)
                if len(body) > _MAX_HTML_BYTES:
                    raise ValueError("WeChat article exceeds the safe response limit")
                if body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
                return body.decode(response.headers.get_content_charset() or "utf-8", "replace")
        except HTTPError:
            raise
        except (URLError, TimeoutError, OSError):
            if attempt == _MAX_FETCH_ATTEMPTS:
                raise
            sleep(0.25 * attempt)
    raise RuntimeError("unreachable WeChat fetch state")


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


def _normalise_link(value: str, article_url: str) -> str | None:
    candidate = value.strip().rstrip(_TRAILING_PUNCTUATION)
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    candidate = urljoin(article_url, candidate)
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _is_same_article(candidate: str, article_url: str) -> bool:
    candidate_parts = urlsplit(candidate)
    article_parts = urlsplit(article_url)
    same_host = (candidate_parts.hostname or "").casefold() == (
        article_parts.hostname or ""
    ).casefold()
    return same_host and candidate_parts.path == article_parts.path


def _application_signal(text: str) -> bool:
    return any(marker in text for marker in _APPLICATION_MARKERS)


def _content_shape(title: str, content: str, blocks: list[str]) -> str:
    recruitment_markers = sum(
        content.count(marker) for marker in ("招聘岗位", "岗位需求", "招聘职位", "职位需求")
    )
    if recruitment_markers >= 2 or any(
        marker in content for marker in ("岗位一览", "职位列表", "招聘岗位如下")
    ):
        return "multi_job_candidate"
    if len(blocks) >= 3 and any(marker in title for marker in ("招聘", "招募", "岗位")):
        return "structured_announcement"
    return "announcement"


def _application_methods(
    article_url: str, content: str, links: list[dict[str, str]], images: list[dict[str, str]]
) -> tuple[list[dict[str, object]], str | None]:
    methods: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    application_signal = _application_signal(content)

    def add_method(method: dict[str, object]) -> None:
        key = (str(method.get("type")), str(method.get("value")))
        if key not in seen:
            seen.add(key)
            methods.append(method)

    for link in links:
        href = link.get("href", "")
        if href.casefold().startswith(("javascript:", "data:", "tel:")):
            continue
        if href.casefold().startswith("mailto:"):
            email = href[7:].split("?", 1)[0].strip()
            if _EMAIL_RE.fullmatch(email):
                add_method(
                    {"type": "email", "value": email, "source": "anchor", "confidence": "high"}
                )
            continue
        candidate = _normalise_link(href, article_url)
        if candidate is None or _is_same_article(candidate, article_url):
            continue
        link_type = classify_link(candidate)
        if link_type == "WECHAT":
            continue
        add_method(
            {
                "type": "url",
                "value": candidate,
                "source": "anchor",
                "link_type": link_type,
                "confidence": "high" if application_signal else "medium",
            }
        )

    for raw_url in _URL_RE.findall(content):
        candidate = _normalise_link(raw_url, article_url)
        if candidate is None or _is_same_article(candidate, article_url):
            continue
        link_type = classify_link(candidate)
        if link_type == "WECHAT":
            continue
        add_method(
            {
                "type": "url",
                "value": candidate,
                "source": "text",
                "link_type": link_type,
                "confidence": "high" if application_signal else "medium",
            }
        )

    for email in _EMAIL_RE.findall(content):
        add_method({"type": "email", "value": email, "source": "text", "confidence": "high"})

    if any(marker in content for marker in _QR_MARKERS) and images:
        add_method(
            {
                "type": "qr_candidate",
                "value": None,
                "source": "image",
                "image_count": len(images),
                "confidence": "medium",
            }
        )
    if any(marker in content for marker in _WECHAT_CONTACT_MARKERS):
        add_method({"type": "wechat_contact", "value": None, "source": "text", "confidence": "low"})
    if not methods and application_signal:
        add_method(
            {
                "type": "unknown",
                "value": None,
                "source": "text",
                "confidence": "low",
                "reason": "application_instruction_without_resolved_entry",
            }
        )

    url_methods = [method for method in methods if method.get("type") == "url"]
    apply_url = None
    if len(url_methods) == 1:
        candidate_method = url_methods[0]
        if (
            candidate_method.get("confidence") == "high"
            or candidate_method.get("link_type") != "COMPANY_WEBSITE"
        ):
            value = candidate_method.get("value")
            apply_url = value if isinstance(value, str) else None
    return methods, apply_url


def _application_status(methods: list[dict[str, object]]) -> str:
    types = {str(method.get("type")) for method in methods}
    if not types:
        return "not_found"
    if len(types) > 1:
        return "mixed"
    only_type = next(iter(types))
    return {
        "url": "direct_url",
        "email": "email",
        "qr_candidate": "qr",
        "wechat_contact": "wechat_contact",
        "unknown": "unknown",
    }.get(only_type, "unknown")


def _review_reasons(content_shape: str, methods: list[dict[str, object]]) -> list[str]:
    reasons: list[str] = []
    if content_shape == "multi_job_candidate":
        reasons.append("multi_job_candidate")
    if not methods:
        reasons.append("no_application_method")
    if len(methods) > 1:
        reasons.append("multiple_application_methods")
    if any(method.get("type") == "qr_candidate" for method in methods):
        reasons.append("qr_requires_decode")
    if any(method.get("type") == "unknown" for method in methods):
        reasons.append("unresolved_application_method")
    if any(method.get("confidence") != "high" for method in methods):
        reasons.append("low_confidence_application_method")
    return reasons


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
    parser._flush_block()
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
    application_methods, apply_url = _application_methods(
        detail_url, content or "", parser.links, parser.images
    )
    application_types = sorted({str(method["type"]) for method in application_methods})
    content_shape = _content_shape(title, content or "", parser.blocks)
    review_reasons = _review_reasons(content_shape, application_methods)
    metadata = {
        "record_kind": "wechat_announcement",
        "article_id": article_id,
        "content_chars": len(content or ""),
        "content_shape": content_shape,
        "application_status": _application_status(application_methods),
        "application_types": application_types,
        "application_methods": application_methods,
        "review_reasons": review_reasons,
        "needs_review": bool(review_reasons),
    }
    if description_truncated:
        metadata["description_truncated"] = True
    job: dict[str, object] = {
        "source_job_id": article_id,
        "title": title,
        "description": content,
        "locations": [],
        "detail_url": detail_url,
        "apply_url": apply_url,
        "recruitment_type": _recruitment_type(title, content or ""),
        "published_at": _date(parser.publish_time),
        "source_ref": detail_url,
        "metadata": metadata,
    }
    return [job]


__all__ = ["fetch_html", "parse"]
