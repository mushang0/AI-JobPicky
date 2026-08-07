# 招聘平台解析手册

只记录已由代码、脱敏 Fixture 和公开页面验证的结论。调查后同步修正入口、分页、字段、
坑点和边界；实现细节以解析器源码为准。

## 维护流程

1. 先排除链接误分类，再判断是否能扩展现有解析器。
2. 数据入口依次尝试：公开 API、内嵌 JSON、服务端 HTML、JavaScript 渲染 DOM。
3. 命令行和代码无法确认运行时结构时，才用浏览器控制技能探索；它不能进入生产或批量
   流程。需要 JavaScript 时优先使用可部署的无头浏览器 CLI。
4. 无法证明分页完整或空列表真实性时，保持采集不完整。
5. Fixture 只保留解析所需结构并脱敏；大型 JSON、CSV 和产物先看汇总、键和少量行，
   不全量输出到终端或模型上下文。

缺口汇总：

```bash
uv run python scripts/report_parser_gaps.py <csv> --limit-rows 20
```

跨平台人工回放：

```bash
uv run python scripts/verify_parser_pipeline.py \
  --platform <PLATFORM> --limit <N> --input <csv> --output <artifact-dir>
```

先小样本验证；确需全量时用 `--limit 0`，完成后先看 `summary.json`。北森专用脚本额外
保存脱敏前的接口响应并支持行区间定位，仅在诊断北森时使用。

批量采集默认按来源使用 4 路有界并发（上限 8 路），同一来源内仍按解析器顺序处理；可用
`JOBPICKY_COLLECTION_WORKERS=1..8` 调整。验证脚本也支持 `--workers 1..8`。

## 北森（BEISEN）

- 域名：`beisen.com`、`zhiye.com`。
- 新版：从页面读取 `BSGlobal.PortalId`，调用 `POST /api/Jobad/GetJobAdPageList`。
- 旧移动版：`GET /JobAd/_SearchJobAd` 列表，再调用 `GET /JobAd/_Info`。
- 无直接列表时按路径回退 `/campus/jobs`、`/social/jobs`、`/intern/jobs`；三类岗位不能
  互相补位。
- `Duty` 与 `Require` 合并；带 `jobAdId` 的链接只保留目标岗位。
- 旧移动链接的 `ky` 混入 `=` 时清空；异常年份不写入事实。
- 单次上限 1000 条，触顶或空列表都不能单独证明完整。
- 回归：`tests/collection/test_beisen_parser.py`。

## 飞书招聘（FEISHU）

- 域名：`jobs.feishu.cn`；详情路径：
  `/<站点路径>/position/<数字ID>/detail`。
- 详情使用公开 `GET /api/v1/job/posts/<ID>`；请求头 `website-path` 必须取 URL 第一段
  路径，否则可能命中错误租户状态。
- 职责与要求合并为 JD；解析地点、招聘类型、发布时间、部门和分类。
- `channel_online_status=0` 表示岗位关闭；跳过关闭岗位，不记为开放岗位。
- 学历目前只有未确认的数值代码，保存在 metadata，不猜文本。
- 列表接口需要前端 `_signature`，不复制混淆签名。使用 Chromium CLI 执行官网
  JavaScript、提取详情链接；详情仍走 HTTP API。
- 列表按 `current`、`limit=100` 翻页并去重；无新链接或不足一页时停止。
- 首页可能只渲染“职位”导航，真实岗位列表在同域 `/position/list`；也可能直接渲染
  “招聘项目”和岗位卡片。先从渲染后的 DOM 或页面配置发现详情链接，没有详情链接时再
  跟进列表路由；不写死租户 ID 或 `spread` 值。默认继承入口查询参数；若继承的岗位筛选
  导致列表为空，再移除 `project`、`keywords` 等列表状态参数重试，但保留 `spread` 等
  追踪参数。
- 详情默认 16 路线程并发，`JOBPICKY_FEISHU_WORKERS` 可在 1–32 之间调节；遇限流时
  降低，不做无界并发。
- Chromium 通过 `JOBPICKY_CHROMIUM_PATH` 配置；缺失或渲染超时应明确失败。
- 2026-07-31 重跑样本：33 个来源中 31 个成功，本轮快照解析并校验 1901 个岗位；它石
  智航入口因失效项目筛选由无筛选兜底恢复，剩余失败为一次详情请求超时和一个关闭岗位。
