# AI JobPicky 首轮并行开发任务

状态：进行中

本轮用于验证两名开发者并行开发、分别提交分支、最终合并的协作方式。需求细节以 `docs/requirements.md` 和 `docs/architecture.md` 为准。

## 任务分配

| 方向 | 建议分支 | 主要开发位置 | 本轮需求 |
|---|---|---|---|
| 岗位采集与结构化 | `feat/first-ats-collector` | `collection` 模块及对应测试目录 | 选择一个真实 ATS 的离线样本，完成岗位列表、岗位详情和投递链接解析，统一输出为现有的 `CollectionBatch` 和 `CollectedJob` 结构 |
| Agent 推荐匹配 | `feat/matching-baseline` | `matching` 模块及对应测试目录 | 基于现有的 `ProfileSnapshot` 和 `JobFact`，实现第一版硬条件筛选、检索文本生成和候选岗位合并，为后续接入 Embedding 和大模型评估提供基础 |

## 边界说明

### 岗位采集分支

本轮只负责：

- 读取一个 ATS 的离线样本；
- 解析岗位列表和详情；
- 提取岗位名称、公司、地点、JD、详情链接和投递链接；
- 输出统一岗位结构；
- 编写对应解析测试。

暂不负责：

- 数据库写入；
- 岗位推荐；
- 用户画像；
- 大模型调用；
- 完整采集任务编排。

### Agent 推荐匹配分支

本轮只负责：

- 根据用户画像生成硬筛选条件；
- 根据用户画像生成岗位检索文本；
- 合并关键词召回和语义召回的候选结果；
- 编写对应匹配逻辑测试。

暂不负责：

- 爬取招聘网站；
- 修改岗位事实；
- 数据库和 API；
- 正式调用大模型；
- 完整推荐任务编排。

## 必须遵守的约束

1. 两个分支都从最新的 `main` 创建。
2. 两个开发者不要修改对方负责的模块。
3. 优先使用现有 DTO 和端口，不重复创建另一套数据结构。
4. 确实需要修改公共契约时，先同步后再修改。
5. 每个分支完成后单独提交 Pull Request，并确保现有测试通过。
6. 第一个 PR 合并后，另一个分支先同步最新 `main`，解决冲突并重新测试，再合并。

## 协作命令

创建分支：

```bash
git switch main
git pull origin main
git switch -c feat/对应任务
```

提交并推送：

```bash
git add .
git commit -m "feat: 完成本轮需求"
git push -u origin feat/对应任务
```

同步已合并的 `main`：

```bash
git fetch origin
git switch 自己的分支
git rebase origin/main
```

本轮结束后检查：是否修改相同文件、公共契约是否足够、合并冲突数量、任务边界，以及 Codex 是否能独立完成各自任务。
