from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

COMPANY_NATURE_VALUES = (
    "央企",
    "国企",
    "事业单位",
    "政府/公共机构",
    "民营企业",
    "外资企业",
    "合资企业",
    "其他",
)
RECRUITMENT_TYPE_VALUES = ("校招", "社招", "实习")
EDUCATION_VALUES = ("高中及以下", "专科", "本科", "硕士", "博士")

_SPACE_RE = re.compile(r"\s+")
_LOCATION_SEPARATOR_RE = re.compile(r"[,，、;/；|]+")
_UNKNOWN_VALUES = {"", "-", "--", "/", "不详", "未知", "待定"}
_CAMPUS_RECRUITMENT_MARKERS = (
    "校招",
    "校园",
    "应届",
    "春招",
    "秋招",
    "提前批",
    "补招",
)

_COMPANY_NATURE_ALIASES = {
    "央企": "央企",
    "中央企业": "央企",
    "中央国有企业": "央企",
    "国企": "国企",
    "国有企业": "国企",
    "地方国企": "国企",
    "地方国有企业": "国企",
    "事业单位": "事业单位",
    "政府/公共机构": "政府/公共机构",
    "政府公共机构": "政府/公共机构",
    "政府机构": "政府/公共机构",
    "公共机构": "政府/公共机构",
    "民营企业": "民营企业",
    "民营": "民营企业",
    "民企": "民营企业",
    "私企": "民营企业",
    "私营企业": "民营企业",
    "外资企业": "外资企业",
    "外企": "外资企业",
    "外商独资": "外资企业",
    "外商独资企业": "外资企业",
    "合资企业": "合资企业",
    "合资": "合资企业",
    "其他": "其他",
    "其它": "其他",
}


def normalize_text(value: str) -> str:
    """Normalize display text without changing its letter case."""
    return _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def normalize_search_text(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_text(value) or None


def normalize_tags(values: Iterable[str]) -> list[str]:
    """Normalize and case-insensitively deduplicate user-entered labels."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def normalize_city(value: str | None) -> str | None:
    if value is None:
        return None
    display = normalize_text(value)
    key = _compact(display)
    if key in _UNKNOWN_VALUES or key in {
        "不限",
        "城市不限",
        "地点不限",
        "工作地点不限",
    }:
        return None
    if key.casefold() in {"remote", "workfromhome"} or key in {
        "线上",
        "在线",
        "居家办公",
        "远程",
        "远程办公",
    }:
        return "远程"
    if key in {"全国", "全国各地", "全国多地", "全国范围"}:
        return "全国"
    if len(key) > 1 and key.endswith("市"):
        return key[:-1]
    return display


def normalize_locations(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in _LOCATION_SEPARATOR_RE.split(normalize_text(value)):
            city = normalize_city(part)
            if city is None:
                continue
            key = city.casefold()
            if key not in seen:
                seen.add(key)
                result.append(city)
    return result


def normalize_company_nature(value: str | None) -> str | None:
    if value is None:
        return None
    return _COMPANY_NATURE_ALIASES.get(_compact(value))


def normalize_recruitment_type(value: str | None) -> str | None:
    if value is None:
        return None
    key = _compact(value)
    if key in _UNKNOWN_VALUES or key == "不限":
        return None
    matches = {
        canonical
        for canonical, matched in (
            ("校招", any(marker in key for marker in _CAMPUS_RECRUITMENT_MARKERS)),
            ("社招", any(marker in key for marker in ("社招", "社会招聘"))),
            ("实习", "实习" in key),
        )
        if matched
    }
    return matches.pop() if len(matches) == 1 else None


def normalize_education(value: str | None) -> str | None:
    if value is None:
        return None
    key = _compact(value)
    if key in _UNKNOWN_VALUES or key in {"不限", "无要求", "不要求"}:
        return None
    if any(
        marker in key
        for marker in (
            "学历不限",
            "学历无要求",
            "学历不要求",
            "无学历要求",
            "不限学历",
        )
    ):
        return None

    # Protect the two unambiguous compound terms before treating bare
    # "研究生" as unknown.
    key = key.replace("博士研究生", "博士").replace("硕士研究生", "硕士")
    levels = (
        ("高中及以下", ("高中", "中专", "中职", "技校", "初中", "小学")),
        ("专科", ("专科", "大专")),
        ("本科", ("本科", "学士")),
        ("硕士", ("硕士",)),
        ("博士", ("博士",)),
    )
    for canonical, markers in levels:
        if any(marker in key for marker in markers):
            return canonical
    return None


def _compact(value: str) -> str:
    return _SPACE_RE.sub("", unicodedata.normalize("NFKC", value)).strip()


__all__ = [
    "COMPANY_NATURE_VALUES",
    "EDUCATION_VALUES",
    "RECRUITMENT_TYPE_VALUES",
    "normalize_city",
    "normalize_company_nature",
    "normalize_education",
    "normalize_locations",
    "normalize_recruitment_type",
    "normalize_search_text",
    "normalize_tags",
    "normalize_text",
]
