# collection-ingest-slice 实施计划

## Context

当前北森采集链路已经能从招聘表格和招聘入口产出 `CollectionBatch`，岗位目录也已具备
PostgreSQL 查询能力，但两者之间仍是断点：`PostgresJobCatalog.ingest()` 会显式报
“未实现”，`scripts/ingest_campus_csv.py` 则绕过目录端口自行生成岗位 ID 并执行
`INSERT ... DO NOTHING`。因此重复采集只能忽略，不能区分新增、更新和确认，也无法恢复
重新出现的已关闭岗位。

本切片完成“北森解析结果 → 岗位目录 → PostgreSQL”的最小正式写入闭环，并让现有校园
招聘脚本走同一条入库路径。它只处理已采集成功的岗位和当前可证明安全的生命周期动作；
来源完整性保护尚未成熟，所以本轮一律不关闭历史岗位。

实现期间远端 `main` 已加入岗位 embedding、pgvector 语义检索和
`0005_job_embedding`。本切片以该实现为新基线：完整保留语义检索，在同一个岗位目录
适配器中补齐 ingest，并用 Alembic merge revision 汇合双方已执行过的迁移分支。

分支：`feat/collection-ingest-slice`

## 交付结果

1. `PostgresJobCatalog.ingest(run_id, batch)` 成为正式写入口：
   - 按既定优先级为岗位建立稳定身份：来源岗位 ID、规范化详情链接、来源 + 公司 +
     标题 + 地点组合；
   - 身份包含来源边界，同一来源的同一岗位重复采集复用系统岗位 ID，不同来源即使复用
     相同 `source_job_id` 也互不碰撞；
   - 在一个事务内完成批次 Upsert，并返回与实际写入一致的 `IngestionResult`。
2. 岗位表补充完成可靠 Upsert 所需的最小内部字段和唯一约束。保留并行产生且已在本地
   分别执行过的 `0005_job_embedding`、`0005_job_ingestion_identity`，用无 DDL 的
   `0006_merge_job_heads` 汇合为单一迁移头。具体哈希和 SQL 组织
   属于内部实现，不修改 `CollectedJob`、`JobFact` 或 `JobCatalogPort` 公共契约。
3. 岗位事实按三种结果处理：
   - 首次出现创建 `OPEN` 岗位；
   - 已有岗位的事实内容变化时更新原记录并产生新的 `fact_version`；
   - 事实内容未变化时只刷新 `last_confirmed_at`；
   - 已关闭岗位再次出现时恢复为 `OPEN`，并计为更新。
4. `IngestionResult` 准确返回本批次的 `created_count`、`updated_count`、
   `unchanged_count` 和 `job_ids`。本切片固定返回 `closed_count=0`、
   `close_skipped=true`、`complete_accepted=false`，并附带明确 warning，说明当前
   尚未同时验证分页完整性、来源范围和关闭保护条件。
5. `scripts/ingest_campus_csv.py` 删除岗位事实转换和直接 INSERT，统一构造目录适配器并
   调用 `ingest()`；输出目录返回的真实新增、更新、未变化数量及现有采集告警。
6. 校园招聘表格按独立招聘入口形成稳定来源，而不是继续共用
   `wanqing-campus-sheet`。同一入口在重复运行中得到相同 `source_id`，不同入口分别
   入库；脚本按来源形成合法的单来源批次。来源管理服务和来源表尚未实现，本轮只建立
   满足当前脚本闭环的确定性来源身份。
7. 自动化测试覆盖身份、事实版本、生命周期刷新、来源隔离和不完整采集保护；数据库
   行为由真实 PostgreSQL 集成测试证明。

## 关键取舍

1. **在岗位目录集中身份与版本规则。** 脚本和采集器只提交 `CollectedJob`，不再各自
   生成岗位 ID 或内容版本，避免出现两套事实规则；不新增 Repository、Factory 或新的
   端口层。
2. **来源是岗位身份的一部分。** `source_job_id` 只保证来源内部稳定，不能作为全库
   唯一键；详情链接和组合兜底也都放在来源边界内。跨来源合并留给有真实样本和冲突
   规则的后续切片。
3. **身份输入与事实版本分离。** 用于定位岗位的证据保持稳定；标题、地点、JD、链接等
   可展示事实的变化刷新 `fact_version`，但不改变已有系统岗位 ID。生命周期时间、
   `status`、`run_id` 及内部去重字段不参与事实版本比较。
4. **只做可证明安全的关闭语义。** 即使采集器声明 `complete=true`，本轮也不接受其
   作为关闭依据；不会预建未启用的关闭算法或返回看似可用的占位结果。后续只有在分页
   完整性和来源范围可验证后，才单独实现关闭。
5. **来源粒度先服务当前纵向切片。** 以规范化招聘入口为稳定依据，并保留公司边界以
   避免不同公司的共享 ATS 参数被混同；不顺带建设来源管理 CRUD、来源发现或来源表。
   规范化只消除不影响入口身份的表面差异，不能把不同招聘项目或租户折叠为一个来源。