- Fixture：`tests/collection/fixtures/feishu_detail.json`；回归：
  `tests/collection/test_feishu_parser.py`。

## Hotjob 招聘（HOTJOB）

- 域名：`hotjob.cn`；同一类型下同时存在 `wecruit` 的 PB/MC 套件、租户根入口、现代
  移动站和旧式 `/wt/` 页面，不能只按链接路径选择一种接口。
- 新套件使用公开表单 `POST /wecruit/positionInfo/listPosition/<suite>`，请求体的
  `recruitType` 使用数字代码（1 校招、2 社招、12 实习、13 海外）；详情使用同域
  `POST /wecruit/positionInfo/listPositionDetail/<suite>`。请求体必须是
  `application/x-www-form-urlencoded`，不能发送 JSON。
- 现代移动站从公开 HTML 的脚本配置读取套件和公开请求头，再用 GET 列表接口；不执行
  浏览器 JavaScript。租户根入口先调用 `wecruit/common/getSLD`，HTTP 入口失败时只重试
  同域 HTTPS；根入口没有招聘类型时按公开接口逐类探测，但不把空列表当成成功。
- 列表按 `totalPage` 翻页并去重，最多 200 页；详情请求默认 8 路并发，
  `JOBPICKY_HOTJOB_WORKERS` 可在 1–16 之间调节。详情暂时不可用时保留列表中已确认的
  岗位事实，并在 metadata 写入 `detail_status=unavailable-fallback`；详情明确返回关闭
  状态时不把它当成新的开放事实。
- 旧式 `/wt/` 页面从服务端 HTML 中读取公开列表/详情接口路径和 `recruitType`，再按
  `pageCount` 读取 JSON；接口中的 `operational` 参数只在运行时从当前页面读取，不写入
  Fixture 或代码。
- 当前样本全量回放：59 个来源中 52 个成功，3853 个岗位通过 schema 校验。剩余 7 个
  为公开接口明确关闭的官网、已失效/关闭的直达岗位，或当前实习入口确实返回空列表；不
  用其他招聘类型的岗位替代这些链接。
- Fixture：`tests/collection/fixtures/hotjob_list.json`、`hotjob_detail.json`；回归：
  `tests/collection/test_hotjob_parser.py`。

## 前程无忧（JOB_51）

- 公开入口分为校园静态页、`jobs.51job.com` 详情页、`xyz.51job.com` 报名页和部分
  `xyzp.51job.com` 单页应用。优先从 URL 直接取岗位 ID 调用公开 `job_detail.php`，再从
  页面及同域公开脚本发现 `ctmid`，调用 `job_list.php`；列表按返回总数有限翻页并去重。
- `coapi` 的签名材料只从当前公开客户端脚本运行时提取，不把页面中可见的客户端字符串写
  入代码或 Fixture；请求保持无登录态、限时和响应大小上限。静态页内嵌的 JSON/JavaScript
  岗位数组、报名链接和公开详情 ID 作为 API 为空时的通用回退；不执行页面脚本。
- 对单页应用，解析公开 bundle 中明确的岗位名称、职责、地点和学历字段；对只有招聘说明
  的公开页，最多生成一条公告级记录，并在 metadata 标注 `record_kind`，不把公告标题拆成
  未验证的岗位。带登录、消费者投递页、公开接口空列表、WAF 公司页保持失败。
- 入口带跟踪 query 且返回 405 时，只重试去掉 query 的同一路径；岗位 ID 或 `ctmid` 已由
  URL 提供时不会因页面跳转到登录而放弃公开列表/详情。公开岗位状态原样保存在 metadata，
  不依据未确认的数字状态码关闭历史岗位。
- 当前样本全量回放：30 个去重来源中 21 个成功，1010 个岗位/公告记录通过 schema 校验。
  其余 9 个为登录入口、公开接口明确为空，或被 WAF 保护的公司职位页；不绕过访问控制。
- Fixture：`tests/collection/fixtures/job_51_detail.json`、`job_51_static.html`；回归：
  `tests/collection/test_job_51_parser.py`。

## Moka 招聘（MOKA）

- 域名：`mokahr.com`；常见入口包括 `/campus-recruitment/`、`/social-recruitment/`、
  `/campus_apply/`、`/apply/`，以及会公开重定向到这些入口的 `/su/` 和推荐投递链接。
