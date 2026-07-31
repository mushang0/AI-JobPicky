# JobPicky 前端 API 需求与目标契约

> 状态：已确认条目可用于开发，未确认能力必须显式标记
> 本文是当前用户前端 API 的新需求基准。已标记“已确认”的内容优先于现有 `requirements.md`、
> `architecture.md`、代码、数据库迁移和当前 OpenAPI；发生冲突时修改旧内容以符合本文，不沿用旧行为。
> 尚未实现的能力不得创建返回假数据的占位接口。同步完成后，可执行 Pydantic Schema、OpenAPI 和契约测试
> 必须与本文一致。

## 1. 确认进度

| 编号 | 页面 | 接口 | 状态 |
|---|---|---|---|
| API-001 | 岗位池（Job pool） | `GET /api/v1/jobs` | 已确认 |
| API-002 | 全部推荐 | `GET /api/v1/user/recommendations` | 已确认 |
| API-003 | 推荐任务 | `GET /api/v1/user/recommendation-runs` | 已确认 |
| API-004 | 新建推荐 | `POST /api/v1/user/recommendation-runs` | 已确认 |
| API-005 | 推荐任务状态 | `GET /api/v1/user/recommendation-runs/{run_id}` | 已确认 |
| API-006 | 单次推荐结果 | `GET /api/v1/user/recommendation-runs/{run_id}/results` | 已确认 |
| API-007 | 推荐反馈 | `PUT /api/v1/user/recommendations/{recommendation_id}/feedback` | 已确认 |
| API-008 | 删除推荐 | `DELETE /api/v1/user/recommendations/{recommendation_id}` | 已确认 |
| API-009 | 收藏岗位 | `PUT/DELETE /api/v1/user/saved-jobs/{job_id}` | 已确认 |
| API-010 | 推荐积分摘要 | `GET /api/v1/user/credits` | 已确认 |
| API-011 | 岗位详情 | `GET /api/v1/jobs/{job_id}` | 已确认 |
| API-012 | 当前求职画像 | `GET /api/v1/user/profiles/current` | 已确认 |
| API-013 | 保存求职画像 | `PUT /api/v1/user/profiles/current` | 已确认 |
| API-014 | 邮箱注册 | `POST /api/v1/auth/register` | 已确认 |
| API-015 | 邮箱密码登录 | `POST /api/v1/auth/login` | 已确认 |
| API-016 | 刷新登录状态 | `POST /api/v1/auth/refresh` | 已确认 |
| API-017 | 退出当前设备 | `POST /api/v1/auth/logout` | 已确认 |
| API-018 | 当前登录用户 | `GET /api/v1/auth/me` | 已确认 |
| API-019 | 收藏岗位列表 | `GET /api/v1/user/saved-jobs` | 已确认 |
| API-020 | 岗位筛选选项 | `GET /api/v1/jobs/filter-options` | 已确认 |

## 2. API-001 岗位池分页查询

### 2.1 页面目标

岗位池首页向匿名访问者展示有限的第一页岗位。登录用户可以继续翻页、调整每页数量、搜索、筛选，
并看到每个岗位真实的收藏状态。

该页面不展示完整 JD；点击岗位后通过 API-011 查询完整岗位详情。

### 2.2 接口

```http
GET /api/v1/jobs
```

该接口使用可选 Bearer 身份上下文：匿名请求可以访问公开预览，登录请求获得完整查询能力和用户收藏状态。
身份传递和失效处理遵循 §20～§27。

### 2.3 可见岗位池

1. 数据库中的岗位默认全部开放，不向用户提供岗位状态筛选。
2. 后端设置整个可见岗位池的数量上限 `visible_pool_limit`。
3. 岗位按 `last_confirmed_at DESC, id ASC` 确定稳定顺序，截取最新的 N 个岗位形成可见岗位池；
   N 为 `visible_pool_limit`。
4. 搜索、筛选和分页只在该可见岗位池内执行。
5. `pool_total` 是应用上限后的可见岗位数，即数据库岗位数与 `visible_pool_limit` 的较小值。
6. `total` 是当前登录用户应用搜索和筛选后，在可见岗位池内命中的岗位数。

开发阶段 `visible_pool_limit=5000`。它是后端配置，不提供首版管理端修改接口；未来只调整配置，不改变
API-001 的响应语义。

### 2.4 访问控制

| 行为 | 匿名访问者 | 登录用户 |
|---|---:|---:|
| 查看默认第一页 | 允许 | 允许 |
| 请求第二页及以后 | 需要登录 | 允许 |
| 使用搜索词 `q` | 需要登录 | 允许 |
| 使用任意筛选条件 | 需要登录 | 允许 |
| 调整 `page_size` | 不得超过公开预览上限 | 不得超过登录用户单页上限 |
| 读取 `is_saved` | 返回 `null` | 返回真实 `true` 或 `false` |

以下匿名请求返回 HTTP `401` 和稳定错误码 `AUTHENTICATION_REQUIRED`：

- `page >= 2`；
- 提供非空搜索词；
- 提供任意筛选条件；
- `page_size` 超过后端配置的公开预览上限。

默认 `page_size=30`，匿名公开预览最大 `30`，登录用户最大 `100`；用户传入的值必须为正整数。

### 2.5 查询参数

| 参数 | 类型 | 默认值 | 登录要求 | 语义 |
|---|---|---:|---:|---|
| `page` | `int` | `1` | `page >= 2` 时需要 | 从 1 开始的页码 |
| `page_size` | `int` | `30` | 超出公开预览上限时需要 | 用户选择的单页数量，同时受后端上限约束 |
| `q` | `str \| null` | `null` | 是 | 岗位模糊搜索词；空白按未提供处理 |
| `city` | `list[str]` | `[]` | 是 | 城市多选 |
| `company_nature` | `list[str]` | `[]` | 是 | 公司性质多选 |
| `source_id` | `list[str]` | `[]` | 是 | 岗位来源多选 |
| `recruitment_type` | `list[str]` | `[]` | 是 | 招聘类型多选 |
| `education` | `list[str]` | `[]` | 是 | 学历要求多选 |
| `graduation_year` | `list[int]` | `[]` | 是 | 届次多选 |
| `salary_min` | `int \| null` | `null` | 是 | 用户选择的薪资区间下限，单位为元/月 |
| `salary_max` | `int \| null` | `null` | 是 | 用户选择的薪资区间上限，单位为元/月 |

列表参数使用重复查询参数传递，不使用逗号拼接：

```http
GET /api/v1/jobs?page=1&page_size=30&city=上海&city=北京&company_nature=民营企业
```

### 2.6 搜索语义

- 搜索前先去除首尾空白并进行大小写无关的文本规范化。
- 对岗位名称、公司名称、工作地点和 JD 正文进行部分匹配。
- 多个搜索词命中任意一个即可进入结果；命中词更多的岗位排序更靠前。
- 有搜索词时按相关度降序，再按 `last_confirmed_at DESC, id ASC` 保证稳定顺序。
- 没有搜索词时按 `last_confirmed_at DESC, id ASC` 排序。
- 首版不使用大模型搜索、语义搜索或拼写纠错。

### 2.7 筛选语义

- 同一筛选项的多个值使用 OR，例如上海或北京。
- 不同筛选项之间使用 AND，例如“上海或北京”且“民营企业”。
- 字段未知时默认保留岗位；只有字段已知且能够确认不匹配时才排除。
- 薪资筛选同样遵循“未知保留”：只有已知薪资信息能够证明岗位区间与查询区间不相交时才排除。
- `salary_min` 和 `salary_max` 同时存在时，`salary_min` 不得大于 `salary_max`。

筛选值使用 §32 的统一规范化语义；前端通过 API-020 获得可用选项，不自行维护另一套字典。

### 2.8 成功响应

