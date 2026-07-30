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

## 跨平台沉淀

- 失败先分成链接分类、入口发现、列表/分页、详情请求和字段校验五类；同一 ATS 的公司
  差异优先沉淀为入口参数或发现逻辑，不复制公司专属解析器。
- 数据入口优先级为公开 API、内嵌 JSON、服务端 HTML、JavaScript 渲染 DOM；浏览器用于
  调查和找路，批量采集复用已验证的稳定入口。
- 无法证明分页完整、空结果真实性或详情请求完整时，保持失败/部分成功，不把空列表当作
  成功，也不关闭历史岗位。
- 每个平台保留最小脱敏 Fixture，覆盖列表、详情、分页和关键失败边界；不得保存 Cookie、
  Token、完整响应或个人联系方式。