- 页面服务端内嵌 `<input id="init-data">` JSON，包含站点信息和岗位列表；解析器优先使用
  该公开数据，直达链接按 URL fragment 的 `job/<id>` 精确筛选，列表链接返回所有公开开放
  岗位。关闭状态不返回；部分岗位重新开放后仍保留旧的 `closedAt`，以当前 `status=open`
  或 `openedAt > closedAt` 识别为重新开放。
- 同一 `(mode, org, site)` 的列表入口按一个招聘源处理，`sourceToken` 和 `#/jobs` 等前端列表
  状态不制造新的来源；`#/job/<id>` 直达岗位仍保留为独立验证入口。
- Moka 详情接口的公开响应为加密数据；当前只写入内嵌清单已经确认的标题、地点、状态、
  部门和时间，不把密钥、IV、密文或浏览器登录流程带入批处理。因而 `description` 可能为
  空，这是已知字段边界，不用表格摘要冒充 JD。
- 页面偶发自重定向；解析器使用带 CookieJar 的有限手动重试，最多 5 次，不跟随到登录、
  验证码或其他站点。HTML 响应上限为 10 MiB。
- 当前样本全量回放：93 个来源中 82 个成功，758 个岗位通过 schema 校验。剩余 11 个为
  当前站点没有开放岗位，或直达岗位已关闭/不在公开首屏清单；不把其他岗位替换为失效直达
  岗位。
- Fixture：`tests/collection/fixtures/moka_init_data.html`；回归：
  `tests/collection/test_moka_parser.py`。

## 微信公众文章（WECHAT）

- 主要入口是 `mp.weixin.qq.com/s/<article-id>`；解析器读取公开 HTML 中的
  `#activity-name`、`#js_content` 和公开发布时间，不执行文章脚本，也不调用登录态接口。
- 正文保留段落边界，并提取公开锚点链接、明文 URL、邮箱和二维码图片候选；链接只保留
  `http(s)`，不执行 `javascript:`、电话链接或表单提交。候选入口写入 metadata 的
  `application_methods`，并标注 `application_status`、`content_shape`、`review_reasons`。
- 一篇文章默认对应一条“公告级岗位信息”记录，`source_job_id` 使用文章 ID；多个职位只
  标记为 `multi_job_candidate`，证据不足时不臆拆成多个岗位。标题中可明确识别 `校招`、
  `社招`、`实习` 时才写 recruitment type，地点留给表格事实回退。
- 只有正文明确发现一个高置信度投递 URL 时才写 `apply_url`；邮箱、二维码、微信联系和
  未解析入口不伪造 URL，文章地址只保留在 `detail_url`/`source_ref`。
- 正文最多保留 80,000 字，超出时 metadata 标记 `description_truncated`；HTML 响应最多
  8 MiB。`weixin.qq.com/r/...`、企业微信个人页和在线表单不是公众文章，保持明确失败，
  不把入口页当成岗位事实。
- 2026-07-31 全量回放：422 个去重来源中 405 个成功、17 个失败；成功记录中 227 个为
  普通公告、156 个为结构化公告、22 个为多岗位候选。记录覆盖的投递方式包括邮箱 130
  个、二维码候选 65 个、微信联系 8 个和 URL 22 个；分类结果见回放目录的 `summary.json`。
- Fixture：`tests/collection/fixtures/wechat_article.html`；回归：
  `tests/collection/test_wechat_parser.py`。

## 公司招聘网站（COMPANY_RECRUITMENT_SITE）

- 先复用已验证的平台分类：`campus.boe.com`、`zhaopin.xdf.cn`、
  `sunzhaopin.sinosig.com`、`we.zyt.com`、`career.h3c.com`、`career.mindray.com`、
  `career.naura.com`、`career.shenzhouintl.com`、`careers.mxbc.com`、
  `careers.narwal.com`、`hr-campus.vivo.com`、`job.lzlj.com` 和 `zhaopin.xa.com` 的公开页面
  使用北森页面模板，统一转到北森解析器；站点无岗位时仍保持失败。
- 其余来源使用通用公开网页解析器：优先读取 `JobPosting` JSON-LD、公开内嵌 JSON 和服务端
  岗位链接；若首页只有“校园招聘/职位/招聘”入口，会再跟随一层公开导航，并从有限数量的同页
  公开脚本中发现岗位列表 API。只调用公开 GET 列表接口，不执行页面脚本、不提交表单、不绕过登录。