6. **批次内重复也必须幂等。** 同一批次若重复出现同一身份，只产生一个 `job_id` 和
   一次分类计数；若重复项的事实互相冲突，应显式拒绝或告警，不依赖写入顺序静默覆盖。
   具体采用哪种最小策略由实现时结合真实样本确定并用测试固定。
7. **事实版本与 embedding 保持一致。** 新岗位等待现有回填流程生成 embedding；岗位
   事实内容变化时清空旧向量，避免语义检索读取过期表示。仅刷新
   `last_confirmed_at`，或只将事实未变化的岗位恢复为 `OPEN` 时保留已有向量。

## 边界（不做）

- 不增加 Moka、飞书、Hotjob 或其他 ATS 解析器；
- 不关闭任何历史岗位，也不实现完整性接受、异常下降检测或关闭恢复工作流；
- 不实现跨来源岗位合并；
- 不新增 Repository、Factory、服务层或第三方依赖；
- 不修改公共 `CollectedJob`、`CollectionBatch`、`IngestionResult`、`JobFact` 或端口
  契约，不为测试输出重构现有 JSON/fixture；
- 不建设来源管理 API、采集运行编排或完整的 `source` / `crawl_run` 持久化；
- 不扩展或重构远端已经实现的语义检索、embedding 回填和推荐评估能力。

## 验收

### PostgreSQL 集成场景

使用迁移到最新版本的真实 PostgreSQL，至少验证以下连续场景：

1. 一个包含来源岗位 ID 的新批次首次入库后：
   - 返回 `created_count=1`、其余三类岗位计数为 0；
   - `job_ids` 含唯一且非空的系统岗位 ID；
   - 数据库中的来源事实与输入一致，状态为 `OPEN`；
   - `first_seen_at`、`last_confirmed_at`、`updated_at` 为带时区时间，
     `fact_version` 非空。
2. 完全相同的批次再次入库后：
   - 不增加数据库岗位行，返回相同系统岗位 ID；
   - 返回 `unchanged_count=1`，新增和更新计数为 0；
   - `last_confirmed_at` 晚于第一次，`first_seen_at` 保持不变；
   - `fact_version` 保持不变；除确认时间外，不改写岗位事实。
3. 修改同一岗位的 JD 后：
   - 更新原行而非创建新行，系统岗位 ID 与 `first_seen_at` 保持不变；
   - 返回 `updated_count=1`；
   - 新 JD 已保存，`fact_version` 与修改前不同，`updated_at` 得到刷新。
4. 将既有岗位预置为 `CLOSED` 后再次采集：
   - 原岗位恢复为 `OPEN`，不创建新行；
   - 即使其他事实未变化也计为更新，并刷新确认时间。
5. 对来源岗位 ID 缺失的岗位，分别验证详情链接兜底和“来源 + 公司 + 标题 + 地点”
   兜底：相同语义输入重复执行复用岗位 ID；链接或文本的无关格式差异按既定规范化规则
   保持稳定。
6. 两个不同来源提交相同 `source_job_id`：
   - 创建两个不同系统岗位 ID；
   - 各自重复采集只命中本来源记录，不发生唯一约束冲突或交叉更新。
7. 对 `complete=false` 和 `complete=true` 的批次都验证：
   - 预置但本次未出现的历史岗位状态保持不变；
   - `closed_count=0`、`close_skipped=true`、`complete_accepted=false`；
   - warning 明确表达未关闭原因，而不是空泛的成功提示。
8. 多岗位批次与批次内重复项验证：
   - 三类计数之和等于本次实际处理的唯一岗位数；
   - `job_ids` 无重复，且与本批次唯一岗位一一对应；
   - 任一写入失败不会留下半个已提交批次。
9. 与 embedding 共存时验证：
   - unchanged 只刷新确认时间并保留已有 embedding；
   - 事实内容变化会清空 embedding；
   - 仅从 `CLOSED` 恢复为 `OPEN` 且事实未变化时保留 embedding；
   - 远端语义检索和推荐评估测试继续通过。

### 脚本与回归

1. 校园招聘脚本不再包含岗位 INSERT SQL、岗位 ID 或 `fact_version` 生成逻辑。
2. 用至少两个独立招聘入口的固定样本验证：
   - 入口得到不同且稳定的 `source_id`；
   - 每个传入 `ingest()` 的 `CollectionBatch` 只包含其声明来源；
   - 同一输入连续执行时，第二次输出新增为 0，并报告真实未变化数量。
3. 现有北森解析、岗位查询、硬筛选和关键词检索测试继续通过；没有数据库连接串时，
   PostgreSQL 集成测试仍按项目约定明确 skip。

## 验证命令

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest

podman compose up -d db
uv run alembic upgrade head
uv run alembic heads  # 仅输出 0006_merge_job_heads
JOBPICKY_TEST_DATABASE_URL=postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky \
  uv run pytest tests/infrastructure/test_job_catalog.py
```

实现完成后再按仓库要求运行完整的真实数据库测试。提交信息、commit、推送和 PR 均在用户
审阅本计划并明确授权后处理。