```json
{
  "items": [
    {
      "id": "job-123",
      "title": "Python 后端工程师",
      "company_name": "示例科技",
      "company_nature": "民营企业",
      "locations": ["上海"],
      "source": {
        "id": "source-1",
        "name": "Moka"
      },
      "recruitment_type": "校招",
      "education_requirement": "本科",
      "graduation_years": [2027],
      "salary_min": 15000,
      "salary_max": 25000,
      "salary_months": 13,
      "description_preview": "负责 Python 后端服务开发……",
      "published_at": "2026-07-30T08:00:00Z",
      "last_confirmed_at": "2026-07-31T08:00:00Z",
      "is_saved": true
    }
  ],
  "total": 4308,
  "page": 1,
  "page_size": 30,
  "pool_total": 4596
}
```

岗位列表项字段语义：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 岗位不透明标识 |
| `title` | `str` | 岗位名称 |
| `company_name` | `str` | 公司名称 |
| `company_nature` | `str \| null` | 公司性质，未知时为 `null` |
| `locations` | `list[str]` | 工作地点，未知时为空数组 |
| `source` | `object` | 岗位来源标识和前端显示名称 |
| `recruitment_type` | `str \| null` | 招聘类型 |
| `education_requirement` | `str \| null` | 学历要求 |
| `graduation_years` | `list[int]` | 届次要求；空数组表示未知或不限 |
| `salary_min` | `int \| null` | 月薪下限，单位为元 |
| `salary_max` | `int \| null` | 月薪上限，单位为元 |
| `salary_months` | `int \| null` | 年发薪月数 |
| `description_preview` | `str \| null` | 后端生成的纯文本 JD 预览，不返回完整 JD |
| `published_at` | `datetime \| null` | 来源发布时间 |
| `last_confirmed_at` | `datetime` | 最近一次确认岗位仍存在的时间 |
| `is_saved` | `bool \| null` | 匿名时为 `null`；登录后为真实收藏状态 |

没有结果时仍返回 HTTP `200`，其中 `items=[]`、`total=0`。登录用户请求超过最后一页时也返回空页。

### 2.9 错误响应

| HTTP 状态 | 错误码 | 场景 |
|---:|---|---|
| `401` | `AUTHENTICATION_REQUIRED` | 匿名用户尝试翻页、搜索、筛选或突破公开预览上限 |
| `422` | `VALIDATION_ERROR` | 页码、单页数量或薪资区间等参数非法 |
| `500` | `INTERNAL_ERROR` | 未预期的服务端错误；响应不得暴露堆栈或内部查询信息 |

错误响应沿用项目统一的 `ErrorBody` 结构。

### 2.10 明确不包含

- 不返回 `pool_updated_at`。
- 不返回或计算 `HOT JOB` 标签。
- 不接受岗位状态筛选。
- 不在列表中返回完整 JD、内部去重键、Embedding 或原始采集响应。
- 不在本接口中修改收藏状态。

### 2.11 关联接口与配置

- 筛选选项：API-020；
- 收藏和取消收藏：API-009；
- 收藏列表：API-019；
- 岗位详情：API-011；
- 登录与身份传递：API-014～API-018；
- `visible_pool_limit` 首版只通过后端配置管理，不增加管理接口。

### 2.12 验收场景

1. 匿名用户不带搜索和筛选请求第一页，获得不超过公开预览上限的岗位，且 `is_saved=null`。
2. 匿名用户请求第二页、搜索、筛选或超大 `page_size`，得到 `401 AUTHENTICATION_REQUIRED`。
3. 登录用户能够翻页、调整合法 `page_size`、搜索和组合筛选，并得到真实 `is_saved`。
4. 数据库岗位数超过 `visible_pool_limit` 时，只取 `last_confirmed_at` 最新的 N 个岗位进入可见池。
5. 开启任一筛选时，缺少该字段的岗位仍被保留，已知且不匹配的岗位被排除。
6. 搜索或筛选无命中时返回成功空页，不伪造岗位。

## 3. 推荐页面公共规则

### 3.1 登录要求

推荐页面及本章用户接口全部要求登录。除 API-001 明确允许的岗位池第一页公开预览外，后续未特别
说明的用户功能都默认需要登录。

用户只能读取和修改自己的推荐任务、推荐结果、积分、收藏与反馈。访问其他用户的资源时不泄露资源
是否存在。

### 3.2 推荐任务与推荐结果

- 一个推荐任务代表用户点击一次“新建推荐”产生的一次独立推荐事件。
- 单次任务最多评估 50 个候选岗位，因此最多产生 50 条成功推荐。
- 50 是单次推荐任务的候选和结果上限，不是“全部推荐”列表的分页上限或累计总数上限。
- 用户完成多次推荐任务后，“全部推荐”的累计数量可以超过 50。
- 只有 AI 返回 `matched=true` 的岗位才成为正式推荐结果。
- 用户已经成功推荐过的岗位，包含后来软删除的推荐，在后续任务中永久跳过。
- 曾进入 AI 评估但 `matched=false` 的岗位不进入推荐列表，后续任务仍可再次评估。
- 没有剩余候选时任务正常成功并返回空结果。
- 推荐岗位必须持久化并关联 `user_id`、`run_id` 和 `job_id`。岗位事实仍归岗位目录所有；推荐记录
  保存用于历史追溯的岗位事实快照、AI 评估、推荐时间和用户交互状态。

### 3.3 AI 分数与中文内容

- `retrieval_score` 是系统内部的关键词与语义召回融合分，不在前端推荐卡片展示。
- `match_score` 是 AI 返回的 0～100 匹配分，前端以百分比展示。
- 首版不设置 `match_score >= 75` 或其他数值阈值；是否进入推荐只由 AI 的 `matched` 判断。
- AI 后端必须直接输出中文的 `reason`、`matched_strengths`、`gaps` 和 `evidence`。
- 前端不翻译、不改写 AI 内容，只把英文 JSON key 映射成中文标题。

### 3.4 推荐卡片

推荐卡片优先展示以下内容：

| 数据字段 | 中文展示 |
|---|---|
| `job.title` | 岗位名称 |
| `job.company_name` | 公司名称 |
| `job.locations` | 工作城市 |
| `job.company_nature` | 公司性质 |
| `assessment.match_score` | AI 匹配度，例如 `89%` |
| `assessment.reason` | 推荐理由 |
| `assessment.matched_strengths` | 匹配优势 |
| `assessment.gaps` | 能力缺口 |
| `assessment.evidence` | 匹配依据 |
| `recommended_at` | 推荐时间 |
| `job.first_seen_at` | 岗位发现时间 |

展示规则：

- 不显示原始英文字段名。
- 公司性质为空时隐藏该项。
- 匹配优势、能力缺口或匹配依据为空时隐藏对应区域。
- 卡片不展示岗位薪资、学历、届次、完整 JD、来源标识或内部检索分。
- 卡片提供收藏、点赞、点踩和删除推荐四个操作。
- 点击卡片通过 API-011 打开统一岗位详情；岗位池、推荐和收藏列表不创建平行的岗位详情接口。

推荐卡片响应使用专门的列表视图，不直接把完整 `JobFact` 塞入分页结果：

```json
{
  "recommendation_id": "rec-123",
  "run_id": "run-123",
  "recommended_at": "2026-07-31T08:00:00Z",
  "job": {
    "id": "job-123",
    "title": "Python 后端工程师",
    "company_name": "示例科技",
    "company_nature": "民营企业",
    "locations": ["上海"],
    "first_seen_at": "2026-07-20T08:00:00Z"
  },
  "assessment": {
    "match_score": 89,
    "reason": "该岗位与用户的 Python 后端经历高度匹配。",
    "matched_strengths": ["具有 Python 后端开发经验"],
    "gaps": ["缺少大型系统实践"],
    "evidence": ["项目经历中使用过 FastAPI"]
  },
  "is_saved": true,
  "feedback": "LIKE"
}
```

## 4. API-002 全部推荐

```http
GET /api/v1/user/recommendations
```

该接口跨所有已完成推荐任务聚合用户成功推荐的岗位。每个用户的同一岗位只出现一次，软删除的推荐
不进入该列表。

查询参数：

| 参数 | 类型 | 默认值 | 语义 |
|---|---|---:|---|
| `page` | `int` | `1` | 从 1 开始的页码 |
| `page_size` | `int` | `10` | 用户可调整，最大 50 |
| `sort` | `str` | `recommended_at_desc` | 排序方式 |