- 列表只有标题时，解析器会从脚本明确暴露的公开详情 API 或详情页补齐 JD；详情路由和岗位数量
  都有上限，避免错误候选 URL 放大请求。`COMPANY_RECRUITMENT_SITE` 路由要求最终必须有
  `description`，所以“只有列表没有 JD”的来源不会被计为成功；其他复用该解析器的类型会保留
  `needs_review` 标记供复核。
- 前端懒加载但没有公开 GET 详情、需要登录/验证码/WAF、或 Moka 等返回加密详情的站点保持失败，
  不把列表摘要、宣传页或浏览器渲染结果冒充稳定 JD。浏览器只用于调查页面链路，批处理仍使用确定性
  HTTP/API 解析。理想汽车、Sicarrier、长亭科技已验证可分别获得岗位和 JD。
- 已增加公司画像目录 `src/jobpicky/collection/company_profiles.py`：先按规范化公司组和招聘平台
  归类，再选择平台适配器；共享平台不按公司复制解析器。当前已验证七个高价值公共接口来源族，另有一个
  已验证的 Phenom 嵌入数据来源族：
  - 阿里巴巴 `campus-talent.alibaba.com`：`POST /position/search` 按 `pageIndex` 分页，入口页面提供公开
    CSRF 引导 token；解析器只在内存中保留匿名 cookie/token，调用 `POST /position/detail` 补齐缺失 JD，保留
    `batchId` 与 `filterParams`，不把无效筛选静默降级成全量列表。
  - 百度 `talent.baidu.com`：`POST /httservice/getPostListNew` 按 `curPage` 分页（每页上限 10），
    `GET /httservice/getPostDetail?postId=...&recruitType=...` 获取公开 JD；保留 `recruitType`、`projectType`
    和搜索词筛选，不能把 SSR 的首屏 10 条误当成全量。
  - 腾讯 `join.qq.com`：`POST /api/v1/position/searchPosition` 获取列表，`GET
    /api/v1/jobDetails/getJobDetailsByPostId?postId=...` 获取公开 JD，使用 `postId` 作为稳定来源 ID。
  - 同花顺 `campus.10jqka.com.cn`：`GET /api/v3/school_recruitment/apply/apply_list` 分页，
    `GET /api/v3/school_recruitment/apply/apply_detail?id=...` 获取 `intro` 与 `requirement`；空数组
    过滤参数不能发送，否则会把公开列表误判为空。
  - 拼多多 `careers.pddglobalhr.com`：`POST /api/careers/api/recruit/position/list` 与
    `POST /api/careers/api/recruit/position/detail`；带 `positionId` 的直达链接只解析目标岗位，不扩展为
    公司全量列表。
  - 网易校园 `campus.163.com` / `campus.game.163.com`：从入口 query 的 `id` 取得项目，调用
    `GET /api/campuspc/position/getJobList`；列表已带 JD 时不额外放大详情请求，缺 JD 才调用公开详情接口。
  - 网易社会招聘 `hr.163.com/job-detail.html?id=...`：调用公开 `GET /api/hr163/position/query?id=...`，
    详情链接保持单岗位范围，不把社会招聘直链扩展成列表。
  - 快手 `campus.kuaishou.cn/recruit/campus`：解析 hash 路由中的 `recruitSubProjectCodes`、岗位标签和筛选，
    调用公开 `POST /recruit/campus/e/api/v1/open/positions/simple` 分页；列表缺 JD 时调用
    `GET /recruit/campus/e/api/v1/open/positions/find?id=...`，直达 `#/campus/job-info/<id>` 只返回目标岗位。
  - Phenom/BCG `careers.bcg.com`：岗位详情页公开嵌入 `phApp.ddo.jobDetail.data.job`，使用稳定 `jobId`、
    HTML JD、申请链接和职位元数据；当前只承诺直接详情页，不把通用搜索页误判成完整列表。
  - 自定义域名飞书招聘 `xiaomi.jobs.f.mioffice.cn`、`jobs.ecoflow.com`、`career.papergames.com`：复用飞书的
    `position/<id>/detail` API、`website-path` 头和渲染列表导航；自定义域名不代表另一套接口，先比对
    portal path 和 API 响应再归类。商汤域名当前因 TLS 连接不可复现，仍保持失败边界。
  - 自定义域名 Moka `campus.sonoscape.com`、`campus.fingard.com`：复用服务端 `#init-data` 岗位清单，
    直达 fragment 仍按岗位 ID 精确筛选；平台详情接口加密，描述为空时保留明确边界，不把列表标题当 JD。
  七个 API 来源族共用受限标准库 HTTP 传输层：响应上限 8 MiB、请求超时 20 秒，详情并发最多 8 个；超过边界、
  缺少 JD 或接口状态异常时明确失败，不把列表标题当作岗位事实。Fixture 和回归分别在
  `tests/collection/fixtures/{alibaba,baidu,tencent,jqka,pdd,netease,kuaishou}_*.json`、
  `tests/collection/fixtures/phenom_job.html` 和对应的 `tests/collection/test_*_parser.py`。
