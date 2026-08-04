"""Known-company dispatch followed by the conservative public-web fallback."""

from __future__ import annotations

from collections.abc import Callable

from ..company_profiles import find_company_profile
from .alibaba import parse as parse_alibaba
from .baidu import parse as parse_baidu
from .feishu import parse as parse_feishu
from .jqka import parse as parse_jqka
from .kuaishou import parse as parse_kuaishou
from .moka import parse as parse_moka
from .netease import parse as parse_netease
from .pdd import parse as parse_pdd
from .phenom import parse as parse_phenom
from .public_web import parse as parse_public_web
from .tencent import parse as parse_tencent

_PLATFORM_PARSERS: dict[str, Callable[[str], list[dict[str, object]]]] = {
    "10jqka-campus": parse_jqka,
    "alibaba-campus": parse_alibaba,
    "baidu-campus": parse_baidu,
    "feishu-careers": parse_feishu,
    "kuaishou-campus": parse_kuaishou,
    "moka-careers": parse_moka,
    "netease-hr": parse_netease,
    "netease-campus": parse_netease,
    "pdd-global-hr": parse_pdd,
    "phenom-careers": parse_phenom,
    "tencent-campus": parse_tencent,
}


def parse(url: str) -> list[dict[str, object]]:
    """Use a verified platform adapter before generic public-page discovery."""
    profile = find_company_profile(url)
    if profile is not None:
        parser = _PLATFORM_PARSERS.get(profile.platform_family)
        if parser is not None:
            return parser(url)
    return parse_public_web(url, require_description=True)


__all__ = ["parse"]