`sort` 只接受：

```text
recommended_at_desc
match_score_desc
```

- `recommended_at_desc`：最新推荐优先。
- `match_score_desc`：AI 匹配度最高优先。
- 排序值相同时使用 `recommendation_id ASC` 保证分页稳定。

响应使用统一分页外形，`items` 为 §3.4 的推荐卡片视图：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10
}
```

## 5. API-003 推荐任务列表

```http
GET /api/v1/user/recommendation-runs
```

推荐任务按 `created_at DESC, run_id ASC` 分页返回。

| 参数 | 类型 | 默认值 | 约束 |
|---|---|---:|---|
| `page` | `int` | `1` | 必须为正整数 |
| `page_size` | `int` | `20` | 最大 100 |

每条任务记录至少包含：

```json
{
  "run_id": "run-123",
  "status": "SUCCEEDED",
  "current_step": "COMPLETE",
  "progress_percent": 100,
  "created_at": "2026-07-31T08:00:00Z",
  "started_at": "2026-07-31T08:00:01Z",
  "finished_at": "2026-07-31T08:00:20Z",
  "counts": {
    "evaluated": 50,
    "recommended": 8
  },
  "credits": {
    "cost": 100,
    "refunded": false,
    "net_spent": 100
  },
  "error": null
}
```

- 首版对用户只出现 `PENDING`、`RUNNING`、`SUCCEEDED`、`FAILED` 四种状态。
- 失败记录返回经过脱敏且内容为中文的错误说明。
- 系统或 AI 失败退款后，`credits.refunded=true`、`net_spent=0`，前端展示“已退回”。
- 点击一条任务后通过 API-006 查看该次任务返回的岗位。
- 任务结果中的软删除推荐仍然保留并标记，满足历史追溯要求。

## 6. API-004 新建推荐任务

```http
POST /api/v1/user/recommendation-runs
Idempotency-Key: client-generated-key
Content-Type: application/json
```

请求体：

```json
{
  "extra_request": "本次优先推荐 Python 后端岗位"
}
```

- 服务端自动使用该用户当前最新且不可变的画像版本。
- `extra_request` 是本次任务的可选补充要求，创建时与画像要求合并并冻结。
- 同一用户同一时间只允许一个 `PENDING` 或 `RUNNING` 的推荐任务。
- 相同幂等键和相同请求重试时返回既有任务，不重复创建或扣费。
- 不同请求试图复用同一幂等键时返回冲突。

成功返回 HTTP `202`：

```json
{
  "run_id": "run-123",
  "status": "PENDING",
  "credits_charged": 100,
  "balance_after": 9900
}
```

积分规则：

- 开发阶段单次推荐价格固定配置为 `100`；生产价格以后端配置和 API-010 返回值为准。
- 任务创建和扣费在同一业务边界内完成；扣费失败时不创建任务。
- 余额不足时不创建任务、不扣费，返回稳定错误码 `INSUFFICIENT_CREDITS`。
- 系统故障或 AI 调用失败时自动退款，退款操作必须幂等。
- 正常完成但没有推荐结果时仍然扣费。
- 没有当前画像时不创建任务，并返回明确的画像缺失错误。
- 所有面向用户的错误 `message` 使用中文；稳定的机器错误码仍使用英文大写字符串。

## 7. API-005 推荐任务状态与进度

```http
GET /api/v1/user/recommendation-runs/{run_id}
```

状态响应包含 API-003 的完整任务记录。运行中的前端每 2 秒轮询一次；首版不使用 WebSocket 或 SSE，
也不提供任务取消功能。

进度映射：

| `current_step` | 中文显示 | `progress_percent` |
|---|---|---:|
| `PENDING` | 等待开始 | 0 |
| `PROFILE` | 读取用户画像 | 10 |
| `FILTER` | 筛选符合条件的岗位 | 25 |
| `RETRIEVE` | 召回候选岗位 | 45 |
| `EVALUATE` | AI 正在评估岗位 | 50～90 |
| `SAVE` | 保存推荐结果 | 95 |
| `COMPLETE` | 推荐完成 | 100 |

- `EVALUATE` 根据已经完成的真实评估批次，在 50～90 之间推进。
- 只有成功完成的任务显示 100。
- 失败任务停留在失败前的实际进度，同时显示中文失败原因。
- 不返回虚假的预计剩余时间。

## 8. API-006 单次推荐结果

```http
GET /api/v1/user/recommendation-runs/{run_id}/results
```

| 参数 | 类型 | 默认值 | 约束 |
|---|---|---:|---|
| `page` | `int` | `1` | 必须为正整数 |
| `page_size` | `int` | `10` | 最大 50 |

该接口只返回该次任务中 AI 判断为 `matched=true` 的岗位，使用 §3.4 的推荐卡片视图并增加：

```json
{
  "is_deleted": false,
  "deleted_at": null
}
```

- 软删除的推荐仍在该接口中返回，且 `is_deleted=true`。
- 未完成任务返回空页，任务是否应该已有结果以 API-005 的 `status` 为准。
- 同一个任务的结果使用稳定保存顺序，不提供额外排序参数。

## 9. API-007 推荐反馈

```http
PUT /api/v1/user/recommendations/{recommendation_id}/feedback
Content-Type: application/json
```

请求体：

```json
{
  "feedback": "LIKE"
}
```

`feedback` 允许：

```text
LIKE | DISLIKE | null
```

- 点赞与点踩互斥。
- 再次点击当前选中状态时，前端发送 `null` 取消反馈。
- 点击相反状态时直接覆盖为新状态。
- 重复提交相同状态保持幂等。
- 反馈与收藏相互独立。
- 首版只记录反馈，不自动训练模型，也不立即修改后续推荐排序。

成功响应：

```json
{
  "recommendation_id": "rec-123",
  "feedback": "LIKE"
}
```

## 10. API-008 删除推荐

```http
DELETE /api/v1/user/recommendations/{recommendation_id}
```

- 删除是推荐记录的软删除，成功返回 HTTP `204`。
- 推荐从 API-002 隐藏，但仍通过 API-006 保留在原任务历史中并标记为已删除。
- 不删除岗位目录中的岗位事实。
- 被删除的岗位仍属于历史成功推荐，后续推荐继续跳过。
- 删除推荐不取消收藏，已收藏岗位仍可在收藏列表查看。
- 重复删除保持幂等。

## 11. API-009 收藏岗位

收藏：

```http
PUT /api/v1/user/saved-jobs/{job_id}
```

取消收藏：

```http
DELETE /api/v1/user/saved-jobs/{job_id}
```

- 收藏按 `user_id + job_id` 唯一保存。
- 收藏和取消收藏都必须幂等。
- 岗位池、推荐卡片、岗位详情和收藏列表共用同一收藏状态。
- 收藏变化不影响推荐记录、反馈状态或历史推荐去重。
- 收藏列表通过 API-019 分页查询；取消收藏后该岗位从列表中移除。

状态响应：

```json
{
  "job_id": "job-123",
  "is_saved": true
}
```

## 12. API-010 推荐积分摘要

```http
GET /api/v1/user/credits
```

成功响应：

```json
{
  "balance": 10000,
  "recommendation_cost": 100
}
```

开发阶段新注册用户初始积分为 `10000`，每次推荐任务价格为 `100`。两项都由后端配置并通过真实余额与
价格返回；未来生产环境的初始赠送、余额上限和价格另行调整，不改变本接口结构。

- 注册用户时必须原子初始化积分账户和一条 `SIGNUP_BONUS +10000` 流水；失败时注册整体回滚。
- 创建推荐任务时原子写入 `RECOMMENDATION_DEBIT -100`，余额不得变为负数。
- 系统或 AI 失败时幂等写入 `RECOMMENDATION_REFUND +100`。
- 开发阶段不设置额外业务余额上限，只使用非负 64 位整数存储；生产上限待真实运营规则确定。
- 首版只展示当前余额和单次推荐价格，不提供积分流水页面。

## 13. API-011 统一岗位详情

```http
GET /api/v1/jobs/{job_id}
```

- 岗位池、推荐卡片和收藏列表复用该接口。
- 该接口允许匿名访问，使用可选 Bearer 身份；公开岗位来自公开招聘源，列表登录限制不用于阻止稳定详情链接。
- 详情不受 `visible_pool_limit` 限制。数据库中仍保留的开放、关闭或待确认岗位都可查询，并明确返回
  `status`；关闭岗位的前端投递按钮必须禁用或提示岗位已关闭。
- 匿名时 `is_saved=null`，登录时返回当前用户真实收藏状态。
- 推荐卡片中的 AI 评估归推荐记录所有，不写入岗位详情事实，也不由本接口返回。

成功响应：

```json
{
  "id": "job-123",
  "title": "Python 后端工程师",
  "company_name": "示例科技",
  "company_nature": "民营企业",
  "locations": ["上海"],
  "source": {
    "id": "source-1",
    "name": "Moka"
  },
  "recruitment_type": "校招",
  "education_requirement": "本科",
  "graduation_years": [2027],
  "salary_min": 15000,
  "salary_max": 25000,
  "salary_months": 13,
  "description": "负责 Python 后端服务开发……",
  "detail_url": "https://example.com/jobs/123",
  "apply_url": "https://example.com/jobs/123/apply",
  "status": "OPEN",
  "published_at": "2026-07-30T08:00:00Z",
  "deadline_at": "2026-08-31T15:59:59Z",
  "first_seen_at": "2026-07-20T08:00:00Z",
  "last_confirmed_at": "2026-07-31T08:00:00Z",
  "updated_at": "2026-07-31T08:00:00Z",
  "is_saved": true
}
```

字段未知时使用 `null` 或空数组。响应不返回 `fact_version`、内部去重键、Embedding、原始采集响应或秘密
来源配置。不存在的 `job_id` 返回 HTTP `404 NOT_FOUND`，不能伪造岗位。

## 14. 推荐页面验收场景

1. 一次推荐任务最多评估 50 个候选，成功推荐数不超过 50；多次任务可以让累计推荐数超过 50。
2. AI 返回 `matched=true` 的岗位被持久化并出现在“全部推荐”，后续任务不再处理这些岗位。
3. `matched=false` 的岗位不进入推荐列表，但仍可在后续任务中再次评估。
4. 推荐卡片展示中文 AI 内容和 AI 匹配分，不展示内部召回分，也不应用 75 分阈值。
5. 点赞、点踩、取消反馈、收藏和取消收藏均可重复安全执行。
6. 软删除推荐后，其岗位不再出现在“全部推荐”，但历史任务仍可追溯且后续推荐继续跳过。
7. 同一用户同时只能有一个运行中任务，重复请求不会重复扣费。
8. 系统或 AI 失败时任务标记失败并自动退款；正常空结果任务成功且不退款。
9. 任务进度随真实阶段推进，成功完成为 100%，失败不伪装完成。
10. 所有用户可见错误说明使用中文，且不会泄露其他用户数据、模型敏感输入或内部堆栈。

## 15. 用户画像页面公共规则

### 15.1 页面定位

首版页面名称为“我的求职画像”。它是推荐系统使用的结构化求职档案，不是包含姓名、手机号、邮箱、
身份证或照片的传统完整简历。

首版只支持用户直接填写表单。PDF 简历解析和 AI 对话完善画像属于未来能力，未实现前不提供可点击入口、
占位接口或伪造结果。

未来三种录入方式都必须汇入同一份可校对画像草稿：

```text
手工表单（首版） ─┐
PDF 解析（未来） ─┼→ 统一画像草稿 → 用户检查和修正 → 不可变画像快照 → 新推荐任务
AI 对话（未来） ─┘
```

PDF 解析或 AI 对话不得直接覆盖正式画像，也不得自动发起推荐。

### 15.2 单一当前画像与版本

- 一个用户只维护一个逻辑上的当前画像，不支持多份画像切换。
- 第一次保存生成版本 `1`；有实际字段变化时生成递增的新版本。
- `id` 在同一用户的所有画像版本中保持不变。
- 内容完全相同时不创建无意义的新版本。
- 历史画像快照不可修改，首版不提供画像版本列表、恢复或删除功能。
- 正在执行和已经完成的推荐任务继续绑定创建任务时的画像版本，不受后续修改影响。
- 新建推荐任务自动读取用户当时最新的已保存画像；未保存的表单内容不参与推荐。

### 15.3 页面表单

页面使用一个表单并分成四组：

| 分组 | 中文字段 | 请求字段 | 首版交互 | 推荐语义 |
|---|---|---|---|---|
| 求职目标 | 目标岗位 | `target_roles` | 标签输入、多值 | 召回和 AI 判断 |
| 求职目标 | 目标城市 | `target_locations` | 城市多选，可不限 | 硬筛选 |
| 求职目标 | 招聘类型 | `recruitment_types` | 校招、社招、实习多选，可不限 | 硬筛选 |
| 求职目标 | 期望税前月薪下限 | `expected_salary_min` | 非负整数，单位元/月，可不限 | 硬筛选 |
| 教育背景 | 最高学历 | `education` | 高中及以下、专科、本科、硕士、博士，可不填 | 硬筛选 |
| 教育背景 | 毕业年份 | `graduation_year` | 年份选择，可不填 | 硬筛选 |
| 技能与经历 | 掌握技能 | `skills` | 标签输入、多值 | 召回和 AI 判断 |
| 技能与经历 | 经历与项目摘要 | `experience_summary` | 单个多行文本框 | AI 判断及证据 |
| 排除与补充 | 明确排除的岗位 | `excluded_roles` | 标签输入、多值 | 硬筛选 |
| 排除与补充 | 其他长期要求 | `extra_request` | 多行文本框 | AI 判断参考 |

首版不拆分多段工作经历、项目经历或教育经历。经历与项目统一通过 `experience_summary` 输入；根据真实
PDF 样本确认确有必要后，再扩展为结构化经历列表。

首版确定不加入公司性质偏好。公司性质只用于岗位池筛选；未来如需进入画像，必须先单独确认它是硬条件
还是 AI 软偏好。

### 15.4 字段校验与规范化

- `target_roles` 为 1～10 项。
- `target_locations` 最多 10 项。
- `recruitment_types` 最多 3 项，值只允许“校招”“社招”“实习”。
- `skills` 最多 50 项，`excluded_roles` 最多 20 项。
- 所有标签单项为 1～100 个字符。
- `skills` 和 `experience_summary` 至少填写一项。
- `target_locations=[]` 表示不限地点。
- `recruitment_types=[]` 表示不限招聘类型。
- `expected_salary_min` 表示税前月薪下限，单位为人民币元/月，范围为 `0～1000000`。
- `graduation_year` 范围为请求发生年份向前 80 年至向后 10 年。
- 标签去除首尾空白并按规范化值去重，同时保留适合展示的原始大小写。
- `experience_summary` 最多 5000 个字符，`extra_request` 最多 1000 个字符。
- 用户请求不得提交或修改 `warnings`；该字段由后端根据校验结果生成。
- 校验错误和用户可见警告必须使用中文，机器错误码继续使用稳定的英文大写字符串。

### 15.5 硬筛选边界

以下字段形成确定性硬筛选条件：

```text
target_locations
recruitment_types
education
graduation_year
expected_salary_min
excluded_roles
```

`target_roles`、`skills`、`experience_summary` 和 `extra_request` 用于召回或 AI 判断，不伪装成确定性硬条件。
`extra_request` 是长期自然语言偏好，页面必须说明它只作为 AI 评估参考。

所有硬筛选继续遵循“未知保留”：岗位没有城市、招聘类型、学历、届次或薪资事实时，不得仅因字段缺失将其
排除。只有岗位已知事实能够确认冲突时才排除。

### 15.6 页面状态与交互

- 没有画像时显示空表单和“保存画像”。
- 已有画像时加载最新版本并显示“保存修改”。
- 表单有未保存修改时，离开页面前提醒用户确认。
- 保存期间禁用提交按钮，失败时保留当前填写内容。
- 保存成功后显示保存时间，并可提供“去获取推荐”入口；保存本身不扣积分，也不自动发起推荐。
- 发生版本冲突时提示“画像已在其他页面更新，请刷新后重试”。
- 首版不实现服务端草稿或自动保存，也不把完整画像长期写入浏览器 `localStorage`。

## 16. API-012 查询当前画像

```http
GET /api/v1/user/profiles/current
```

- 必须登录，用户只能查询自己的画像。
- 成功时返回当前最新的不可变画像快照。
- 用户尚未建立画像时返回 HTTP `404`、错误码 `PROFILE_NOT_FOUND` 和中文说明；前端将其作为正常的首次
  建立状态处理。
- 登录上下文已经标识用户，响应不重复返回 `user_id`。
- 不返回原始简历、联系方式、内部模型输入或其他受保护数据。

成功响应示例：

```json
{
  "id": "profile-123",
  "version": 3,
  "target_roles": ["Python 后端工程师"],
  "target_locations": ["上海", "杭州"],
  "recruitment_types": ["社招"],
  "skills": ["Python", "FastAPI", "PostgreSQL"],
  "education": "本科",
  "graduation_year": 2024,
  "expected_salary_min": 20000,
  "experience_summary": "使用 FastAPI 开发过订单系统，负责接口和数据库设计。",
  "excluded_roles": ["销售", "客服"],
  "extra_request": "不接受长期出差，希望技术栈以 Python 为主。",
  "warnings": [],
  "created_at": "2026-07-31T08:00:00Z"
}
```

## 17. API-013 保存当前画像

```http
PUT /api/v1/user/profiles/current
Idempotency-Key: client-generated-key
Content-Type: application/json
```

该接口以完整表单替换当前画像状态：没有画像时创建版本 `1`，已有画像时在内容变化后创建下一版本。
首版不再分别暴露“从简历创建”的 `POST` 和按画像 ID 修改的 `PATCH`；现有架构中的旧契约应在同步阶段
替换为本接口。

请求示例：

```json
{
  "base_version": 2,
  "target_roles": ["Python 后端工程师"],
  "target_locations": ["上海", "杭州"],
  "recruitment_types": ["社招"],
  "skills": ["Python", "FastAPI", "PostgreSQL"],
  "education": "本科",
  "graduation_year": 2024,
  "expected_salary_min": 20000,
  "experience_summary": "使用 FastAPI 开发过订单系统，负责接口和数据库设计。",
  "excluded_roles": ["销售", "客服"],
  "extra_request": "不接受长期出差，希望技术栈以 Python 为主。"
}
```

`base_version` 规则：

- 首次创建时为 `null`。
- 修改时必须等于服务端当前版本。
- 不匹配时返回 HTTP `409` 和错误码 `PROFILE_VERSION_CONFLICT`，不覆盖较新的画像。

写入规则：

- `Idempotency-Key` 必填；同一次保存的前端重试和重复点击必须复用同一个键。
- 请求中的用户身份来自登录上下文，不接受 `user_id`。
- 请求不接受 `id`、`version`、`created_at` 或 `warnings`。
- 首次创建成功返回 HTTP `201`；修改或内容未变化时返回 HTTP `200`。
- 服务端先处理相同幂等键的重放，再校验 `base_version`；不同幂等键携带过期版本时仍返回版本冲突。
- `base_version` 有效且规范化后的内容与当前快照相同时不增加版本，直接返回当前快照。
- 相同用户、相同幂等键和相同请求重复提交时返回既有结果，不重复创建版本。
- 不同请求复用同一幂等键时返回 HTTP `409`。
- 画像保存与推荐任务创建是两个独立操作；本接口不检查积分、不扣费、不自动启动推荐。

响应使用与 API-012 相同的完整画像快照结构。

错误响应：

| HTTP 状态 | 错误码 | 场景 |
|---:|---|---|
| `401` | `AUTHENTICATION_REQUIRED` | 未登录 |
| `409` | `PROFILE_VERSION_CONFLICT` | `base_version` 已过期 |
| `409` | `IDEMPOTENCY_CONFLICT` | 幂等键被不同请求复用 |
| `422` | `VALIDATION_ERROR` | 必填项、列表、年份、薪资或文本长度不合法 |
| `500` | `INTERNAL_ERROR` | 未预期服务端错误，不暴露内部堆栈 |

## 18. 未来画像录入方式

### 18.1 PDF 简历解析

未来 PDF 解析使用独立异步导入流程，而不是扩展 API-013 接受文件：

```http
POST /api/v1/user/profile-imports
GET  /api/v1/user/profile-imports/{import_id}
```

流程为上传校验、文本提取、结构化解析、返回草稿与无法确认字段、用户校对、通过 API-013 保存。原始 PDF
按敏感数据处理，不进入普通画像响应或日志；文件大小、页数、格式和保留周期在实现该能力时根据真实样本
单独确认。

### 18.2 AI 对话完善画像

未来 AI 对话只修改独立草稿，并在页面同步展示字段变化。AI 必须基于用户输入，不得编造经历；只有用户
确认并调用 API-013 后才生成正式画像版本。具体会话接口等实现时再确认，现在不创建占位契约。

## 19. 用户画像页面验收场景

1. 未登录用户无法查询或保存画像。
2. 没有画像的用户进入页面后看到空表单，可以通过一次有效提交创建版本 `1`。
3. 目标岗位为空，或技能和经历摘要同时为空时，保存失败并返回中文校验信息。
4. 空目标城市和空招聘类型按“不限”保存，不被转换成字符串标签。
5. 修改画像创建新版本，历史推荐仍绑定旧版本；新推荐使用最新版本。
6. 相同内容、重复幂等请求和重复点击保存都不会创建重复版本。
7. 旧页面提交过期 `base_version` 时不会覆盖新数据，并获得中文冲突提示。
8. 除并发控制所需的 `base_version` 外，用户不能提交 `warnings`、`user_id`、`id`、`version`、
   `created_at` 或其他服务端字段。
9. 结构化硬条件只在已知岗位事实明确冲突时排除岗位，未知字段继续保留。
10. 首版页面没有可操作的 PDF 或 AI 对话假入口，也不会保存或记录无关个人敏感信息。

## 20. 登录与身份公共规则

### 20.1 首版范围

首版使用邮箱和密码完成自助注册与登录。注册成功后自动登录；暂不接入邮件服务，因此不验证邮箱所有权，
也不提供邮箱验证码、忘记密码或邮件重置入口。该边界适用于内测，公开生产前必须重新确认邮箱验证与账户
恢复能力。

首版登录页面只包含：

- 邮箱；
- 密码；
- 登录按钮；
- 前往注册入口；
- 中文校验和登录错误；
- 登录成功后返回原访问页面。

未实现能力不得展示可操作的假入口。首版不显示忘记密码、验证码登录、手机号登录、第三方登录或多因素
认证按钮。

### 20.2 账户与角色

- 普通用户和管理员使用同一账户体系。
- 公开注册只能创建 `USER`，请求不得包含或指定角色。
- `ADMIN` 只能通过受控的后台或部署流程创建，不能通过公开 API 提权。
- 用户 ID 是不透明标识；业务数据通过登录上下文取得 `user_id`，不信任请求体或查询参数提供的用户 ID。
- 开发阶段新注册用户由服务端初始化 `10000` 积分，注册请求不能指定金额；余额不写入登录响应，前端通过
  API-010 查询。

### 20.3 令牌组合

首版使用以下组合：

| 凭据 | 形式 | 前端保存位置 | 默认有效期 | 用途 |
|---|---|---|---:|---|
| Access Token | JWT | 页面内存 | 15 分钟 | 访问受保护 API |
| Refresh Token | 高熵随机令牌 | HttpOnly Cookie | 30 天 | 轮换 Access Token |

Refresh Token 不做成无状态 JWT。服务端保存其哈希和会话状态，以支持轮换、退出和盗用重放检测；数据库
不得保存原始 Refresh Token。

受保护接口统一使用：

```http
Authorization: Bearer <access_token>
```

前端不得把 Access Token 或 Refresh Token 写入 `localStorage`、`sessionStorage` 或普通 JavaScript 可读
Cookie。Access Token 只保存在内存；页面重新加载时通过 API-016 恢复会话。

### 20.4 前端会话流程

1. 登录或注册成功后，将响应中的 Access Token 保存到内存，Refresh Token 由浏览器 Cookie 管理。
2. 页面重新加载时调用 API-016；成功后再按需调用 API-018 读取当前用户。
3. 受保护接口返回 `401` 时，前端最多自动刷新并重试原请求一次，禁止无限刷新循环。
4. 刷新失败后清除内存身份状态并进入登录页。
5. 用户主动退出时调用 API-017，并立即清除内存中的 Access Token 和用户信息。
6. 匿名用户触发需要登录的岗位池翻页、搜索或筛选时，登录成功后返回原页面和原操作上下文。

## 21. API-014 邮箱注册

```http
POST /api/v1/auth/register
Content-Type: application/json
```

请求体：

```json
{
  "email": "user@example.com",
  "password": "用户输入的密码"
}
```

注册规则：

- 邮箱去除首尾空白并按大小写不敏感的规范化值唯一保存。
- 邮箱必须是合法格式，规范化后最长 254 个字符。
- 密码确认由前端完成，后端不接收 `password_confirmation`。
- 注册请求不得包含 `id`、`role`、`status`、积分或其他服务端字段。
- 密码校验通过后只保存密码哈希，不保存或记录明文。
- 相同规范化邮箱重复注册返回冲突，不创建第二个账户。
- 注册成功创建 `USER` 账户和独立登录会话，并直接返回登录结果。
- 用户账户、积分账户和 `SIGNUP_BONUS +10000` 流水必须在同一业务事务中成功或回滚。
- 当前版本不向邮箱发送验证邮件，邮箱只作为唯一登录标识，不代表系统已经确认邮箱所有权。

成功返回 HTTP `201`，响应体与 API-015 相同，并设置新的 Refresh Cookie。

## 22. API-015 邮箱密码登录

```http
POST /api/v1/auth/login
Content-Type: application/json
```

请求体：

```json
{
  "email": "user@example.com",
  "password": "用户输入的密码"
}
```

成功返回 HTTP `200`：

```json
{
  "access_token": "<jwt>",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "user-123",
    "email": "user@example.com",
    "role": "USER",
    "created_at": "2026-07-31T08:00:00Z"
  }
}
```

同时设置 Refresh Cookie：

```http
Set-Cookie: refresh_token=<opaque-token>; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth; Max-Age=2592000
```

- `Secure` 在生产 HTTPS 环境必须开启；仅允许本地开发环境显式关闭。
- 当前 `SameSite=Lax` 方案假设前端与 API 处于同站点部署边界。
- 使用凭据的 CORS 配置只能允许明确前端来源，不允许 `*`。
- 服务端应校验浏览器认证写操作的 `Origin`，不能仅依赖 Cookie。
- 每次成功登录创建一个独立设备会话；首版允许多设备同时登录，但不提供设备管理页面。
- 登录成功更新 `last_login_at`，但该字段不返回给其他用户。

邮箱不存在、密码错误统一返回 HTTP `401` 和 `INVALID_CREDENTIALS`，用户提示固定为“邮箱或密码错误。”，
不得通过状态码、响应时间或错误详情帮助调用方枚举注册邮箱。

## 23. API-016 刷新登录状态

```http
POST /api/v1/auth/refresh
Cookie: refresh_token=<opaque-token>
```

请求没有 JSON 请求体。成功返回 HTTP `200`：

```json
{
  "access_token": "<new-jwt>",
  "token_type": "Bearer",
  "expires_in": 900
}
```

刷新规则：

- 服务端只通过 HttpOnly Cookie 读取 Refresh Token，不接受请求体、查询参数或 Authorization Header
  传入 Refresh Token。
- 每次成功刷新都撤销旧 Refresh Token，创建同一令牌族中的新令牌并覆盖 Cookie。
- 相同旧令牌再次出现时视为可能泄露，撤销该令牌族并要求重新登录。
- 过期、撤销、伪造或缺失的 Refresh Token 都不返回新的 Access Token。
- 不延长超过后端允许的会话边界；30 天默认值可以通过安全配置调整并写入 OpenAPI。

## 24. API-017 退出当前设备

```http
POST /api/v1/auth/logout
Cookie: refresh_token=<opaque-token>
```

- 撤销当前设备的 Refresh Session。
- 通过过期的 `Set-Cookie` 清除 Refresh Cookie。
- 缺少、过期或已经撤销的会话仍清除 Cookie，重复退出保持幂等。
- 成功返回 HTTP `204`，无响应体。
- 首版只退出当前设备，不提供“退出全部设备”。
- Access JWT 不维护实时黑名单；前端必须立即丢弃它，已经泄露的 Access JWT 最多继续有效 15 分钟。

## 25. API-018 当前登录用户

```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

