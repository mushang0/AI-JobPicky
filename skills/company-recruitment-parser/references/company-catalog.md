# Known company catalog

This catalog is a prioritization aid, not a reason to fabricate support. Match aliases and domains with the runtime catalog in `src/jobpicky/collection/company_profiles.py`; update both when a verified public source changes.

## P0 groups from the current corpus

| Group | Common labels | Domains | Platform family |
|---|---|---|---|
| Alibaba | 阿里巴巴、飞猪 | `campus-talent.alibaba.com` | alibaba-campus |
| Baidu | 百度、百度-IDG | `talent.baidu.com` | baidu-campus |
| Tencent | 腾讯、腾讯游戏 | `join.qq.com` | tencent-campus |
| PDD | 拼多多、PDD | `careers.pddglobalhr.com` | pdd-global-hr |
| NetEase | 网易、网易游戏、雷火 | `campus.163.com`, `campus.game.163.com`, `leihuo.163.com` | netease-campus |
| NetEase HR | 网易社会招聘 | `hr.163.com` | netease-hr |
| Kuaishou | 快手 | `campus.kuaishou.cn` | kuaishou-campus |
| Tonghuashun | 同花顺 | `campus.10jqka.com.cn` | 10jqka-campus |
| CSCEC | 中建一局、中建八局、中建安装 | `*.cscec.com`, `job.cscec8b.com.cn` | hcm-cloud |
| BCG | BCG中国区、BCG波士顿咨询 | `careers.bcg.com` | phenom-careers |
| DJI | 大疆、DJI | `careers.dji.com`, `apply.careers.dji.com` | moka-careers |
| BYD | 比亚迪、弗迪电池 | `job.byd.com` | byd-campus |
| Li Auto | 理想汽车 | `www.lixiang.com` | li-auto-campus |
| Meituan | 美团、LongCat | `zhaopin.meituan.com` | meituan-campus |
| Huawei | 华为 | `career.huawei.com` | huawei-careers |
| Bilibili | 哔哩哔哩 | `jobs.bilibili.com` | bilibili-careers |
| JD | 京东 | `campus.jd.com` | jd-campus |
| Didi | 滴滴 | `outreach.didichuxing.com` | didi-careers |
| Xiaohongshu | 小红书 | `job.xiaohongshu.com` | xiaohongshu-careers |
| ZTE | 中兴通讯 | `job.zte.com.cn` | zte-careers |
| Yonyou | 用友 | `career.yonyou.com` | yonyou-careers |
| SF Express | 顺丰 | `campus.sf-express.com` | sf-express-campus |
| China Mobile | 中国移动、河北移动 | `job.10086.cn` | china-mobile-campus |
| COMAC | 中国商飞、上海飞机 | `zhaopin.comac.cc` | comac-campus |
| CIB | 兴业银行、兴业信托 | `job.cib.com.cn` | cib-careers |
| Nanjing Bank | 南京银行、南银理财 | `job.njcb.com.cn` | nanjing-bank-careers |
| Ningbo Bank | 宁波银行 | `zhaopin.nbcb.com.cn` | ningbo-bank-careers |

The verified public adapters currently cover Alibaba, Baidu, Tencent, PDD, NetEase campus and HR pages,
Kuaishou, Tonghuashun, OPPO, Huawei, Bilibili, JD, Didi, Xiaohongshu, ZTE, Yonyou, Phenom-backed BCG detail pages, custom-domain Feishu sites for Xiaomi, EcoFlow and
PaperGames, and custom-domain Moka sites for Sonoscape, Fingard, and DJI. Other catalog entries still route
through the conservative public-web fallback until their list and detail contracts are verified.

## P1 groups

Ping An, SenseTime, Hikvision, ICBC, CCB, SPDB, State Grid, Sinopec, China Aerospace, China Railway, Geely, Gree, Mercedes-Benz, L'Oréal, Unity, McKinsey, Roland Berger, and Citadel are present in the corpus and should be configured before they receive custom adapters. Geely's page shell resembles Moka, but its current TLS endpoint is not reproducible by the bounded HTTP client and therefore remains conservative fallback.

## Normalization rules

- Keep `company_group` stable across subsidiaries and campaigns.
- Keep the spreadsheet's original company label in `company_name`.
- Use domain and platform family to choose an adapter; use aliases only to disambiguate shared hosts.
- Do not put query tokens, cookies, or response bodies in this catalog.
