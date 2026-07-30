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
- 详情默认 4 路线程并发；用 `JOBPICKY_FEISHU_WORKERS=1` 串行，遇限流时降低，不做
  无界并发。
- Chromium 通过 `JOBPICKY_CHROMIUM_PATH` 配置；缺失或渲染超时应明确失败。
- 2026-07-30 全量样本：33 个来源中 27 个成功，解析并校验 1381 个岗位；关闭岗位和
  无效入口保留为失败证据。
- Fixture：`tests/collection/fixtures/feishu_detail.json`；回归：
  `tests/collection/test_feishu_parser.py`。
