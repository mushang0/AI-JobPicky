# AI JobPicky

JobPicky 是一个以后端能力为主的岗位聚合与个性化推荐系统。它从企业官方招聘入口建立可追溯的岗位事实库，再用确定性硬筛选、关键词与语义召回、结构化模型评估生成可信推荐。

当前仓库处于“公共底座”阶段：已经提供可执行的跨模块数据契约、服务端口、配置、统一错误响应、请求 ID、健康检查与测试基线；采集器、数据库、画像解析、检索和推荐工作流将在后续纵向切片中实现。

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

## 验证

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## 文档

- [需求基线](docs/requirements.md)
- [架构与公共契约](docs/architecture.md)
- [开发协作约定](docs/development.md)
- [实施计划](docs/implementation-plan.md)
- [早期设计输入](docs/design/)