- Fixture：`tests/collection/fixtures/public_job_page.html`；回归：
  `tests/collection/test_public_web_parser.py`、`tests/collection/test_link_classification.py`。

## 公司官网公告（COMPANY_WEBSITE）

- 复用通用公开网页解析器。若页面存在可验证的 `JobPosting`、内嵌岗位数据或岗位详情链接，
  按岗位事实解析；否则仅在标题或正文明确包含招聘语义时保留一条 `public_announcement` 公告级
  记录，岗位名称、薪资和 JD 不从表格摘要推断。
- 公告级记录的 `detail_url` 只表示公开来源，`apply_url` 保持为空；登录、WAF、普通公司介绍和
  无招聘语义的文章保持失败。
- 回归复用：`tests/collection/test_public_web_parser.py` 和
  `tests/collection/test_pipeline.py` 的公告链接语义测试。

## 定制招聘系统（CUSTOM_RECRUITMENT_SYSTEM）

- 复用通用公开网页解析器读取公开 JSON、JSON-LD、岗位详情和招聘公告；不会根据系统域名或
  表格岗位方向猜测岗位事实。
- `exam-sp.com`、二维码中转页、需要登录的报名页和没有公开岗位数据的系统入口保持失败；不绕过
  登录、验证码、加密投递或访问控制。
- 回归复用：`tests/collection/test_public_web_parser.py` 的 JSON、静态页和登录页边界测试。

## 政府招聘公告（GOVERNMENT_NOTICE）

- 公开政务站招聘文章复用通用公开网页解析器；优先读取公开 `JobPosting` 或岗位数据，普通
  招聘公告保留为一条 `public_announcement` 记录，正文和来源链接可追溯。
- 公告标题不能证明单个岗位时不拆分岗位、不伪造投递链接；首页、错误页、登录页、当前无公开
  内容的页面保持失败。
- 回归复用：`tests/collection/test_public_web_parser.py` 的公告级成功路径和登录页失败边界。

## 公共招聘门户（PUBLIC_RECRUITMENT_PORTAL）

- 复用通用公开网页解析器，读取公开岗位数据、JSON-LD、服务端岗位链接或招聘公告；公告级记录
  保留来源正文和详情链接，不把公告标题拆成岗位。
- 门户当前无岗位、跳转登录、返回网关错误或只有报名入口时保持失败；不使用表格岗位方向补齐
  缺失事实，也不绕过访问控制。
- 回归复用：`tests/collection/test_public_web_parser.py` 的公开 JSON、静态页、公告和登录页边界。

## 表单或短链（FORM_OR_SHORT）

- 先跟随公开短链，再读取表单页面的标题和正文；只有页面自身明确包含招聘、招募、实习或岗位
  语义时保留一条 `public_announcement` 记录，`apply_url` 不用表单详情页冒充岗位投递事实。
- 普通问卷、登录/验证码页、失效短链和没有招聘证据的表单保持失败；不提交表单、不读取登录态，
  也不从表格岗位摘要猜岗位。
- Fixture/回归：`tests/collection/test_form_parser.py`，底层字段测试复用
  `tests/collection/test_public_web_parser.py`。

## 邮箱（EMAIL）

- 邮箱是公告中的投递方式，不是公开岗位来源。解析器显式返回“application method”失败，避免把
  邮箱地址或主题臆造为岗位标题；后续应由公告解析器记录为 application method。
- 回归：`tests/collection/test_email_parser.py`。

## 国聘（GUOPIN）

