# catalog-search 实现计划

## Context

`feat/matching-baseline` 交付了确定性的匹配基线（`build_filter_spec` / `build_query_text` /
`merge_candidates`），`feat/infra-database` 交付了 PostgreSQL + pgvector 底座并把校招样例
数据写入了 `job` 表。整条推荐流水线仍断在「搜索」一环：`ports.py` 的 `JobCatalogPort`
（`get_jobs` / `hard_filter` / `keyword_search` / `semantic_search`）没有任何实现，
匹配基线产出的 `HardFilterSpec` 和检索文本没有真实的岗位存储可以执行。

本切片实现 `JobCatalogPort` 的搜索侧，让「画像 → 硬筛选 → 关键词召回 → 融合」第一次
离线端到端跑通。`semantic_search` 依赖 Embedding 厂商选型（架构 §7.3），`ingest`
属于采集切片，两者本轮**显式失败**，不用假数据伪装完成。

## 交付物

1. `src/jobpicky/catalog/` — 新业务模块，放纯确定性、无 I/O 的岗位目录领域逻辑：
   - `hard_filter.py` — 硬筛选判定纯函数：`evaluate_job(spec, job) -> FilterExclusion | None`
     与 `apply_filter(spec, jobs) -> FilterResult`；
   - `query_terms.py` — 检索文本分词（`extract_terms(query_text) -> list[str]`）与
     词命中计分（`term_hit_score(terms, job) -> float`）纯函数。
2. `src/jobpicky/infrastructure/job_catalog.py` — `PostgresJobCatalog`，实现
   `JobCatalogPort`：`get_jobs` / `hard_filter` / `keyword_search` 真实执行（SQLAlchemy
   Core 读 `job` 表 + 调用 catalog 纯函数）；`ingest` / `semantic_search` 抛
   `ApplicationError(ErrorCode.DEPENDENCY_UNAVAILABLE)`。
3. `tests/catalog/test_hard_filter.py`、`tests/catalog/test_query_terms.py` — 离线单测，
   测试数据用工厂函数构造（参考 `tests/matching/factories.py`）。
4. `tests/infrastructure/test_job_catalog.py` — 真实数据库集成测试（未设置
   `JOBPICKY_TEST_DATABASE_URL` 时 skip，CI service container 真实执行）：种样例行，
   验证行 → `JobFact` 映射、硬筛选端到端、关键词召回排序、未实现方法显式抛错。
5. `docs/plans/003-catalog-search.md` — 本计划留档。

## 关键取舍

1. **`catalog` 模块从此切片诞生**：硬筛选判定和词命中计分是岗位事实上的领域逻辑，
   归 `catalog`（架构：岗位事实归 catalog 唯一所有）；SQL 读写归 `infrastructure`。
   纯函数与 I/O 分离后，绝大多数测试离线完成，集成测试只验证映射与接线。
2. **硬筛选读行后在 Python 判定，不下推 SQL**：`hard_filter` 读取 OPEN 岗位的必要列，
   逐岗位走 `evaluate_job`。当前数据量是校招样例级别，全量读代价可忽略；换来的是
   判定逻辑单一出处、离线可测、排除原因（`FilterReasonCode`）逐条准确。数据量增长后
   再考虑 SQL 下推，契约不变。
3. **排除语义严格遵守 R2（宁放行勿误杀）**，逐维度规则：
   - `only_open`：`status != open` → `JOB_NOT_OPEN`；
   - `target_locations` 非空且与 `job.locations` 无交集 → `LOCATION_MISMATCH`；
     岗位 `locations` 为空 → 放行；
   - `recruitment_types` 非空且岗位 `recruitment_type` 不在其中 →
     `RECRUITMENT_TYPE_MISMATCH`；岗位该字段为 null → 放行；
   - 学历等级表（专科 < 本科 < 硕士 < 博士）：岗位要求等级**高于**求职者等级 →
     `EDUCATION_MISMATCH`；岗位要求无法解析或为 null → 放行；
   - `title` 命中任一 `excluded_roles` 词 → `EXCLUDED_ROLE`；
   - `graduation_years` 非空且不包含 `graduation_year` → `GRADUATION_YEAR_MISMATCH`；
     岗位该列表为空 → 放行；
   - `salary_max < min_salary` → `SALARY_MISMATCH`；岗位薪资为 null → 放行。
   一岗位多维度命中时，按上述顺序报告首个原因，与 `FilterReasonCode` 定义顺序一致。
4. **关键词召回用确定性词命中计分，不上 pg_trgm/zhparser**：校招 JD 以中文为主，
   PostgreSQL 内置 FTS 对中文基本无效。首版把 `query_text`（匹配基线产出的是按行
   组织的角色/技能/经历/补充要求）拆成词条——连续 CJK 段与英文数字词，去重——
   在 `title` + `company_name` + `description` 上统计命中词数，`score =
   命中词数 / 总词数`（归一化到 `NormalizedScore`）。简单、确定、可解释，满足
   「两种召回方式可独立验证」（需求 §5.4）；分词器/索引升级留给阶段 4 评估集驱动。
   空词条列表返回空命中，不造分。
5. **不为搜索建索引、不加迁移**：当前数据量下顺序扫描足够；本切片零迁移，自然不会
   与采集切片在迁移头 `0003` 之后产生并行终点冲突（development.md §9）。
6. **未实现能力显式失败**：`semantic_search` 与 `ingest` 抛
   `ApplicationError(ErrorCode.DEPENDENCY_UNAVAILABLE)`——错误码已存在于公共契约，
   **本切片不涉及任何契约/端口变更**。docstring 分别注明：语义召回待 Embedding
   选型后用独立迁移加 `embedding` 列 + HNSW 索引；`ingest` 由采集切片实现。

## 边界（不做）

- 不实现 `ingest`（岗位落库归采集切片）、不建 `embedding` 列、不选 Embedding 厂商
- 不改 `contracts/`、`ports.py`、`matching/`，不碰采集相关文件
- 不接 API 路由、不做 `RecommendationRun` 持久化（阶段 2 内容）
- 不做语义召回与融合策略调参（阶段 4 评估集驱动）

## 验证

```bash
docker compose up -d db
uv run alembic upgrade head
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
uv run pytest                                        # 本地：集成测试 skip，离线测试全绿
JOBPICKY_TEST_DATABASE_URL=postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky \
  uv run pytest                                      # 起库后：集成测试真实执行
```

提交：`feat: implement job catalog search port`，从最新 `main` 切 `feat/catalog-search`
分支单独开 PR；推送前向用户确认提交信息并取得推送授权。
