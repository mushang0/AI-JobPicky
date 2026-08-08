"""Small, reviewable catalog of high-value public recruitment sources."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from jobpicky.contracts.common import JsonObject


@dataclass(frozen=True)
class CompanyProfile:
    group_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    domains: tuple[str, ...]
    platform_family: str
    priority: str = "P1"
    requires_company_name: bool = False

    def matches(self, url: str, company_name: str | None = None) -> bool:
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
        domain_match = any(host == domain or host.endswith(f".{domain}") for domain in self.domains)
        if not domain_match:
            return False
        if not company_name:
            return not self.requires_company_name
        normalized = company_name.casefold().replace(" ", "")
        return any(alias.casefold().replace(" ", "") in normalized for alias in self.aliases)

    def metadata(self) -> JsonObject:
        return {
            "company_group": self.group_id,
            "company_profile": self.canonical_name,
            "platform_family": self.platform_family,
            "profile_priority": self.priority,
        }


COMPANY_PROFILES: tuple[CompanyProfile, ...] = (
    CompanyProfile(
        "alibaba",
        "阿里巴巴集团",
        ("阿里巴巴", "飞猪"),
        ("campus-talent.alibaba.com",),
        "alibaba-campus",
        "P0",
    ),
    CompanyProfile("baidu", "百度", ("百度",), ("talent.baidu.com",), "baidu-campus", "P0"),
    CompanyProfile(
        "tencent",
        "腾讯",
        ("腾讯",),
        ("join.qq.com",),
        "tencent-campus",
        "P0",
    ),
    CompanyProfile(
        "pdd",
        "拼多多集团",
        ("拼多多", "PDD"),
        ("careers.pddglobalhr.com",),
        "pdd-global-hr",
        "P0",
    ),
    CompanyProfile(
        "netease",
        "网易集团",
        ("网易",),
        (
            "campus.163.com",
            "campus.game.163.com",
            "game.campus.163.com",
            "leihuo.163.com",
        ),
        "netease-campus",
        "P0",
    ),
    CompanyProfile(
        "netease",
        "网易集团",
        ("网易", "网易游戏"),
        ("hr.163.com",),
        "netease-hr",
        "P0",
    ),
    CompanyProfile(
        "kuaishou",
        "快手",
        ("快手",),
        ("campus.kuaishou.cn",),
        "kuaishou-campus",
        "P0",
    ),
    CompanyProfile(
        "10jqka",
        "同花顺",
        ("同花顺",),
        ("campus.10jqka.com.cn",),
        "10jqka-campus",
        "P0",
    ),
    CompanyProfile(
        "cscec",
        "中国建筑集团",
        ("中建", "中国建筑"),
        ("1bhr.cscec.com", "recruit.cscec.com", "job.cscec8b.com.cn"),
        "hcm-cloud",
        "P0",
    ),
    CompanyProfile(
        "bcg",
        "BCG波士顿咨询",
        ("BCG", "波士顿咨询"),
        ("careers.bcg.com",),
        "phenom-careers",
        "P0",
    ),
    CompanyProfile(
        "dji",
        "大疆创新",
        ("大疆", "DJI"),
        ("careers.dji.com", "apply.careers.dji.com"),
        "moka-careers",
        "P0",
    ),
    CompanyProfile("byd", "比亚迪", ("比亚迪",), ("job.byd.com",), "byd-campus", "P0"),
    CompanyProfile(
        "li-auto", "理想汽车", ("理想汽车",), ("www.lixiang.com",), "li-auto-campus", "P0"
    ),
    CompanyProfile(
        "meituan",
        "美团",
        ("美团",),
        ("zhaopin.meituan.com",),
        "meituan-campus",
        "P0",
    ),
    CompanyProfile(
        "sf-express",
        "顺丰集团",
        ("顺丰",),
        ("campus.sf-express.com",),
        "sf-express-campus",
        "P0",
    ),
    CompanyProfile(
        "china-mobile",
        "中国移动",
        ("中国移动", "河北移动"),
        ("job.10086.cn",),
        "china-mobile-campus",
        "P0",
    ),
    CompanyProfile(
        "comac",
        "中国商飞",
        ("中国商飞", "上海飞机"),
        ("zhaopin.comac.cc",),
        "comac-campus",
        "P0",
    ),
    CompanyProfile(
        "cib",
        "兴业银行集团",
        ("兴业银行", "兴业国际信托"),
        ("job.cib.com.cn",),
        "cib-careers",
        "P0",
    ),
    CompanyProfile(
        "nanjing-bank",
        "南京银行集团",
        ("南京银行", "南银理财"),
        ("job.njcb.com.cn",),
        "nanjing-bank-careers",
        "P0",
    ),
    CompanyProfile(
        "ningbo-bank",
        "宁波银行",
        ("宁波银行",),
        ("zhaopin.nbcb.com.cn",),
        "ningbo-bank-careers",
        "P0",
    ),
    CompanyProfile("huawei", "华为", ("华为",), ("career.huawei.com",), "huawei-careers"),
    CompanyProfile("xiaomi", "小米", ("小米",), ("xiaomi.jobs.f.mioffice.cn",), "feishu-careers"),
    CompanyProfile("jd", "京东", ("京东",), ("campus.jd.com",), "jd-campus"),
    CompanyProfile("didi", "滴滴", ("滴滴",), ("outreach.didichuxing.com",), "didi-careers"),
    CompanyProfile("oppo", "OPPO", ("OPPO",), ("careers.oppo.com",), "oppo-careers"),
    CompanyProfile(
        "bilibili", "哔哩哔哩", ("哔哩哔哩",), ("jobs.bilibili.com",), "bilibili-careers"
    ),
    CompanyProfile(
        "xiaohongshu", "小红书", ("小红书",), ("job.xiaohongshu.com",), "xiaohongshu-careers"
    ),
    CompanyProfile("ping-an", "中国平安", ("中国平安",), ("campus.pingan.com",), "ping-an-careers"),
    CompanyProfile("zte", "中兴通讯", ("中兴通讯",), ("job.zte.com.cn",), "zte-careers"),
    CompanyProfile(
        "sense-time", "商汤科技", ("商汤科技",), ("hr.sensetime.com",), "sensetime-careers"
    ),
    CompanyProfile(
        "ecoflow",
        "正浩EcoFlow",
        ("正浩", "EcoFlow"),
        ("jobs.ecoflow.com",),
        "feishu-careers",
    ),
    CompanyProfile(
        "papergames",
        "叠纸游戏",
        ("叠纸游戏", "PaperGames"),
        ("career.papegames.com",),
        "feishu-careers",
    ),
    CompanyProfile(
        "hikvision",
        "海康威视",
        ("海康威视",),
        ("campushr.hikvision.com",),
        "hikvision-careers",
    ),
    CompanyProfile("yonyou", "用友", ("用友",), ("career.yonyou.com",), "yonyou-careers"),
    CompanyProfile("icbc", "中国工商银行", ("中国工商银行",), ("job.icbc.com.cn",), "icbc-careers"),
    CompanyProfile("ccb", "中国建设银行", ("中国建设银行",), ("job3.ccb.com",), "ccb-careers"),
    CompanyProfile("spdb", "浦发银行", ("浦发银行",), ("job.spdb.com.cn",), "spdb-careers"),
    CompanyProfile(
        "state-grid",
        "国家电网",
        ("国网", "国家电网"),
        ("zhaopin.zj.sgcc.com.cn",),
        "state-grid-careers",
    ),
    CompanyProfile("sinopec", "中国石化", ("中石化",), ("job.sinopec.com",), "sinopec-careers"),
    CompanyProfile(
        "china-aerospace",
        "中国航天科技集团",
        ("航天科技集团",),
        ("www.spacetalent.com.cn",),
        "china-aerospace-careers",
    ),
    CompanyProfile(
        "china-railway",
        "中国铁路",
        ("中国铁路",),
        ("hr.jntlj.com",),
        "china-railway-careers",
    ),
    CompanyProfile("geely", "吉利科技集团", ("吉利",), ("campus.geely.com",), "geely-careers"),
    CompanyProfile(
        "sonoscape",
        "开立医疗",
        ("开立医疗", "Sonoscape"),
        ("campus.sonoscape.com",),
        "moka-careers",
    ),
    CompanyProfile(
        "fingard",
        "保融科技",
        ("保融科技", "Fingard"),
        ("campus.fingard.com",),
        "moka-careers",
    ),
    CompanyProfile(
        "chery-jlr",
        "奇瑞捷豹路虎",
        ("奇瑞捷豹路虎",),
        ("www.liepin.com",),
        "liepin-company-careers",
        "P1",
        True,
    ),
    CompanyProfile("gree", "格力电器", ("格力",), ("zhaopin.greeyun.com",), "gree-careers"),
)


def find_company_profile(url: str, company_name: str | None = None) -> CompanyProfile | None:
    """Return the first configured profile whose public domain matches ``url``."""
    for profile in COMPANY_PROFILES:
        if profile.matches(url, company_name):
            return profile
    return None


__all__ = ["COMPANY_PROFILES", "CompanyProfile", "find_company_profile"]
