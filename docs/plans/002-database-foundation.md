# database-foundation 实现计划

## Context

`feat/matching-baseline` 交付了确定性的匹配基线（硬条件生成、检索文本、候选融合），
但整条推荐流水线断在「搜索」一环：`ports.py:37` 的 `JobCatalogPort`（`hard_filter` /
`keyword_search` / `semantic_search`）需要真实的岗位存储才能实现。

按架构 §7.3/§10，首版存储定案为 **PostgreSQL（全文检索）+ pgvector 扩展（语义向量）**，
SQLAlchemy + Alembic 管理持久化，Docker Compose 提供本地依赖。本切片只做数据库底座，
让后续「采集切片」（岗位落库）和「搜索切片」（实现 `JobCatalogPort`）都有共同起点。

实施计划 `implementation-plan.md` 原本把 PostgreSQL 归在阶段 1 采集切片；按
`development.md` §6「公共前置变更先形成小的独立交付，再让依赖任务同步」，
本底座作为独立小 PR 先行，合并后队友 rebase 复用。

## 交付物

1. `docker-compose.yml` — `db` 服务，本地 PostgreSQL + pgvector
2. 依赖：`sqlalchemy[asyncio]`、`alembic`、`asyncpg`、`pgvector`
3. `src/jobpicky/config.py` — `Settings.database_url`（`JOBPICKY_DATABASE_URL`）
4. `src/jobpicky/infrastructure/database.py` — async engine / session 工厂
5. `alembic/` 异步迁移环境 + 首个迁移：启用 pgvector 扩展、建 `job` 表
6. `tests/infrastructure/test_database.py` — 真实数据库集成测试（未起库时 skip）
7. CI 增加 Postgres service container，迁移 + 集成测试真实执行
8. README「本地数据库」一节
9. `docs/plans/002-database-foundation.md` — 本计划留档

## 关键取舍

1. **镜像 `pgvector/pgvector:pg16`**：官方维护、pgvector 预装，`docker compose up -d db`
   一条命令让所有开发者与 CI 得到完全一致的环境。
2. **异步栈**：SQLAlchemy 2.0 async + asyncpg，与 FastAPI 异步模型一致；Alembic 用
   异步模板，不引入同步驱动。连接串只来自 `JOBPICKY_DATABASE_URL`，不写进 `alembic.ini`。
3. **`embedding` 向量列本次不建**：只启用扩展。向量维度取决于 Embedding 厂商选型
   （架构 §7.3 明确留给实现者），现在建列等于提前锁定维度；语义召回切片确定厂商后
   用独立迁移加列 + HNSW 索引。符合「不为未来概念提前建表」。
4. **首版 Schema 保持简单**：`job` 表字段一一镜像 `JobFact` 契约；`source`、
   `crawl_run` 等表属于采集切片，不提前建。
5. **集成测试无库时 skip**：本地 `uv run pytest` 不起库也全绿；设置
   `JOBPICKY_TEST_DATABASE_URL` 后真实执行；CI 用 service container 强制真实执行。
6. **迁移纪律**：本 PR 创建第一个迁移头（`0001_job_table`），后续所有切片在此头
   上续迁移，不得从同一头各开终点（development.md §9）。

## 边界（不做）

- 不实现 `JobCatalogPort` 任何方法（hard_filter / keyword_search / semantic_search）
- 不建 `embedding` 列、不选 Embedding 厂商
- 不碰 `contracts/`、`ports.py`、`matching/`、采集相关文件
- 不接 API 路由、不写 Repository / Service 层

## 验证

```bash
docker compose up -d db
uv run alembic upgrade head
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
uv run pytest                                        # 本地：集成测试 skip
JOBPICKY_TEST_DATABASE_URL=postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky \
  uv run pytest                                      # 起库后：集成测试真实执行
```

提交：`feat: add postgres database foundation`，推送 `feat/infra-database` 单独开 PR；
合并后通知队友同步 `main`。