成功响应：

```json
{
  "id": "user-123",
  "email": "user@example.com",
  "role": "USER",
  "created_at": "2026-07-31T08:00:00Z"
}
```

- 返回当前 Access Token 对应的账户，不接受 `user_id`。
- 不返回密码哈希、Refresh Token、会话列表、画像、积分或管理员私有信息。
- 积分继续通过 API-010 查询，画像继续通过 API-012 查询。

## 26. JWT、密码与会话安全

### 26.1 Access JWT

Access JWT 至少包含：

```json
{
  "iss": "jobpicky",
  "aud": "jobpicky-api",
  "sub": "user-123",
  "jti": "token-uuid",
  "iat": 1785484800,
  "exp": 1785485700,
  "token_type": "access",
  "role": "USER"
}
```

- `sub` 是稳定用户 ID，不放邮箱、画像、积分或其他易变化数据。
- 模块化单体首版固定使用 `HS256`，签名密钥必须是至少 32 个随机字节的独立秘密；拒绝 `none` 和请求
  自行指定的其他算法。未来只有出现独立验签服务时才考虑非对称算法。
- 每次验证必须检查签名、`iss`、`aud`、`sub`、`exp` 和 `token_type`。
- JWT 签名密钥只来自安全配置；生产环境缺少密钥或密钥不满足强度要求时启动失败，不能使用代码默认值。
- 没有、过期或非法 Access Token 返回 `401`；身份有效但角色不足返回 `403`。
- `401` 响应携带符合 Bearer 认证语义的 `WWW-Authenticate` 响应头。

