# collection-pipeline 实现计划与现状

## 当前状态

分支：`feat/collection-pipeline`。

本分支目标是打通：

```text
固定格式招聘表格
→ 抽取表格字段
→ 按投递链接类型路由解析器
→ 采集网站岗位
→ 合并表格字段与网站字段
→ 生成 CollectedJob
→ 转换为 JobFact 并可入库
```

本轮实际验证使用原始 CSV 前 600 条物理数据行，去重后选出 63 条北森投递链接。因此 `selected_source_count=63` 不是 600 个岗位，也不是 600 家公司。

## 当前分支的改动

### 采集与表格

- `src/jobpicky/collection/spreadsheet.py`
  - 统一 CSV/XLSX 固定列读取。
  - 抽取公司、行业、岗位方向、城市、截止时间、届次、学历、批次、公告链接、投递链接等字段。
  - 复用共享链接抽取逻辑，同时过滤表格中的普通文本和占位值。
  - 原始 `batch` 保留；`recruitment_type` 只做粗粒度归一化：实习、校招或原始值。
- `src/jobpicky/collection/link_extraction.py`
  - 统一 Excel 文本与超链接目标的链接抽取，避免 `mailto:` 链接和裸邮箱重复计数。
- `src/jobpicky/collection/link_classification.py`
  - 按域名和链接形态识别北森、Moka、飞书等来源类型。
- `src/jobpicky/collection/parsers/beisen.py`
  - 支持北森桌面端 API、移动端 API、内嵌 JSON 和有限静态 HTML 兜底。
  - 支持根域、自定义入口、`/campus` 等页面回退到语义匹配的岗位列表路径。
  - 支持单岗位详情按 `jobAdId` 过滤，不把详情链接扩大成公司全量岗位。
  - 清理移动端明显损坏的 `ky=π=1` 查询参数，同时保留有效分类筛选。
  - 没有独立投递入口时，将岗位详情链接同时作为 `apply_url`；网站提供独立投递链接时保留原值。
- `src/jobpicky/collection/pipeline.py`
  - 按链接类型选择解析器。
  - 网站字段优先，表格字段补充缺失内容。
  - 缺少独立投递链接时，以详情链接补齐 `apply_url`。
  - 合并结果校验为 `CollectedJob`。
  - 不支持、解析失败、空结果和字段非法均记录为可定位失败，不伪造岗位。

### 脚本、入库与测试

- `scripts/verify_beisen_pipeline.py`
  - 不写数据库，生成每个来源的原始抓取快照、解析结果、合并结果、复核 CSV 和汇总。
- `scripts/ingest_campus_csv.py`
  - 从旧的“表格直灌”改为使用采集管线。
  - 将 `CollectedJob` 转换为 `JobFact`，补充薪资字段并写入岗位表。
  - 当前仍默认把成功采集岗位写成 `OPEN`，没有实现历史岗位关闭和过期清洗。
- `scripts/analyze_apply_links.py`
  - 使用共享链接抽取逻辑，删除脚本内重复实现，并保留 `main` 中的 `mailto:` 去重修复。
- `tests/collection/`、`tests/fixtures/`
  - 覆盖固定列抽取、来源分类、北森桌面/移动/内嵌 JSON、合并优先级和失败路径。
- `AGENTS.md`
  - 增加大型 JSON/CSV 不应全量载入上下文的协作约束。

## 当前采集结果

最新在线复跑结果：[`beisen-current-20260729/summary.json`](/Users/joy/Documents/toyproject/artifacts/collection-review/beisen-current-20260729/summary.json)

```text
selected_source_count: 63
successful_source_count: 57
failed_source_count: 6
parsed_job_count: 2753
merged_job_count: 2753
schema_valid_count: 2753
schema_invalid_count: 0
duplicate_job_count: 166
```

旧结果 [`beisen-first-600/summary.json`](/Users/joy/Documents/toyproject/artifacts/collection-review/beisen-first-600/summary.json) 的 43/20 是修复前历史快照，不应覆盖或修改为新结果。

当前 6 条失败的命令行复核结论：

