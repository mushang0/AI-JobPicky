# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 与 AGENTS.md 的关系

`CLAUDE.md` 与 `AGENTS.md` **功能一致、互为补充**：`AGENTS.md` 面向所有 AI/人工协作者写协作约束，本文件补充 Claude Code 的常用命令与架构导览。**Agent 开始工作前必须两份都读**，以两份文档中更严格的约束为准。

## 推送授权（硬性规则）

**任何推送到远端的操作（`git push`、创建远端分支、开 PR）都必须先得到用户的明确授权**，不得凭惯性执行。提交（commit）前也应先向用户确认提交信息。

## 常用命令

```bash
uv sync --extra dev                 # 安装依赖
uv run uvicorn jobpicky.main:app --reload   # 本地起服务

uv run ruff check .                 # lint
uv run ruff format --check .        # 格式检查（写代码用 uv run ruff format .）
uv run mypy src tests               # 类型检查
uv run pytest                       # 全部测试（数据库集成测试无库时自动 skip）
uv run pytest tests/matching/test_query_text.py::test_xxx   # 跑单个测试

docker compose up -d db             # 起本地 PostgreSQL + pgvector
uv run alembic upgrade head         # 执行迁移（连接串来自 JOBPICKY_DATABASE_URL）
uv run alembic upgrade head --sql   # 离线预览迁移 SQL，不需起库
uv run alembic revision -m "..."    # 新建迁移（必须接在现有迁移头之后）

JOBPICKY_TEST_DATABASE_URL=postgresql+asyncpg://jobpicky:jobpicky@localhost:5432/jobpicky \
  uv run pytest                     # 起库后真实执行数据库集成测试
```

配置全部走环境变量（前缀 `JOBPICKY_`，见 `.env.example` 与 `src/jobpicky/config.py`），秘密不进仓库。

## 架构导览

模块化单体（FastAPI），模块间**只允许通过公共契约和端口协作**：

- `src/jobpicky/contracts/` — 跨模块 DTO（Pydantic）。改这里的字段/枚举属于公共契约变更，必须先同步（见 `docs/development.md` §8）。
- `src/jobpicky/ports.py` — 全部跨模块端口（Protocol）。业务模块不得绕过端口读其他模块的私有存储。
- `src/jobpicky/matching/` — 匹配基线：纯确定性逻辑（`MatchingPort` 的实现），无 I/O，权重/阈值集中在 `MatchingConfig`。
- `src/jobpicky/infrastructure/` — 数据库等外部依赖的具体适配（async SQLAlchemy + asyncpg）。
- `alembic/` — 迁移。链式单头，新迁移必须接在现有头之后；并行任务不得从同一头各开终点。

核心架构不变量（违反即 bug）：岗位事实归 `catalog` 唯一所有；模型输出不能成为岗位事实；不完整采集不得关闭历史岗位；信息不足不得变成排除条件（宁放行勿误杀）；未实现的能力显式失败，不用假数据或占位接口伪装完成。

## 测试约定

- 离线优先：普通测试不依赖网络、数据库或真实模型；数据库集成测试（`tests/infrastructure/`）未设置 `JOBPICKY_TEST_DATABASE_URL` 时 skip，CI 用 service container 真实执行。
- 测试数据用工厂函数构造（参考 `tests/matching/factories.py`），注意 `ProfileSnapshot` 等契约是 frozen 且时间字段需带时区。

## 文档依据

优先级：`docs/requirements.md`（做什么/验收）> `docs/architecture.md`（公共契约与不变量）> `docs/development.md`（协作/验证/交付规则）> 代码现状。冲突时不得改需求迁就代码，也不得改架构掩盖偏差。每轮任务的实现计划留档在 `docs/plans/`。