### 26.2 密码

- 密码长度为 15～128 个 Unicode 字符。
- 允许空格，不强制大小写、数字和特殊字符组合，也不定期强迫修改。
- 密码按用户输入原值验证，不去除首尾空白或改变大小写。
- 固定使用 Argon2id 和每个密码独立盐值，最低参数为 `m=19456 KiB, t=2, p=1`，部署时可按性能向上调整；
  不得使用 MD5、SHA-256 或可逆加密存储密码。
- 密码、密码哈希、JWT 和 Refresh Token 不得进入普通日志、错误响应、分析事件或 OpenAPI 示例真实值。

### 26.3 限流与会话

- 注册：同一来源 IP 每小时最多 5 次。
- 登录：同一规范化邮箱 15 分钟内最多 5 次失败；同一来源 IP 15 分钟内最多 30 次尝试。
- 刷新：同一会话每分钟最多 10 次，同一来源 IP 每分钟最多 60 次。
- 连续失败返回 HTTP `429`、`TOO_MANY_ATTEMPTS` 和 `Retry-After`。
- 不使用永久账户锁定，避免攻击者恶意锁住他人账户。
- 上述阈值通过后端配置提供，但开发和契约测试使用这些默认值，不由客户端传入。
- 服务端保存 Refresh Token 的安全哈希、令牌族和撤销状态，不保存原始令牌。

