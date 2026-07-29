# recommendation-run-skeleton 实现计划

## Context

`feat/catalog-search` 合入后，推荐链路的确定性零件全部就绪：`build_filter_spec` →
`hard_filter`（真实库）→ `build_query_text` → `keyword_search`（真实库）→ `merge_candidates`。
但还没有任何东西把它们串成一次可查询的推荐运行：`RecommendationOrchestratorPort` 无实现、
`recommendation_run` 无表、`profiles` 存储不存在。

本切片是阶段 2（首个推荐纵向切片）的**前半段**：搭建推荐编排骨架 + 运行持久化，
串联确定性链路，兑现「发起推荐 → 查状态 → 查候选结果」。语义召回、LLM 评估、
事实重组是阶段 2 后半段，等 Embedding/模型/简历格式选型后填入骨架，本轮不做。

## 已确认的决策（2026-07-29 与用户确认）

1. **画像来源**：顺带建最小画像存储——`profile` 表迁移 + `ProfileSnapshotReaderPort`
   实现 + 种子写入方式，让切片端到端真实可跑。
2. **执行方式**：进程内后台任务（`asyncio` 任务），`start` 立即返回 `RunAccepted`；
   不引入 worker 或执行器抽象（阶段 3 内容）。
3. **结果形态**：新增候选结果 DTO `RecommendationCandidate`（`job: JobFact` +
   `retrieval: Candidate`），`get_results` 返回它；`RecommendationItem` 留待评估环节。
4. **不接 API**：只交付服务层，HTTP 等身份方式定了再统一接。

## 交付物

1. 迁移 `0004_profile_and_recommendation_run`（接在头 `0003` 之后，单头纪律）：
   - `profile` 表：镜像 `ProfileSnapshot`（`id` + `version` 联合唯一，快照不可变，
     列表字段用 ARRAY）；
   - `recommendation_run` 表：`run_id` 主键、`user_id`、`status`、`current_step`、
     时间戳三件套、`counts`/`warnings`、`recommendation_input`（JSONB，含
     `profile_id`/`profile_version`/`effective_extra_request`）、
     `model_config_version`、`error`（JSONB）、`idempotency_key`（可空，与
     `user_id` 建复合唯一索引，见关键取舍 4）、
     `results`（JSONB，候选结果快照列表）。
2. `src/jobpicky/contracts/matching.py` — 新增 `RecommendationCandidate`
   （受控契约新增，见关键取舍 1）。
3. `src/jobpicky/infrastructure/profile_store.py` — `PostgresProfileStore`：
   实现 `ProfileSnapshotReaderPort.get_snapshot`；另附 `save_snapshot`（种子/测试用，
   不属于端口）。
4. `src/jobpicky/orchestration/` — 新模块：
   - `service.py` — `RecommendationRunService` 实现 `RecommendationOrchestratorPort`
     （`start` / `list_runs` / `get_run` / `get_results`），编排逻辑与 I/O 分离：
     纯函数规划步骤，DB 适配只管读写；
   - 执行器：进程内 `asyncio` 后台任务驱动确定性链路。
5. `ports.py` — `RecommendationOrchestratorPort.get_results` 返回类型改为
   `Page[RecommendationCandidate]`（随契约新增同步）；`tests/test_ports.py`
   补一条 `get_results` 返回注解断言，防止端口签名静默漂移。
6. `docs/architecture.md` — 同步 §5.6 端口签名、结果 DTO 说明，以及 §6.1.1
   P0 HTTP 覆盖表中 `get_results` 一行的 DTO（契约变更纪律 §8），保持文档
   内部一致。
7. 测试：
   - `tests/orchestration/` — 离线：步骤规划、输入合并（`merge_extra_request` 在
     创建时固化）、幂等键冲突且输入一致返回既有运行、同 key 不同输入显式
     `CONFLICT`、跨用户同 key 互不可见、未完成运行 `get_results` 返回空页、
     零候选运行落 `SUCCEEDED`、失败路径状态落库；
   - `tests/infrastructure/test_profile_store.py`、
     `tests/infrastructure/test_recommendation_run.py` — 真实库端到端：种画像 →
     发起运行 → 轮询状态至完成 → 查候选结果（沿用 `JOBPICKY_TEST_DATABASE_URL` skip 模式）。
