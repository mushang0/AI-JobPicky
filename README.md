# AI JobPicky

JobPicky 是一个以后端能力为主的岗位聚合与个性化推荐系统。它从企业官方招聘入口建立可追溯的岗位事实库，再用确定性硬筛选、关键词与语义召回、结构化模型评估生成可信推荐。

当前仓库处于“公共底座”阶段：已经提供可执行的跨模块数据契约、服务端口、配置、统一错误响应、请求 ID、健康检查与测试基线；数据库底座（PostgreSQL + pgvector、Alembic 迁移与 `job` 表）已就位；采集器、画像解析、检索和推荐工作流将在后续纵向切片中实现。

## 架构

首版采用模块化单体：

```text
HTTP API
   ↓
应用编排
   ├── collection：招聘源与采集
   ├── catalog：岗位事实、生命周期与查询
   ├── profiles：简历解析与版本化画像
   └── matching：硬筛选、召回融合与评估
   ↓
infrastructure：数据库、HTTP、模型与任务执行器适配
```

跨模块只通过 `src/jobpicky/contracts/` 中的 DTO 和 `src/jobpicky/ports.py` 中的端口协作。岗位事实归 `catalog` 所有；模型输出不能覆盖岗位事实；不完整采集不能关闭历史岗位。

## 本地运行

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev
uv run uvicorn jobpicky.main:app --reload
```

健康检查：

```text
GET http://127.0.0.1:8000/api/v1/system/health
```

OpenAPI：

```text
http://127.0.0.1:8000/docs
```

### 一键启动前后端与数据库

完成根目录 `.env`、`frontend/.env` 和前端依赖配置后执行：

```bash
./scripts/start-dev.sh
```

脚本会启动 Docker 中的 PostgreSQL/pgvector、执行 Alembic 迁移，并启动真实 API 模式的后端和前端。
按 `Ctrl-C` 只停止前后端，数据库保持运行。

## 本地数据库

岗位事实存储在 PostgreSQL（pgvector 扩展）。需要 Docker（Docker Desktop 或兼容运行时）：

```bash
docker compose up -d db
uv run alembic upgrade head
```

连接串默认为 `postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky`，
可用环境变量 `JOBPICKY_DATABASE_URL` 覆盖（见 `.env.example`）。

数据库集成测试默认跳过；起库并迁移后，设置
`JOBPICKY_TEST_DATABASE_URL`（本地与默认值相同）再运行 `uv run pytest` 即可真实执行。

### 灌入开发样本数据

仓库自带校招汇总表样本（`data/raw/campus_jobs_sample.csv`），可灌入约 1000 条真实岗位：

```bash
uv run python scripts/ingest_campus_csv.py            # 默认全部写入，幂等 upsert
uv run python scripts/ingest_campus_csv.py --limit 500
uv run python scripts/ingest_campus_csv.py --reset --row-limit 600  # 清空后只灌入前 600 条记录
```

不带 `--reset` 时按岗位身份幂等 upsert：新岗位新增，内容变化的岗位更新，未变化的岗位保留。
`--reset` 仅用于 development/test，会在解析得到岗位后清空岗位目录及其关联的收藏/推荐记录，再用当前仓库代码重新灌入；它不删除表结构、用户账户或画像，也不会运行解析验证脚本。

## 验证

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

### 推荐模型配置

语义召回只从本地 Hugging Face 文件加载，不会因模型缺失自动降级为关键词召回；模型路径和 DashScope
密钥均通过环境变量提供。数据库迁移完成后，显式运行以下命令回填缺失的 512 维岗位向量：

```bash
JOBPICKY_EMBEDDING_MODEL_PATH=/path/to/bge-small-zh-v1.5 \
  python scripts/backfill_job_embeddings.py
```

推荐运行需要 `JOBPICKY_LLM_MODEL` 和 `JOBPICKY_DASHSCOPE_API_KEY`。API key 不写入仓库、日志或运行快照；
未配置模型依赖时，推荐运行会以明确的依赖错误失败。

评估 Prompt 与模型输入/输出 JSON Schema 位于 `src/jobpicky/infrastructure/prompts/` 和
`src/jobpicky/infrastructure/schemas/`，修改模型协议时同步升级 `JOBPICKY_MODEL_CONFIG_VERSION`。

## 文档

- [需求基线](docs/requirements.md)
- [架构与公共契约](docs/architecture.md)
- [开发协作约定](docs/development.md)
- [实施计划](docs/implementation-plan.md)
- [早期设计输入](docs/design/)
