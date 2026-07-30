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
uv run python scripts/ingest_campus_csv.py            # 默认前 1000 条
uv run python scripts/ingest_campus_csv.py --limit 500
```

脚本幂等（按公告链接去重），重复执行不会新增数据。

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

## 文档

- [需求基线](docs/requirements.md)
- [架构与公共契约](docs/architecture.md)
- [开发协作约定](docs/development.md)
- [实施计划](docs/implementation-plan.md)
- [早期设计输入](docs/design/)