### 26.4 最小数据模型

`user_account` 至少保存：

```text
id
email
password_hash
role
status
created_at
updated_at
last_login_at
```

`auth_session` 至少保存：

```text
id
user_id
refresh_token_hash
token_family_id
expires_at
revoked_at
rotated_to_id
created_at
last_used_at
```

邮箱规范化值必须有数据库唯一约束。账户和会话删除、保留周期以及管理员审计策略在实现对应管理功能时
单独确认。

## 27. 登录错误响应

所有用户可见 `message` 使用中文；错误码保持稳定英文。不得在错误详情中返回密码、令牌、密码哈希或
账户内部状态。

| HTTP 状态 | 错误码 | 场景与中文信息 |
|---:|---|---|
| `401` | `INVALID_CREDENTIALS` | 邮箱不存在或密码错误：“邮箱或密码错误。” |
| `401` | `AUTHENTICATION_REQUIRED` | Access Token 缺失、非法或过期：“登录状态已失效，请重新登录。” |
| `401` | `SESSION_EXPIRED` | Refresh Session 不可用：“登录会话已过期，请重新登录。” |
| `403` | `ACCOUNT_DISABLED` | 账户被禁用：“当前账号不可用，请联系管理员。” |
| `403` | `FORBIDDEN` | 身份有效但权限不足：“你没有权限执行此操作。” |
| `409` | `EMAIL_ALREADY_REGISTERED` | 规范化邮箱已存在：“该邮箱已经注册。” |
| `422` | `VALIDATION_ERROR` | 邮箱或密码格式不合法：“请求内容不符合要求。” |
| `429` | `TOO_MANY_ATTEMPTS` | 触发限流：“操作过于频繁，请稍后重试。” |
| `500` | `INTERNAL_ERROR` | 未预期错误，不暴露内部实现或堆栈 |