| 来源 | 当前结论 |
|---|---|
| 优衣库、郑州易盛信息、深圳燃气 | 详情链接对应的 `jobAdId` 已不在当前岗位列表，倾向岗位关闭或链接过期 |
| 长江存储、美赞臣中国 | 校招列表完整返回但为空，当前没有可用校招岗位 |
| 中芯国际 | 校招列表为空；同域实习列表仍有岗位，不能关闭公司全部岗位 |

与前一次 `beisen-rerun-20260729` 摘要相比，来源成功/失败数、重复数和无效数一致，岗位数增加 1，属于网站实时状态变化，不视为代码回归。

## 设想中的正确职责边界

### 1. 采集层：只回答“网站现在返回了什么”

解析器应保留网站事实和来源信息，不在解析阶段删除 2025 年岗位，也不根据表格批次猜测网站岗位类型。

### 2. 表格层：保留原始批次和届次

`batch` 应保留完整原文，例如“春招补录”“暑期实习”“秋招提前批”。
`recruitment_type` 只适合作为粗粒度筛选字段，不能替代 `batch`。当前精确批次放在 `metadata["batch"]`，后续若批次成为核心筛选条件，应考虑将其提升为明确字段。

### 3. 生命周期层：决定岗位是否关闭

只有在以下条件同时满足时，空列表才可关闭历史岗位：

- 请求成功且页面/API 返回结构正常；
- 能确认分页或列表完整；
- 当前链接的招聘范围明确，例如校招、实习或社招；
- 不是单岗位详情链接、登录页、异常页或被访问控制拦截。

关闭范围应是“同来源、同招聘范围”的岗位，而不是整家公司。采集不完整时，已有岗位必须保持原状态。

### 4. 清洗/推荐层：决定哪些岗位还有价值

发布时间、截止时间、批次和届次应在采集完成后综合判断：

- 已过截止时间：关闭或排除推荐；
- 来源明确关闭：关闭；
- 发布时间很旧且没有未来截止时间、目标届次或当前开放证据：标记过期并排除推荐；
- 只有发布时间早，但仍明确面向未来届次或仍开放：不要仅凭年份删除。

“丢弃”更适合表示“不进入推荐候选”，不建议直接删除事实记录。保留关闭/过期状态有利于审计、去重、恢复和解释。

## 已知风险与未来坑

- `recruitment_type` 不是严格枚举。网站解析器明确返回的类型优先；只有解析器没有返回类型时才使用表格批次归一化值，无法归一化的明确值保持为空，避免误标为实习。
- 混合批次如“暑期实习, 秋招提前批”不会再按“实习”优先归类；原始批次会拆成多个可筛选单元，粗粒度招聘类型保持未知。
- 当前岗位关闭没有真正接入 `ingest_campus_csv.py`；成功岗位会写入，但历史岗位不会按本次完整采集结果关闭。
- 桌面端和移动端单次请求上限为 1000，尚未证明所有来源的分页完整性；超过上限会造成不完整采集。
- `duplicate_job_count=166` 表明不同来源链接之间存在重复岗位，当前汇总只统计重复，没有独立的跨来源去重策略。
- 详情链接失效只能确认该岗位不可用，不能据此关闭同公司的其他岗位。
- 公开网站的岗位发布时间、截止时间和状态可能缺失或格式变化，时间清洗必须允许 `UNKNOWN`，不能把缺失当作过期。
- 在线复跑受网站实时状态、限流和页面波动影响，不能直接作为离线回归测试；应逐步沉淀脱敏 fixture。
- `artifacts/collection-review/` 中包含抓取快照和岗位明细，提交前必须检查是否有不应入库的响应内容。

## 验证记录

本轮通过：

```text
uv run ruff check .
uv run ruff format --check .
uv run pytest
94 passed, 3 skipped
```

在线复核命令扫描原始 CSV 第 2–601 行，未写数据库；摘要结果为 63 个来源、57 个成功、6 个失败、2753 个解析和合并岗位、0 个 Schema 无效岗位、166 个重复岗位。

本计划不包含推送或数据库真实回填；历史岗位关闭和过期清洗仍未接入 `ingest_campus_csv.py`。
