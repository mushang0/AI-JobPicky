# matching-baseline 实现计划

## Context

任务单 `docs/tasks/001-first-parallel-development.md` 中「Agent 推荐匹配」分支：基于现有 `ProfileSnapshot` 和 `JobFact` 相关契约，实现第一版硬条件筛选条件生成、检索文本生成和候选岗位合并，为后续接入 Embedding 和大模型评估提供基础。

当前状态：`feat/matching-baseline` 分支已从最新 main 创建；基线干净（ruff 通过、22 测试全过）；`MatchingPort`（`src/jobpicky/ports.py:120`）已定义三个同步方法，但 `src/jobpicky/matching/` 模块尚不存在。

## 交付物

1. `src/jobpicky/matching/` 模块 — 实现 `MatchingPort`
2. `tests/matching/` 测试 — 离线、确定性、固定小数据集
3. `docs/plans/001-matching-baseline.md` — 本计划留档（新建 `docs/plans/` 目录）

## 模块设计

### 文件组织

```
src/jobpicky/matching/
├── __init__.py        # 导出 BaselineMatchingService、MatchingConfig
├── config.py          # MatchingConfig：融合权重、候选上限、最低分阈值
└── service.py         # BaselineMatchingService（实现 MatchingPort）
```

### MatchingConfig（config.py）

冻结 dataclass，版本化可调参数（架构 §4.8 要求阈值/上限/权重由配置管理）：

- `keyword_weight: float = 0.5`、`semantic_weight: float = 0.5`（校验非负且和为 1）
- `max_candidates: int = 50`
- `min_retrieval_score: float = 0.0`（默认不过滤，阈值调优留给评估集）

### build_filter_spec（service.py）

`ProfileSnapshot` → `HardFilterSpec` 的直接映射，不做任何推断：

- `target_locations` ← `profile.target_locations`（空列表 = 不限）
- `excluded_roles` ← `profile.excluded_roles`
- `education` ← `profile.education`（`None` = 不执行学历排除）
- `recruitment_types` ← **空列表**：`ProfileSnapshot` 没有招聘类型字段，信息不足不得擅自推断（requirements R2/§3.1）
- `only_open` ← `True`（默认只看在招岗位）
- `effective_extra_request` 是自然语言，无法确定性解析为硬条件，本轮**不影响** filter spec（注释说明，留给后续模型辅助理解，但模型永远不能覆盖确定性条件 — R3）

### build_query_text（service.py）

画像 → 一份同时供关键词召回和语义召回使用的检索文本：

- 组成部分按固定顺序拼接：`target_roles`、`skills`、`experience_summary`、`effective_extra_request`
- 每项 strip、去重（保持首次出现顺序）、忽略空白项，以换行连接
- `effective_extra_request` 按架构 §4.12 已在运行创建时合并好，直接使用，**不再调用** `merge_extra_request`
- 全部为空时返回空字符串（真实状态，不伪造）
- 确定性：同输入必得同输出

### merge_candidates（service.py）

两路 `SearchHit` → 去重融合的 `Candidate` 列表：

- 按 `job_id` 分组；`keyword_score` / `semantic_score` 分别取自对应渠道的 hit
- `retrieval_score = keyword_weight * (keyword_score or 0) + semantic_weight * (semantic_score or 0)`，天然保持在 0~1；双渠道召回的岗位得分更高
- `sources` 按固定顺序标记：两路都有 → `[KEYWORD, SEMANTIC]`，单路 → 对应单元素列表
- 过滤 `retrieval_score < min_retrieval_score` 的候选
- 排序：`retrieval_score` 降序，同分按 `job_id` 升序（保证可复现），截取前 `max_candidates`
- **显式失败**（raise `ValueError`）：
  - hit 的 `channel` 与所在列表不符（如 keyword_hits 里出现 `channel=SEMANTIC`）
  - 同一列表内同一 `job_id` 重复出现（上游 bug，不静默取 max）

## 测试设计（tests/matching/）

```
tests/matching/
├── factories.py           # make_profile(**overrides)、make_hit(job_id, score, channel)
├── test_filter_spec.py
├── test_query_text.py
└── test_merge_candidates.py
```

`factories.py`：工厂函数提供合法默认值（注意 `ProfileSnapshot` 是 frozen、`created_at` 需带时区），每个测试只覆盖关心的字段。

**test_filter_spec.py**
- 标准画像 → 字段逐一正确映射
- 空地点/空排除列表 → 不限制（空列表传递）
- `education=None` → 不执行学历排除
- `recruitment_types` 恒为空、`only_open` 恒为 True
- extra_request 不影响 filter spec

**test_query_text.py**
- 完整画像 → 包含 roles/skills/summary/extra_request，顺序固定
- 重复条目去重、空白项忽略
- 全空画像 → 空字符串
- 可复现：同输入两次调用结果相同

**test_merge_candidates.py**（对应验收场景 D 的融合部分）
- 双渠道召回同一岗位 → 去重、`sources=[KEYWORD, SEMANTIC]`、子分数归位、融合分正确
- 单渠道岗位 → `sources` 单元素、缺失子分数为 `None`
- 乱序输入 → 输出一致（可复现性）
- 自定义权重 → 融合分按权重计算
- `min_retrieval_score` 过滤、`max_candidates` 截断
- channel 与列表不符 → ValueError；同列表重复 job_id → ValueError

## 计划留档

实现完成后，将本计划保存为 `docs/plans/001-matching-baseline.md`（新建 `docs/plans/` 目录，供后续轮次任务计划复用），随实现一起提交。

## 边界（不做）

- 不修改 `contracts/`、`ports.py`、`collection` 模块
- 不做数据库、API、大模型调用、推荐编排
- 测试不需要 `JobFact`、真实简历或网络 fixture

## 验证

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest          # 现有 22 个测试 + 新增 matching 测试全过
```

提交：`feat: add matching baseline service`，推送 `feat/matching-baseline` 并单独提 PR。