- 普通详情使用公开 `GET https://gp-api.iguopin.com/api/jobs/v1/info?id=<岗位ID>`；查询键是
  `id`，不是 `job_id`。公司页、关键词页和定制子域统一使用公开
  `POST /api/jobs/v1/list`，岗位列表按 `page`、`page_size` 翻页；公司页本单位无岗位时再用
  `company_id_with_sub` 读取公开的下级单位岗位。
- `*.iguopin.com` 定制站先读取公开的
  `GET /api/activity/exclusive/v1/info?domain=<子域>`，再使用配置返回的公司 ID。定制站的
  页面只是 SPA 壳，不能把空 HTML 当岗位；`zp.iguopin.com/detail/companyDetail` 是公开招聘会
  公司岗位页，使用 `/api/activity/jobfair/company/v1/jobs-list`，保留 `jobfair_id` 和公司 ID。
- 岗位正文来自 `contents`，地点来自 `district_list`，学历、招聘类型、薪资、发布时间和截止
  时间只在接口明确给出时写入；岗位详情链接使用稳定的公开岗位路由。v3 签名接口、公司管理接口
  和登录/权限错误均保持失败，不复制公共客户端密钥，也不绕过访问控制。
- 当前样本全量回放：15 个来源中 11 个成功，409 个岗位通过 schema 校验。剩余 4 个经公开
  列表接口和页面 DOM 双重确认当前没有岗位：一个本单位职位数为 0、两个定制站岗位列表为空，
  一个定制站当前页面没有可用岗位；不使用历史岗位或公告标题填充。空列表会明确记录为失败，避免
  把不完整采集当成完整来源。
- Fixture：`tests/collection/fixtures/guopin_detail.json`、`guopin_list.json`、
  `guopin_site_config.json`、`guopin_fair_list.json`；回归：
  `tests/collection/test_guopin_parser.py`。

## 智联招聘（ZHAOPIN）

- 常见入口分为 Grace 自定义站、`/zk/` 招考站、智联校园服务端渲染页和移动端详情页；先
  跟随公开重定向，再按最终页面选择入口，登录页不作为岗位事实。
- Grace 页面从同域公开 JavaScript 的 `globalData` 发现 `companyId`、`xiaozhaoId` 和
  `scene`，调用 `POST https://fe.zhaopin.com/grace/api/dsc/search-job-list`。旧版页面的
  岗位源 ID 可能只写在公开组件 bundle 中，解析器动态发现它，并兼容 `orgNumbers` 的
  数组/字符串形态和 `jobSource` 的 1/2 两种公开值；按 `pageInfo.totalPage` 翻页，最多
  200 页。只保留接口中有岗位编号和标题的记录。
- `/zk/` 使用公开 `GET site/portal/pc/site` 和 `POST
  site/portal/pc/job-info/portal-list-reformc`；站点返回空岗位列表时保持失败，不用公告标题
  冒充岗位。详情链接使用公开的前端岗位详情路由。
- 智联校园详情优先读取 `window.__INITIAL_DATA__`；公司页中的招聘岗位列表也可直接使用。
  移动详情读取公开的 `window.$positionData`，不解密、不调用登录态投递接口。职责要求从
  HTML 字段转为文本，地点、学历、薪资和公开时间只在页面/API 明确给出时写入。
- 当前样本全量回放：45 个去重来源中 23 个成功，1357 个岗位通过 schema 校验。其余主要
  是公开接口明确返回空岗位、已失效的自定义页面、当前只剩公司介绍的页面，或重定向到登录
  页；不把这些页面的招聘标题、表格摘要或历史岗位补成新的开放岗位。
- Fixture：`tests/collection/fixtures/zhaopin_initial_data.html`、
  `zhaopin_mobile_position.html`、`zhaopin_zk.html`；回归：
  `tests/collection/test_zhaopin_parser.py`。

## 跨平台沉淀

- 失败先分成链接分类、入口发现、列表/分页、详情请求和字段校验五类；同一 ATS 的公司
  差异优先沉淀为入口参数或发现逻辑，不复制公司专属解析器。
- 数据入口优先级为公开 API、内嵌 JSON、服务端 HTML、JavaScript 渲染 DOM；浏览器用于
  调查和找路，批量采集复用已验证的稳定入口。
- 无法证明分页完整、空结果真实性或详情请求完整时，保持失败/部分成功，不把空列表当作
  成功，也不关闭历史岗位。
- 每个平台保留最小脱敏 Fixture，覆盖列表、详情、分页和关键失败边界；不得保存 Cookie、
  Token、完整响应或个人联系方式。
