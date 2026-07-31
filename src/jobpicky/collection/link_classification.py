from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit

MOKA = "MOKA"
BEISEN = "BEISEN"
FEISHU = "FEISHU"
HOTJOB = "HOTJOB"
ZHAOPIN = "ZHAOPIN"
JOB_51 = "JOB_51"
GUOPIN = "GUOPIN"
WECHAT = "WECHAT"
EMAIL = "EMAIL"
FORM_OR_SHORT = "FORM_OR_SHORT"
GOVERNMENT_NOTICE = "GOVERNMENT_NOTICE"
COMPANY_RECRUITMENT_SITE = "COMPANY_RECRUITMENT_SITE"
PUBLIC_RECRUITMENT_PORTAL = "PUBLIC_RECRUITMENT_PORTAL"
CUSTOM_RECRUITMENT_SYSTEM = "CUSTOM_RECRUITMENT_SYSTEM"
COMPANY_WEBSITE = "COMPANY_WEBSITE"
UNKNOWN = "UNKNOWN"

_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_FORM_PATH_RE = re.compile(r"/(?:form|forms|survey|questionnaire)(?:/|$)", re.IGNORECASE)
_NESTED_URL_KEYS = {
    "jumpurl",
    "next",
    "redirect",
    "redirect_uri",
    "returnurl",
    "targeturl",
    "url",
}
_FORM_OR_SHORT_ROOTS = {
    "bsurl.cn",
    "bit.ly",
    "dqr.cn",
    "docs.google.com",
    "docs.popo.netease.com",
    "f.kdocs.cn",
    "f.wps.cn",
    "forms.office.com",
    "is.gd",
    "jinshuju.net",
    "jsj.top",
    "jsjform.com",
    "send2me.cn",
    "t.cn",
    "t.co",
    "tinyurl.com",
    "url.cn",
    "wj.toutiao.com",
    "wjx.cn",
    "wjx.com",
    "wjx.top",
}
_CUSTOM_RECRUITMENT_ROOTS = {
    "ciicscjob.com",
    "exam-sp.com",
    "hersingdat.com",
    "hire66.com",
    "izhanchi.com",
    "pzhl.net",
    "recruitee.com",
    "sun-hrm.com",
    "tupu360.com",
    "wscloud.kingdee.com",
}
_BEISEN_CUSTOM_ROOTS = {
    "campus.boe.com",
    "career.h3c.com",
    "career.mindray.com",
    "career.naura.com",
    "career.shenzhouintl.com",
    "careers.mxbc.com",
    "careers.narwal.com",
    "hr-campus.vivo.com",
    "job.lzlj.com",
    "sunzhaopin.sinosig.com",
    "we.zyt.com",
    "zhaopin.xa.com",
    "zhaopin.xdf.cn",
}
_PUBLIC_RECRUITMENT_ROOTS = {
    "cqrc.net",
    "czrsj.cn",
    "fzrsrc.cn",
    "gxrc.com",
    "hbggzp.cn",
    "ncrczpw.com",
    "qgsydw.com",
    "yingjiesheng.com",
}
_GOVERNMENT_HOST_MARKERS = ("gzw.", "mohrss.", "rsj.", "rsc.", "hrss.")
_GOVERNMENT_PATH_MARKERS = (
    "gqzp",
    "notice",
    "rcdw",
    "rczp",
    "recruit",
    "renshi",
    "rencai",
    "talent",
    "tzgg",
    "zhaopin",
)
_COMPANY_RECRUITMENT_MARKERS = (
    "apply",
    "career",
    "campus",
    "hr",
    "job",
    "join",
    "outreach",
    "recruit",
    "talent",
    "zhaopin",
)


def _is_root_or_subdomain(host: str, root: str) -> bool:
    return host == root or host.endswith(f".{root}")


def _has_email(text: str) -> bool:
    return bool(_EMAIL_RE.search(text))


def _is_government_notice(host: str, path: str) -> bool:
    if not host.endswith(".gov.cn"):
        return False
    haystack = f"{host}{path}".lower()
    return any(marker in haystack for marker in _GOVERNMENT_HOST_MARKERS + _GOVERNMENT_PATH_MARKERS)


def _is_obvious_form(host: str, path: str) -> bool:
    return host.startswith("form.") or bool(_FORM_PATH_RE.search(path))


def _classify_http(parts, *, inspect_nested: bool) -> str:
    host = parts.hostname.lower().rstrip(".")
    if inspect_nested:
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() not in _NESTED_URL_KEYS:
                continue
            try:
                nested = urlsplit(value)
            except ValueError:
                continue
            if nested.scheme not in {"http", "https"} or not nested.hostname:
                continue
            nested_type = _classify_http(nested, inspect_nested=False)
            if nested_type != UNKNOWN:
                return nested_type

    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return UNKNOWN

    if _is_root_or_subdomain(host, "mokahr.com"):
        return MOKA
    if _is_root_or_subdomain(host, "beisen.com") or _is_root_or_subdomain(host, "zhiye.com"):
        return BEISEN
    if _is_root_or_subdomain(host, "jobs.feishu.cn"):
        return FEISHU
    if _is_root_or_subdomain(host, "hotjob.cn"):
        return HOTJOB
    if _is_root_or_subdomain(host, "zhaopin.com"):
        return ZHAOPIN
    if _is_root_or_subdomain(host, "51job.com"):
        return JOB_51
    if _is_root_or_subdomain(host, "iguopin.com"):
        return GUOPIN
    if _is_root_or_subdomain(host, "weixin.qq.com"):
        return WECHAT
    if any(_is_root_or_subdomain(host, root) for root in _BEISEN_CUSTOM_ROOTS):
        return BEISEN
    if any(_is_root_or_subdomain(host, root) for root in _CUSTOM_RECRUITMENT_ROOTS):
        return CUSTOM_RECRUITMENT_SYSTEM
    if _is_government_notice(host, parts.path):
        return GOVERNMENT_NOTICE
    if any(_is_root_or_subdomain(host, root) for root in _PUBLIC_RECRUITMENT_ROOTS):
        return PUBLIC_RECRUITMENT_PORTAL
    if any(_is_root_or_subdomain(host, root) for root in _FORM_OR_SHORT_ROOTS) or _is_obvious_form(
        host, parts.path
    ):
        return FORM_OR_SHORT
    if any(marker in f"{host}{parts.path}".lower() for marker in _COMPANY_RECRUITMENT_MARKERS):
        return COMPANY_RECRUITMENT_SITE
    if host.startswith("www."):
        return COMPANY_WEBSITE
    return UNKNOWN


def classify_link(url: str) -> str:
    """Classify a link without changing its original URL text."""
    if not isinstance(url, str) or not url.strip():
        return UNKNOWN

    text = url.strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return UNKNOWN

    if parts.scheme in {"http", "https"} and parts.hostname:
        return _classify_http(parts, inspect_nested=True)
    if parts.scheme == "mailto" or _has_email(text):
        return EMAIL
    return UNKNOWN


__all__ = ["classify_link"]
