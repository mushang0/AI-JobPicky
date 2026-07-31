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
uv run python scripts/report_parser_gaps.py <csv-or-xlsx> --limit-rows 20
```

跨平台人工回放：

```bash
uv run python scripts/verify_parser_pipeline.py \
  --platform <PLATFORM> --limit <N> --input <csv> --output <artifact-dir>
```

先小样本验证；确需全量时用 `--limit 0`，完成后先看 `summary.json`。北森专用脚本额外
保存脱敏前的接口响应并支持行区间定位，仅在诊断北森时使用。

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
- 其余来源使用通用公开网页解析器：优先读取 `JobPosting` JSON-LD，再读取公开内嵌 JSON，
  然后读取带岗位语义的服务端链接或直达岗位页。只保存能确认标题的岗位，不执行页面脚本，
  不把首页导航、登录页或空 SPA 壳当岗位。
- 没有稳定公开数据的前端 SPA、跳转到登录或访问控制页面、以及只有招聘入口而没有岗位事实的
  页面保持失败；这类来源需要后续按公开接口调查，不能用表格岗位摘要补写 JD。
- Fixture：`tests/collection/fixtures/public_job_page.html`；回归：
  `tests/collection/test_public_web_parser.py`、`tests/collection/test_link_classification.py`。

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
