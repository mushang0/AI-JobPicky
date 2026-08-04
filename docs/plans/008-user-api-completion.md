# 用户 API 闭环实现计划

## 目标

按 `docs/api-requirements.md` 已确认的 API-001～API-020 完成四个可运行纵向切片；每个阶段通过相关测试和仓库质量门槛后创建独立提交，不推送远端。

## 阶段

1. 认证与积分：用户、Refresh Session、积分账户与流水迁移；Argon2id、HS256 Access JWT、Refresh Cookie 轮换/重用检测/注销、限流、必需与可选身份依赖，以及 API-010、API-014～018。
2. 岗位与收藏：统一规范化和安全回填、岗位查询索引、完整开放岗位池、匿名预览限制、组合筛选与稳定分页、岗位详情、收藏和五分钟筛选选项缓存，以及 API-001、API-009、API-011、API-019、API-020。
3. 用户画像：用户可写输入与只读快照、单画像多不可变版本、`base_version` 乐观并发、`Idempotency-Key`、招聘类型硬筛选，以及 API-012、API-013。
4. 推荐闭环：正式推荐记录、任务进度、当前画像绑定、50 条上限、历史成功去重、原子扣费与幂等退款、单用户活动任务唯一、反馈/软删除/分页，以及 API-002～API-008。

## 共同约束

- Router 只处理 HTTP，业务规则留在应用服务，数据库访问留在基础设施适配器。
- 岗位事实只来自目录；模型评估不覆盖岗位事实，未知字段继续保持未知。
- 密码、密码哈希、JWT、Refresh Token、Cookie 和敏感模型输入不进入日志或错误响应。
- 数据迁移保持单头链式；结构与回填分开表达，回填只映射可确认值。
- 不创建 PDF、AI 对话、忘记密码或其他未实现能力的占位接口。

## 验证

每阶段运行最接近改动的单元/契约/集成测试；提交前至少运行：

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

最终额外运行 `uv run mypy src tests`、Alembic 单头检查和离线迁移 SQL；若配置了 `JOBPICKY_TEST_DATABASE_URL`，再运行真实 PostgreSQL 集成测试。