## 28. 首版明确不包含

- 邮箱验证码或魔法链接登录；
- 邮箱所有权验证；
- 忘记密码和邮件重置；
- 手机号登录；
- 微信、Google、GitHub 等第三方登录；
- 多因素认证；
- 登录设备列表和会话管理页面；
- 退出全部设备；
- Access Token 实时黑名单；
- 用户自行修改邮箱或密码；
- 管理员公开注册；
- 在登录响应中返回积分、画像或推荐内容。

这些能力只有在真实页面和邮件、第三方身份等依赖准备完成后再确认接口，不提前创建占位 handler。

## 29. 登录与身份验收场景

1. 新邮箱和有效密码可以注册 `USER` 账户并立即获得 Access JWT 与 Refresh Cookie。
2. 邮箱大小写不同仍命中同一账户，不能重复注册。
3. 未知邮箱和错误密码返回完全相同的 `INVALID_CREDENTIALS` 响应。
4. 密码只以 Argon2id 等慢哈希保存，明文密码和所有令牌不出现在数据库明文字段、响应日志或错误信息中。
5. Access JWT 的签名、算法、签发方、受众、主题、类型或有效期任一不合法时，请求被拒绝。
6. Access Token 过期后可以用有效 Refresh Cookie 获得新 Access Token，且旧 Refresh Token 立即失效。
7. 被轮换的 Refresh Token 再次使用时撤销对应令牌族，不继续签发凭据。
8. 退出登录会撤销当前 Refresh Session、清除 Cookie，重复退出仍成功且不影响其他设备会话。
9. 前端不把任何认证令牌写入 `localStorage` 或 `sessionStorage`，刷新失败后回到未登录状态。
10. `USER` 不能访问管理员接口，公开注册请求不能自行指定 `ADMIN`。
11. 登录限流触发时返回 `429` 和 `Retry-After`，但不会永久锁定账户。
12. 没有有效身份的用户只能使用 API-001 公开预览、API-011 岗位详情和 API-020 筛选选项；其他用户功能
    要求登录。

## 30. API-019 收藏岗位列表

```http
GET /api/v1/user/saved-jobs
Authorization: Bearer <access_token>
```

该接口为独立“收藏岗位”页面提供数据，必须登录。

查询参数：

| 参数 | 类型 | 默认值 | 约束 |
|---|---|---:|---|
| `page` | `int` | `1` | 正整数 |
| `page_size` | `int` | `10` | `1～50` |

首版固定按 `saved_at DESC, job.id ASC` 排序，不提供搜索、筛选或其他排序参数。

成功响应：