8. `docs/plans/004-recommendation-run-skeleton.md` — 本计划留档。

## 关键取舍

1. **受控契约新增而非放宽现有契约**：`RecommendationItem` 强制 `matched=true` 的
   模型评估，无评估器时组装不出合法实例。新增 `RecommendationCandidate`
   （`job` + `retrieval`，无 `assessment`）承载评估前的结果，`get_results` 改返回
   `Page[RecommendationCandidate]`；`RecommendationItem` 不动，评估环节落地后再决定
   扩展还是回迁。同一 PR 同步 `architecture.md`，符合「契约变更先同步再修改」。
2. **结果存快照，不查询时回读**（R7）：运行完成时把候选的完整 `JobFact` 快照 +
   融合分数写入 `results` JSONB。之后岗位事实无论如何变化，历史运行看到的结果
   都保持不变；`recommendation_input.profile_version` 与 `effective_extra_request`
   同样在创建时固化，恢复/重试/查询一律用已保存值（架构 §4.12）。
3. **`model_config_version` 用确定性常量**：推荐运行的 `RunView` 必须填充该字段，
   但模型配置尚不存在。本轮填匹配基线版本常量（如 `baseline-v1`，挂在
   `MatchingConfig` 上），含义诚实：本次运行只使用了基线确定性逻辑。
4. **幂等靠 per-user 复合唯一约束**：唯一索引建在 `(user_id, idempotency_key)`
   上（可空，NULL 不参与唯一冲突），避免不同用户凑巧同 key 时互相拿到对方的
   运行——全库唯一会同时违反 R8 用户隔离与幂等语义。冲突时不新建运行：先比对
   既有运行固化的 `recommendation_input`（`profile_id`/`profile_version`/
   `effective_extra_request`），输入一致则返回既有运行的 `RunAccepted`（需求
   R5：客户端重复提交不产生重复结果）；同一 key 配不同输入则显式失败
   （`CONFLICT`），不静默复用旧运行冒充新输入已生效。未提供 key 时每次创建新
   运行。
5. **进程内后台任务的已知局限**：服务重启会丢失进行中的任务（运行记录停在
   `RUNNING`）。这是明示的取舍——恢复与重试加固属于阶段 3，本切片在 docstring 和
   计划里写明，不伪装可靠性。
6. **画像存储只做读取 + 种子写入**：`ProfileApplicationPort`（画像创建/修正）依赖
   简历解析与身份方式，不实现；`save_snapshot` 仅供种子数据与测试，画像的正式
   写入路径归后续 profiles 切片。
7. **一次迁移两张表**：`profile` 与 `recommendation_run` 同属本切片的运行骨架，
   合在 `0004` 一个迁移里，减少迁移头竞争窗口。
8. **边界语义显式固化**（实现时按此定死，不留给调用方猜）：
   - 运行未完成（`PENDING`/`RUNNING`）时 `get_results` 返回空 `Page`，不报错；
     是否出结果以 `RunView.status` 为准；
   - 硬过滤/检索后候选为 0 属正常结果：`status=SUCCEEDED`、空 `results`、
     `counts` 体现 0；不用 `PARTIAL` 混淆「无候选」与「部分失败」；
   - 失败路径一律终态 `FAILED` 并落 `RunError`（code/message/details），
     不残留中间态。

## 边界（不做）

- 不实现语义召回、LLM 评估、事实重组（等三个选型）
- 不实现 `ProfileApplicationPort`、简历解析、身份/鉴权
- 不接 HTTP 路由、不做 worker/执行器抽象、不做崩溃恢复与重试（阶段 3）
- 不碰 `collection`、`matching` 现有实现；`RecommendationItem` 语义不变

## 验证

```bash
podman compose up -d db
uv run alembic upgrade head
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
uv run pytest                                        # 本地：集成测试 skip
JOBPICKY_TEST_DATABASE_URL=postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky \
  uv run pytest                                      # 起库后：集成测试真实执行
```

提交：`feat: add recommendation run skeleton`，从最新 `main` 切
`feat/recommendation-run-skeleton` 分支；commit 信息与推送均需用户确认/授权。