```json
{
  "items": [
    {
      "saved_at": "2026-07-31T08:00:00Z",
      "job": {
        "id": "job-123",
        "title": "Python 后端工程师",
        "company_name": "示例科技",
        "company_nature": "民营企业",
        "locations": ["上海"],
        "source": {
          "id": "source-1",
          "name": "Moka"
        },
        "recruitment_type": "社招",
        "education_requirement": "本科",
        "graduation_years": [],
        "salary_min": 20000,
        "salary_max": 30000,
        "salary_months": 13,
        "description_preview": "负责 Python 后端服务开发……",
        "status": "OPEN",
        "published_at": "2026-07-30T08:00:00Z",
        "last_confirmed_at": "2026-07-31T08:00:00Z",
        "is_saved": true
      }
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

- 收藏列表不受 `visible_pool_limit` 限制。
- 已关闭或待确认岗位仍保留在收藏列表，通过 `job.status` 明确展示，不静默删除用户收藏。
- 列表岗位卡片不返回完整 JD；点击后通过 API-011 查询详情。
- `is_saved` 在本接口中恒为 `true`。
- 取消收藏后该记录不再出现在列表，但不影响岗位事实、推荐记录或反馈。
- 没有收藏时返回 HTTP `200` 和标准空分页。

## 31. API-020 岗位筛选选项

```http
GET /api/v1/jobs/filter-options
```

该接口允许匿名访问，不返回用户数据。它提供 API-001 所需的统一规范化选项和当前岗位池限制，避免前端
维护另一套字典。

成功响应：

```json
{
  "cities": ["北京", "上海", "杭州", "深圳", "远程"],
  "company_natures": ["央企", "国企", "事业单位", "民营企业", "外资企业"],
  "sources": [
    {"id": "source-1", "name": "Moka"},
    {"id": "source-2", "name": "飞书招聘"}
  ],
  "recruitment_types": ["校招", "社招", "实习"],
  "educations": ["高中及以下", "专科", "本科", "硕士", "博士"],
  "graduation_years": [2026, 2027, 2028],
  "limits": {
    "visible_pool_limit": 5000,
    "default_page_size": 30,
    "public_page_size_max": 30,
    "authenticated_page_size_max": 100
  }
}
```

- `cities`、`company_natures`、`sources` 和 `graduation_years` 从当前可见岗位池的已知规范化事实中去重生成，
  分别按中文显示值、来源名称和年份升序排序。
- `recruitment_types` 和 `educations` 返回首版支持的固定规范值。
- 未知值不作为筛选选项返回；用户选择任一筛选后，岗位未知字段仍按“未知保留”处理。
- 不返回每个选项的实时岗位数量，避免为首版增加昂贵的聚合查询。
- 薪资使用 API-001 的数值区间输入，不增加薪资档位字典。
- 响应可以使用 `Cache-Control: public, max-age=300` 缓存 5 分钟，不要求实时推送变化。
- 静态路由必须在 `/api/v1/jobs/{job_id}` 动态路由之前注册，避免将 `filter-options` 解释为岗位 ID。

## 32. 筛选值规范化字典

所有采集适配器、岗位写入、画像输入、API-001 查询和 API-020 选项必须共享同一规范化逻辑。

### 32.1 城市

- 国内城市使用常见中文简称，例如“北京市”规范为“北京”，“上海市”规范为“上海”。
- 多地点拆分后去重。
- 明确远程岗位规范为“远程”，不伪装成某个城市。
- “全国”保留为“全国”；无法确认时使用空数组，不使用“未知”字符串。

### 32.2 公司性质

首版规范值为：

```text
央企
国企
事业单位
政府/公共机构
民营企业
外资企业
合资企业
其他
```

常见别名如“民企”“私企”映射为“民营企业”，“国有企业”映射为“国企”。无法可靠确认时为 `null`，
不得由模型猜测公司性质。

### 32.3 招聘类型

首版规范值只有：

```text
校招
社招
实习
```

来源中的“校园招聘”“应届生招聘”映射为“校招”，“社会招聘”映射为“社招”；无法确认时为 `null`。

### 32.4 学历

首版学历顺序为：

```text
高中及以下 < 专科 < 本科 < 硕士 < 博士
```

“大专”映射为“专科”，“学士”映射为“本科”，“研究生”在能确认硕士语义时映射为“硕士”。“学历不限”
和未知要求都不形成排除条件，但内部可以保留不同的数据质量标记。

### 32.5 自由文本和来源

- 目标岗位、技能和排除岗位去除首尾空白、合并连续空白并按大小写不敏感值去重，保留首个展示文本。
- `source_id` 使用后端不透明 ID；来源显示名称只能来自来源目录，不由岗位或前端自行拼接。
- 规范化失败时遵循“未知保留”，不得为了凑齐筛选值而调用模型补写岗位事实。

## 33. 首版用户页面范围

首版实现并开放以下页面：

```text
岗位池
推荐（全部推荐、推荐任务、新建推荐）
我的求职画像
收藏岗位
岗位详情
登录与注册
```

- 设计稿中的 `Portfolio` 导航改为“我的求职画像”，使用 API-012 和 API-013。
- `Saved jobs` 使用 API-019。
- Dashboard 尚未确认真实内容，首版从导航隐藏，不创建 Dashboard API 或假统计数据。
- PDF 画像解析和 AI 对话入口继续隐藏，直到对应能力真实实现。

## 34. 开发阶段固定配置

| 配置 | 开发默认值 | 说明 |
|---|---:|---|
| `visible_pool_limit` | `5000` | API-001 可见岗位池上限 |
| 岗位池默认页大小 | `30` | 匿名和登录用户默认值 |
| 岗位池匿名页大小上限 | `30` | 匿名仍只能请求第 1 页 |
| 岗位池登录页大小上限 | `100` | 登录用户可调整 |
| 推荐聚合页大小 | 默认 `10`，最大 `50` | API-002 |
| 推荐任务页大小 | 默认 `20`，最大 `100` | API-003 |
| 单次任务结果页大小 | 默认 `10`，最大 `50` | API-006 |
| 收藏列表页大小 | 默认 `10`，最大 `50` | API-019 |
| 单次推荐候选/结果上限 | `50` | 不是累计推荐上限 |
| 新用户初始积分 | `10000` | 开发阶段注册赠送 |
| 单次推荐价格 | `100` | 开发阶段配置 |
| Access JWT 有效期 | `900` 秒 | 15 分钟 |
| Refresh Session 有效期 | `2592000` 秒 | 30 天 |
| 岗位描述预览 | `240` 字符 | 合并空白，超出时追加省略号 |

额外输入限制：

- API-001 `q` 去除首尾空白后最多 200 个字符。
- API-001 每一种多选筛选最多提交 50 个值，重复值规范化去重。
- API-004 单次 `extra_request` 最多 1000 个字符。
- `Idempotency-Key` 为 1～128 个可打印 ASCII 字符；前端首选 UUID，同一次操作的重试必须复用。
- 所有金额、页大小、时间和长度限制必须进入 Pydantic Schema 和生成的 OpenAPI，不能只存在于前端。

这些值允许通过后端配置调整，但调整后的真实限制必须由 API 响应或 OpenAPI 表达；生产积分、余额上限和
岗位池规模在上线前根据运营与容量重新确认。

## 35. 与现有仓库冲突及待修改项

本表是迁移清单。以下位置与本文已确认契约冲突时，以本文为准；本轮只记录待修改项，不保留两套并行语义。

| 位置 | 当前冲突 | 必须修改为 | 状态 |
|---|---|---|---|
| `docs/requirements.md` | 仍以简历文本/文件创建画像，且把具体前端 UI 放在 Later | 手工画像表单、登录、岗位池、推荐和收藏页面成为当前首版范围 | 待修改 |
| `docs/architecture.md` §4.6、§5.3、§6 | 画像仍是 `POST + PATCH`，推荐请求仍由前端传 `profile_id`，没有认证、收藏列表和筛选选项契约 | 同步 API-001～020、最新 DTO、自动使用当前画像和可选/必需身份边界 | 待修改 |
| `src/jobpicky/contracts/profiles.py` | 缺少 `recruitment_types`，并把 `warnings` 放在用户可写 `ProfileDraft` | 拆分用户输入与只读快照；增加招聘类型、字段上限和版本并发输入 | 待修改 |
| `src/jobpicky/contracts/catalog.py` | `JobQuery` 只有少量字段，`JobFact` 不能直接表达列表来源对象和收藏状态 | 增加完整岗位查询 DTO，并新增 `JobListItem`、`JobDetailView`、筛选选项视图 | 待修改 |
| `src/jobpicky/contracts/matching.py` | `RecommendationItem` 暴露内部 `retrieval`，缺少推荐 ID、时间、收藏、反馈和软删除状态 | 保留内部评估 DTO，另外新增前端 `RecommendationCardView` 和任务结果视图 | 待修改 |
| `src/jobpicky/contracts/common.py` | `ErrorCode`、`RunView` 和进度字段不足以覆盖新契约，部分默认消息仍为英文 | 增加已确认错误码、积分/进度视图和中文用户消息；保留英文机器码 | 待修改 |
| `src/jobpicky/ports.py` | 没有认证、积分、收藏、推荐反馈/删除、筛选选项端口；画像端口仍按简历文本创建 | 按模块所有权新增最小应用端口并修改画像保存契约 | 待修改 |
| `src/jobpicky/matching/service.py` | `recruitment_types` 被固定为空 | 从最新画像快照生成招聘类型硬筛选 | 待修改 |
| `src/jobpicky/infrastructure/profile_store.py` | 表映射缺少招聘类型，写入应用服务未实现 | 支持单一画像 ID、多版本保存、并发控制和最新版本读取 | 待修改 |
| `src/jobpicky/orchestration/store.py` 与推荐存储 | 结果主要保存在运行 JSON 中，没有独立推荐交互状态 | 增加正式推荐记录、用户去重、反馈、软删除和历史结果查询 | 待修改 |
| `alembic/versions/` | 没有用户、会话、积分、收藏和正式推荐表；画像表缺少招聘类型 | 新增迁移，不修改已经发布的历史迁移文件 | 待修改 |
| `src/jobpicky/config.py`、`.env.example` | 没有岗位池、积分、JWT、Cookie、CORS、限流和页面上限配置 | 增加 §26、§34 的配置并对生产秘密做启动校验 | 待修改 |
| `pyproject.toml` | 没有 JWT、邮箱校验和 Argon2id 密码哈希依赖 | 实现鉴权时选择维护中的最小依赖并锁定兼容范围 | 待修改 |
| `src/jobpicky/app.py` | 当前只有健康检查路由，验证错误和内部错误的用户消息仍为英文 | 注册真实 API router、可选/必需身份依赖和统一中文错误映射 | 待修改 |
| `tests/` 与当前 OpenAPI | 只覆盖已有底座，未验证本文契约 | 为 API-001～020 增加契约、权限、幂等、并发、退款和安全测试并生成 OpenAPI | 待修改 |

同步过程中不得删除仍被采集、匹配等内部流程使用的 DTO；应将内部 DTO 与面向前端的 API View 分开，避免
为了页面响应破坏既有模块边界。

## 36. 开发与联调准入

- 前后端现在可以依据本文开始开发，本文已确认条目是目标行为。
- 后端第一步必须完成 §35 的公共契约同步，再实现业务 handler；不能让旧 `architecture.md` 覆盖新需求。
- 前端可以先按本文 DTO 使用 Mock 开发，但正式联调必须以同步后的 FastAPI OpenAPI 为准。
- API-001～020 的 Pydantic Schema、OpenAPI 和关键契约测试一致后，才视为接口冻结完成。
- 未来能力和明确排除项不属于当前交付，不创建空路由、假数据或无业务实现的占位类。
