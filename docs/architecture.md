# JobPicky 架构与公共契约

> 状态：MVP 架构基线
> 需求范围和验收结果以 `requirements.md` 为准。
> 本文只固定跨模块协作所需的边界、数据语义和公开接口；模块内部实现保持弹性。

## 0. 如何使用本文

本文中的内容分为三类：

- **公共契约**：跨模块 DTO、服务端口、HTTP 路径及响应语义。实现后不得静默改变。
- **架构不变量**：无论采用何种框架和存储方案都必须成立的安全与一致性规则。
- **参考实现**：帮助首版快速落地的默认选择，可以在保持契约和需求不变的前提下替换。

没有标为公共契约或架构不变量的目录、类、函数、表、索引、算法和第三方库都不是硬性要求。示例代码用于说明接口语义，不要求照抄文件组织。

## 1. 总体架构

首版的参考落地方式是模块化单体：一个后端部署单元、一个主业务数据库，长任务由同进程后台执行器或独立 Worker 运行。这不是客户端契约；如果现有仓库或部署条件已有更简单的合适方案，可以调整物理结构，但下述逻辑所有权和公共契约保持不变。

### 1.1 逻辑模块

| 模块 | 负责 | 不负责 |
|---|---|---|
| 招聘源与采集 `collection` | 来源识别、平台采集、未知来源探索、原始字段标准化 | 决定系统岗位 ID、关闭岗位、执行推荐 |
| 岗位目录 `catalog` | 岗位事实、身份去重、生命周期，并执行结构化、全文与向量查询 | 调用招聘网站、决定召回策略、生成模型推荐理由 |
| 用户画像 `profiles` | 简历文本提取、画像解析、校验、版本 | 搜索岗位、改变岗位事实 |
| 匹配 `matching` | 生成硬筛选与检索条件、融合候选、模型评估 | 保存或编造岗位事实、控制采集 |
| 编排 `orchestration` | 创建运行、按顺序调用能力、记录进度、失败与恢复 | 承载采集、SQL、检索或模型算法 |
| 接口 `api` | 鉴权上下文、输入校验、DTO 转换、HTTP 语义 | 业务算法和直接数据库访问 |
| 基础设施 `infrastructure` | 数据库、HTTP、浏览器、模型、任务执行器的具体接入 | 定义产品规则 |

模块名称是语义边界，不强制对应同名目录。小型实现可以合并相邻模块的文件，但不得混淆数据所有权。

### 1.2 岗位采集链路

```text
招聘源
→ 选择采集能力
→ 获取并标准化 CollectedJob
→ 形成带完整性声明的 CollectionBatch
→ 岗位目录校验、去重和写入
→ 仅在安全条件成立时更新关闭状态
→ 保存 CrawlRun
```

### 1.3 推荐链路

```text
画像快照
→ 确定性硬筛选
→ 关键词与语义召回
→ 读取 JobFact
→ 结构化匹配评估
→ 重新用 JobFact 组装 RecommendationItem
→ 保存 RecommendationRun 和结果
```

编排层可以使用状态图，也可以使用更轻量的显式流程。客户端只依赖运行状态，不依赖内部节点、类名或框架。

## 2. 架构不变量

以下规则必须由代码和测试共同保护。

### A1. 岗位目录拥有岗位事实

采集模块只能提交观察到的岗位，不得指定系统岗位 ID、内容哈希、最终岗位状态或关闭其他岗位。匹配和模型模块只能通过岗位目录读取事实。

### A2. 完整性先于关闭

`CollectionBatch.complete = true` 只是采集器的完整性声明。岗位目录仍需通过分页、错误比例、字段完整性和异常数量保护检查；只有两侧都确认安全，才允许关闭本次未出现的岗位。

### A3. 事实与判断分离

模型评估只输出 `job_id`、是否匹配、分数、理由、匹配项和缺口。保存结果前重新读取 `JobFact`，并保留当时的事实版本或快照；最终推荐中的公司、标题、地点、JD 和链接不从模型输出中获取。

### A4. 硬筛选不可旁路

编排层不得直接将未经过硬筛选的岗位交给最终评估。硬筛选规则必须在相同数据和配置下可复现，并能给出排除原因。

### A5. 运行记录是业务事实

采集运行、推荐运行和正式结果保存在业务存储中。框架 Checkpoint、任务队列状态和日志可以辅助恢复，但不能成为唯一事实来源。

### A6. 版本和幂等

推荐绑定不可变的画像版本。写入接口必须能抵御任务重试和客户端重复提交；同一来源岗位与同一运行结果不能因重试重复创建。

### A7. 依赖方向清晰

- 采集通过岗位目录写入端口提交数据。
- 匹配通过岗位目录查询端口读取数据。
- 编排只调用公开业务端口。
- API 只调用应用服务。
- 业务模块不导入其他模块的私有 Repository、ORM 模型或第三方 SDK 实现。
- 基础设施实现业务端口，业务规则不反向依赖具体厂商。

### A8. 隐私与权限上下文不丢失

所有用户侧画像、推荐和个人岗位操作都携带用户上下文；所有管理操作都携带管理员上下文。即使首版使用本地身份适配器，也不能让应用服务默认调用者拥有全局权限。

## 3. 公共类型约定

以下约定适用于跨模块 DTO 和 `/api/v1` JSON。

| 项目 | 约定 |
|---|---|
| 字段命名 | `snake_case` |
| 标识符 | 对外为非空字符串并视为不透明值；首版可使用 UUID |
| 时间 | 带时区时间，JSON 使用 RFC 3339；内部建议统一 UTC |
| 缺失值 | 使用 `null` 或省略可选字段，不用空字符串伪装缺失 |
| 列表 | 使用 JSON 数组；空列表与未知值语义不同 |
| 岗位匹配分 | `match_score` 为 `0` 到 `100` 的整数 |
| 检索分 | `retrieval_score` 及子分数为 `0.0` 到 `1.0`；进入公共 DTO 前完成归一化 |
| 扩展数据 | 放入明确命名的 `metadata`，不得借此绕开核心字段 |

公共枚举值使用大写字符串：

```text
JobStatus:
OPEN | CLOSED | UNKNOWN

RunStatus:
PENDING | RUNNING | SUCCEEDED | PARTIAL | FAILED | CANCELLED

RecommendationStep:
PENDING | PROFILE | FILTER | RETRIEVE | EVALUATE | SAVE | COMPLETE
```

新增枚举值应保持旧客户端能够安全处理未知值；删除、改名或改变语义属于不兼容契约变更。

## 4. 核心公共数据契约

表格中的“必须”是跨模块或对外传输时的要求，不代表每张数据库表必须逐字段照搬。

### 4.1 `SourceInput`

创建招聘源的最小输入。

| 字段 | 类型 | 必须 | 语义 |
|---|---|---:|---|
| `company_name` | `str` | 是 | 公司显示名称 |
| `source_url` | `str` | 是 | 公开的官方招聘入口 |
| `enabled` | `bool` | 否 | 默认 `true` |
| `platform_hint` | `str \| null` | 否 | 人工提示，不覆盖实际检测结果 |
| `metadata` | `object` | 否 | 非敏感的来源扩展信息 |

读取契约 `SourceView` 在此基础上增加：

| 字段 | 类型 |
|---|---|
| `id` | `str` |
| `platform` | `str \| null` |
| `resolved_url` | `str \| null` |
| `created_at` | `datetime` |
| `updated_at` | `datetime` |

秘密凭据不得进入 `SourceInput` 或 `SourceView`。

### 4.2 `CollectedJob`

采集模块向岗位目录提交的唯一岗位事实输入。

| 字段 | 类型 | 必须 | 语义 |
|---|---|---:|---|
| `source_id` | `str` | 是 | 招聘源 |
| `source_job_id` | `str \| null` | 否 | 来源系统的稳定岗位 ID |
| `company_name` | `str` | 是 | 来源展示的公司名称 |
| `company_nature` | `str \| null` | 否 | 企业性质（民企、央国企、事业单位等）；无法确认时为空 |
| `title` | `str` | 是 | 岗位名称 |
| `locations` | `list[str]` | 是 | 可为空但不能伪造 |
| `description` | `str \| null` | 否 | 完整 JD 或已知正文 |
| `detail_url` | `str \| null` | 否 | 岗位详情页 |
| `apply_url` | `str \| null` | 否 | 直接投递入口；与详情页不同时必须保留 |
| `recruitment_type` | `str \| null` | 否 | 校招、社招、实习等标准化值 |
| `education_requirement` | `str \| null` | 否 | 无法确认时为空或未知 |
| `salary_min` | `int \| null` | 否 | 月薪下限（元）；无法确认时为空 |
| `salary_max` | `int \| null` | 否 | 月薪上限（元）；无法确认时为空 |
| `salary_months` | `int \| null` | 否 | 年发薪月数；无法确认时为空 |
| `graduation_years` | `list[int]` | 否 | 岗位限定的届次（校招）；空列表表示未标明或不限 |
| `published_at` | `datetime \| null` | 否 | 来源发布时间 |
| `deadline_at` | `datetime \| null` | 否 | 投递截止时间 |
| `source_ref` | `str \| null` | 否 | 可定位原始快照或响应的内部引用 |
| `metadata` | `object` | 否 | 平台特有且不作为核心事实的字段 |

`CollectedJob` 不得包含系统 `job_id`、`status`、`dedupe_key`、`content_hash`、Embedding 或“关闭”指令。

### 4.3 `CollectionBatch`

一次来源采集的跨模块输出。

| 字段 | 类型 | 必须 | 语义 |
|---|---|---:|---|
| `source_id` | `str` | 是 | 本批次来源 |
| `items` | `list[CollectedJob]` | 是 | 本次成功标准化的岗位 |
| `complete` | `bool` | 是 | 采集器是否确认覆盖了该来源当前全部岗位 |
| `method` | `str` | 是 | 使用的适配器、通用 API、HTML 或探索方式 |
| `warnings` | `list[str]` | 是 | 非致命异常和完整性风险 |
| `metrics` | `object` | 否 | 页数、请求数、字段完整率等可观测数据 |
| `config_candidate` | `object \| null` | 否 | 未知网站探索得到但尚待验证的配置 |

`items=[]` 不自动代表完整空岗位。只有来源明确返回空集合、分页语义得到验证且无异常时，`complete` 才能为 `true`。

### 4.4 `IngestionResult`

岗位目录处理一个批次后的结果。

| 字段 | 类型 |
|---|---|
| `job_ids` | `list[str]` |
| `created_count` | `int` |
| `updated_count` | `int` |
| `unchanged_count` | `int` |
| `closed_count` | `int` |
| `close_skipped` | `bool` |
| `complete_accepted` | `bool` |
| `warnings` | `list[str]` |

当 `complete_accepted=false` 时，`closed_count` 必须为 `0`。

### 4.5 `JobFact`

岗位目录对其他模块和客户端提供的事实视图。

| 字段 | 类型 | 必须 |
|---|---|---:|
| `id` | `str` | 是 |
| `source_id` | `str` | 是 |
| `company_name` | `str` | 是 |
| `company_nature` | `str \| null` | 否 |
| `title` | `str` | 是 |
| `locations` | `list[str]` | 是 |
| `description` | `str \| null` | 否 |
| `detail_url` | `str \| null` | 否 |
| `apply_url` | `str \| null` | 否 |
| `recruitment_type` | `str \| null` | 否 |
| `education_requirement` | `str \| null` | 否 |
| `salary_min` | `int \| null` | 否 |
| `salary_max` | `int \| null` | 否 |
| `salary_months` | `int \| null` | 否 |
| `graduation_years` | `list[int]` | 否 |
| `status` | `JobStatus` | 是 |
| `fact_version` | `str` | 是 |
| `published_at` | `datetime \| null` | 否 |
| `deadline_at` | `datetime \| null` | 否 |
| `first_seen_at` | `datetime` | 是 |
| `last_confirmed_at` | `datetime` | 是 |
| `updated_at` | `datetime` | 是 |

普通用户接口不得返回内部去重键、内容哈希、Embedding、原始响应和秘密采集参数。

### 4.6 `ProfileDraft` 与 `ProfileSnapshot`

模型或规则解析得到 `ProfileDraft`，校验并保存后成为不可变的 `ProfileSnapshot`。

| 字段 | 类型 | 必须 | 语义 |
|---|---|---:|---|
| `target_locations` | `list[str]` | 是 | 目标地点 |
| `target_roles` | `list[str]` | 是 | 目标岗位方向 |
| `skills` | `list[str]` | 是 | 有输入依据的技能 |
| `excluded_roles` | `list[str]` | 是 | 明确不考虑的岗位 |
| `education` | `str \| null` | 否 | 无法确认时为空 |
| `graduation_year` | `int \| null` | 否 | 求职者届次（如 2027）；非校招场景可为空 |
| `expected_salary_min` | `int \| null` | 否 | 期望月薪下限（元）；无法确认时为空 |
| `experience_summary` | `str \| null` | 否 | 与匹配有关的经历摘要 |
| `extra_request` | `str \| null` | 否 | 用户补充要求 |
| `warnings` | `list[str]` | 是 | 冲突、缺失和低置信信息 |

`ProfileSnapshot` 在此基础上增加：

| 字段 | 类型 |
|---|---|
| `id` | `str` |
| `user_id` | `str` |
| `version` | `int`，从 1 递增 |
| `created_at` | `datetime` |

原始简历引用属于受保护字段，不默认进入普通画像响应。

### 4.7 `HardFilterSpec` 与 `FilterResult`

匹配模块将画像和本次请求转换为 `HardFilterSpec`，岗位目录只执行该确定性条件：

| 字段 | 类型 | 默认语义 |
|---|---|---|
| `target_locations` | `list[str]` | 空列表表示不限 |
| `excluded_roles` | `list[str]` | 空列表表示无明确排除 |
| `education` | `str \| null` | 空值表示不执行学历排除 |
| `recruitment_types` | `list[str]` | 空列表表示不限 |
| `graduation_year` | `int \| null` | 空值表示不执行届次排除；岗位未标明届次时不得排除 |
| `min_salary` | `int \| null` | 空值表示不执行薪资排除；仅当岗位 `salary_max` 已知且低于该值时排除 |
| `only_open` | `bool` | `true` |

筛选值必须使用画像与岗位目录共享的规范化语义；来源原始文本不能直接作为跨模块筛选值。

| 字段 | 类型 |
|---|---|
| `eligible_job_ids` | `list[str]` |
| `excluded` | `list[FilterExclusion]` |

`FilterExclusion` 包含 `job_id`、稳定的 `reason_code` 和可读 `reason`。首版至少支持以下原因语义：

```text
JOB_NOT_OPEN
LOCATION_MISMATCH
RECRUITMENT_TYPE_MISMATCH
EDUCATION_MISMATCH
EXCLUDED_ROLE
GRADUATION_YEAR_MISMATCH
SALARY_MISMATCH
```

缺失信息只有在业务规则明确允许时才能成为排除原因。

### 4.8 `SearchHit` 与 `Candidate`

岗位目录的单路检索结果为 `SearchHit`：

| 字段 | 类型 |
|---|---|
| `job_id` | `str` |
| `score` | `float`，范围 `0.0` 到 `1.0` |
| `channel` | `"keyword" \| "semantic"` |

匹配模块合并多个 `SearchHit` 后形成 `Candidate`：

| 字段 | 类型 | 必须 |
|---|---|---:|
| `job_id` | `str` | 是 |
| `retrieval_score` | `float` | 是 |
| `keyword_score` | `float \| null` | 否 |
| `semantic_score` | `float \| null` | 否 |
| `sources` | `list[str]` | 是 |

融合算法不属于公共契约，但同一数据、配置和输入下应可复现。阈值、上限和权重由版本化配置管理。

### 4.9 `MatchAssessment`

| 字段 | 类型 | 必须 |
|---|---|---:|
| `job_id` | `str` | 是 |
| `matched` | `bool` | 是 |
| `match_score` | `int` | 是 |
| `reason` | `str` | 是 |
| `matched_strengths` | `list[str]` | 是 |
| `gaps` | `list[str]` | 是 |
| `evidence` | `list[str]` | 否 |

`job_id` 必须来自输入候选且每批最多出现一次。评估中不得包含可覆盖 `JobFact` 的岗位字段。

### 4.10 `RecommendationItem`

最终结果使用组合结构，显式区分事实、召回和判断。以下是省略部分字段的结构示例：

```json
{
  "job": {"id": "job-id", "company_name": "某公司", "title": "软件工程师"},
  "retrieval": {"job_id": "job-id", "retrieval_score": 0.82, "sources": ["keyword", "semantic"]},
  "assessment": {"job_id": "job-id", "matched": true, "match_score": 88, "reason": "…", "matched_strengths": [], "gaps": []}
}
```

完整字段分别遵循 `JobFact`、`Candidate` 和 `MatchAssessment`。三个 `job_id` 必须一致；普通结果列表只包含 `matched=true` 的项。`job` 是保存推荐结果前从岗位目录读取并与结果一同保存的事实快照，其 `fact_version` 用于追溯；当前岗位状态可另通过岗位详情接口查询。

`RecommendationCandidate` 只作为召回到评估之间的内部中间契约；推荐运行持久化和用户结果接口使用
`RecommendationItem`，并要求 `assessment.matched=true`。

### 4.11 运行与通用响应

`RunAccepted`：

| 字段 | 类型 |
|---|---|
| `run_id` | `str` |
| `status` | `RunStatus`，创建时通常为 `PENDING` |

`RunView`：

| 字段 | 类型 |
|---|---|
| `run_id` | `str` |
| `kind` | `"CRAWL" \| "RECOMMENDATION"` |
| `status` | `RunStatus` |
| `created_at` | `datetime` |
| `current_step` | `str \| null` |
| `started_at` | `datetime \| null` |
| `finished_at` | `datetime \| null` |
| `counts` | `object` |
| `warnings` | `list[str]` |
| `recommendation_input` | `RecommendationRunInput \| null` |
| `model_config_version` | `str \| null` |
| `error` | `RunError \| null` |

`created_at` 是所有运行的创建时间。推荐运行必须填充 `recommendation_input` 和
`model_config_version`；其中 `recommendation_input.profile_version` 是本次使用的不可变画像版本，
`effective_extra_request` 是持久化的最终输入，而不是查询时重新从当前画像推导的值。

分页响应：

```json
{"items": [], "total": 0, "page": 1, "page_size": 20}
```

错误响应：

```json
{
  "code": "STABLE_MACHINE_READABLE_CODE",
  "message": "面向调用者的简洁说明",
  "details": {},
  "request_id": "request-id",
  "run_id": null
}
```

单资源成功响应直接返回资源，不增加无业务意义的 `data` 包装。

首版保留以下稳定错误语义：

```text
VALIDATION_ERROR
NOT_FOUND
FORBIDDEN
CONFLICT
DEPENDENCY_UNAVAILABLE
CRAWL_UNSUPPORTED
CRAWL_INCOMPLETE
PROFILE_PARSE_FAILED
RECOMMENDATION_FAILED
INTERNAL_ERROR
```

`ErrorBody` 仅用于 HTTP 响应，必须带当前请求的 `request_id`，可选关联 `run_id`。
后台运行持久化使用不含 `request_id` 的 `RunError`；运行历史不能因为查询请求不同而改变其错误内容。

### 4.12 推荐请求输入合并

画像快照中的 `extra_request` 是长期偏好，单次推荐请求中的 `extra_request` 是本次覆盖范围内的补充。
两者都存在时按“画像要求、空行、单次要求”的顺序拼接；只存在一方时使用该方；两者为空或仅空白时为
`null`。该合并在创建运行时完成，结果写入 `RecommendationRunInput.effective_extra_request`，后续恢复、
重试和查询均使用已保存值，不读取当前画像重新计算。

模块可以增加更具体的错误码，但同一错误码不得表达不同语义，外部依赖原始错误和堆栈不得直接成为公开 `message`。

## 5. 跨模块服务端口

端口名称和方法语义是公共契约。具体同步/异步语法、依赖注入方式和 import 路径可按语言与框架习惯落地，但改变输入、输出或所有权前必须同步更新本文和契约测试。

### 5.1 采集端口

```python
class SourceCollectorPort(Protocol):
    async def collect(
        self,
        source: SourceView,
        *,
        config: Mapping[str, object] | None = None,
    ) -> CollectionBatch: ...
```

- 一个实现可以对应一个 ATS、一类通用 API 或 HTML 策略。
- 平台检测、列表/详情拆分、分页和浏览器使用方式属于采集模块内部设计。
- 端口返回批次，不直接写数据库。

未知来源探索在 P1 可作为单独 `DiscoveryPort`，也可作为采集模块内部能力；只要未验证配置不会直接启用，就不要求提前抽象。

### 5.2 岗位目录端口

```python
class JobCatalogPort(Protocol):
    async def ingest(
        self,
        run_id: str,
        batch: CollectionBatch,
    ) -> IngestionResult: ...

    async def get_jobs(
        self,
        job_ids: Sequence[str],
    ) -> list[JobFact]: ...

    async def hard_filter(
        self,
        spec: HardFilterSpec,
    ) -> FilterResult: ...

    async def keyword_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]: ...

    async def semantic_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]: ...
```

匹配模块负责从画像生成 `HardFilterSpec` 和检索文本，并将两路 `SearchHit` 融合为 `Candidate`。列表管理查询可以通过同一应用服务扩展，但不得让采集或匹配模块绕过此端口直接操作岗位表。

### 5.3 画像端口

```python
class ProfileParserPort(Protocol):
    async def parse(
        self,
        resume_text: str,
        extra_request: str | None,
    ) -> ProfileDraft: ...
```

保存、读取和创建新版本由画像模块的应用服务负责。文件解析器只输出文本，不与模型画像契约耦合。

```python
class ProfileSnapshotReaderPort(Protocol):
    async def get_snapshot(self, user_id: str, profile_id: str) -> ProfileSnapshot: ...
```

推荐编排器只能通过该只读端口读取画像快照；画像私有 Repository 或 ORM 不得出现在编排模块。

画像 P0 应用服务最小契约为：按用户创建版本、读取当前版本、基于用户和画像 ID 修正并创建新版本。

```python
class ProfileApplicationPort(Protocol):
    async def create_profile(
        self,
        user_id: str,
        *,
        resume_text: str,
        extra_request: str | None = None,
    ) -> ProfileSnapshot: ...

    async def get_current(self, user_id: str) -> ProfileSnapshot: ...

    async def update_profile(
        self,
        user_id: str,
        profile_id: str,
        draft: ProfileDraft,
    ) -> ProfileSnapshot: ...
```

```python
class SourceApplicationPort(Protocol):
    async def create_source(self, admin_id: str, source: SourceInput) -> SourceView: ...
    async def list_sources(self, admin_id: str, page: int, page_size: int) -> Page[SourceView]: ...
    async def get_source(self, admin_id: str, source_id: str) -> SourceView: ...
    async def update_source(
        self,
        admin_id: str,
        source_id: str,
        patch: SourcePatch,
    ) -> SourceView: ...
```

### 5.4 匹配评估端口

匹配模块拥有画像到硬筛选条件、检索文本和候选融合的转换；编排器只调用匹配端口，再把结果交给目录端口。

```python
class MatchingPort(Protocol):
    def build_filter_spec(
        self,
        profile: ProfileSnapshot,
        effective_extra_request: str | None,
    ) -> HardFilterSpec: ...

    def build_query_text(
        self,
        profile: ProfileSnapshot,
        effective_extra_request: str | None,
    ) -> str: ...

    def merge_candidates(
        self,
        keyword_hits: Sequence[SearchHit],
        semantic_hits: Sequence[SearchHit],
    ) -> list[Candidate]: ...
```

```python
class JobEvaluatorPort(Protocol):
    async def evaluate(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        effective_extra_request: str | None = None,
    ) -> list[MatchAssessment]: ...
```

实现可以分批、并发或使用不同模型。它必须验证输入输出关联、限制重试，并拒绝未知或重复 `job_id`。

### 5.5 采集编排端口

```python
class CrawlOrchestratorPort(Protocol):
    async def start(
        self,
        admin_id: str,
        source_ids: Sequence[str],
        idempotency_key: str | None = None,
    ) -> RunAccepted: ...

    async def list_runs(
        self,
        admin_id: str,
        page: int,
        page_size: int,
    ) -> Page[RunView]: ...

    async def get_run(
        self,
        admin_id: str,
        run_id: str,
    ) -> RunView: ...
```

该端口创建运行、选择采集能力并把 `CollectionBatch` 交给岗位目录。它不在自身实现平台解析或岗位去重。

### 5.6 推荐编排端口

```python
class RecommendationOrchestratorPort(Protocol):
    async def start(
        self,
        user_id: str,
        profile_id: str,
        extra_request: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunAccepted: ...

    async def list_runs(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> Page[RunView]: ...

    async def get_run(
        self,
        user_id: str,
        run_id: str,
    ) -> RunView: ...

    async def get_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationItem]: ...
```

`get_results` 返回评估后的最终推荐 `RecommendationItem`（见 §4.10）。其中岗位事实是保存前重新读取的
`JobFact` 快照，结果列表不包含 `matched=false` 的评估项目。

具体图节点和执行器不是端口的一部分。模型工具只包装上述业务端口，不应形成另一套平行业务接口。

管理员推荐历史不复用用户侧 `get_run(user_id, run_id)`，而使用独立的管理员查询端口：

```python
class AdminRecommendationRunQueryPort(Protocol):
    async def list_runs(self, admin_id: str, page: int, page_size: int) -> Page[RunView]: ...
    async def get_run(self, admin_id: str, run_id: str) -> RunView: ...
```

来源管理、用户岗位详情和管理端岗位查询也由应用服务端口承接：`SourceApplicationPort`、
`UserJobQueryPort` 和 `AdminJobQueryPort`。它们分别携带 `admin_id` 或 `user_id`，禁止通过调用者自带的
资源 ID 推断权限。

```python
class UserJobQueryPort(Protocol):
    async def get_job(self, user_id: str, job_id: str) -> JobFact: ...


class AdminJobQueryPort(Protocol):
    async def list_jobs(
        self,
        admin_id: str,
        query: JobQuery,
        page: int,
        page_size: int,
    ) -> Page[JobFact]: ...

    async def get_job(self, admin_id: str, job_id: str) -> JobFact: ...
```

## 6. HTTP API 公共契约

### 6.1 通用规则

- 版本前缀固定为 `/api/v1`。
- 用户接口位于 `/api/v1/user`，管理接口位于 `/api/v1/admin`，系统接口位于 `/api/v1/system`。
- JSON 为默认格式；文件上传使用 `multipart/form-data`。
- 长任务创建成功返回 `202 Accepted` 和 `RunAccepted`。
- 列表使用统一分页，页大小上限由服务配置并写入 OpenAPI。
- 错误使用统一错误响应；内部堆栈不得对外返回。
- OpenAPI 是可执行接口清单，必须通过契约测试与本文语义保持一致。

### 6.1.1 P0 HTTP API 覆盖表

以下表是 P0 HTTP → 应用服务/端口 → DTO → 权限上下文的唯一覆盖清单。当前阶段只固化契约，未实现的
业务 handler 不创建占位接口。

| HTTP API | 应用服务/端口 | 输入/输出 DTO | 权限上下文 |
|---|---|---|---|
| `POST /api/v1/user/profiles` | `ProfileApplicationPort.create_profile` | `resume_text`/文件转文本 → `ProfileSnapshot` | `user_id` |
| `GET /api/v1/user/profiles/current` | `ProfileApplicationPort.get_current` | `ProfileSnapshot` | `user_id` |
| `PATCH /api/v1/user/profiles/{profile_id}` | `ProfileApplicationPort.update_profile` | `ProfileDraft` → `ProfileSnapshot` | `user_id` + `profile_id` |
| `POST /api/v1/user/recommendation-runs` | `RecommendationOrchestratorPort.start` | `profile_id` + `extra_request` → `RunAccepted` | `user_id` |
| `GET /api/v1/user/recommendation-runs` | `RecommendationOrchestratorPort.list_runs` | `Page[RunView]` | `user_id` |
| `GET /api/v1/user/recommendation-runs/{run_id}` | `RecommendationOrchestratorPort.get_run` | `RunView` | `user_id` |
| `GET /api/v1/user/recommendation-runs/{run_id}/results` | `RecommendationOrchestratorPort.get_results` | `Page[RecommendationItem]` | `user_id` |
| `GET /api/v1/user/jobs/{job_id}` | `UserJobQueryPort.get_job` | `JobFact` | `user_id` |
| `POST /api/v1/admin/sources` | `SourceApplicationPort.create_source` | `SourceInput` → `SourceView` | `admin_id` |
| `GET /api/v1/admin/sources` | `SourceApplicationPort.list_sources` | `Page[SourceView]` | `admin_id` |
| `GET /api/v1/admin/sources/{source_id}` | `SourceApplicationPort.get_source` | `SourceView` | `admin_id` |
| `PATCH /api/v1/admin/sources/{source_id}` | `SourceApplicationPort.update_source` | `SourcePatch` → `SourceView` | `admin_id` + `source_id` |
| `POST /api/v1/admin/crawl-runs` | `CrawlOrchestratorPort.start` | `source_ids` → `RunAccepted` | `admin_id` |
| `GET /api/v1/admin/crawl-runs` | `CrawlOrchestratorPort.list_runs` | `Page[RunView]` | `admin_id` |
| `GET /api/v1/admin/crawl-runs/{run_id}` | `CrawlOrchestratorPort.get_run` | `RunView` | `admin_id` |
| `GET /api/v1/admin/jobs` | `AdminJobQueryPort.list_jobs` | `JobQuery` → `Page[JobFact]` | `admin_id` |
| `GET /api/v1/admin/jobs/{job_id}` | `AdminJobQueryPort.get_job` | `JobFact` | `admin_id` |
| `GET /api/v1/admin/recommendation-runs` | `AdminRecommendationRunQueryPort.list_runs` | `Page[RunView]` | `admin_id` |
| `GET /api/v1/admin/recommendation-runs/{run_id}` | `AdminRecommendationRunQueryPort.get_run` | `RunView` | `admin_id` |
| `GET /api/v1/system/health` | 应用健康检查 | `HealthView` | 无业务身份 |

### 6.2 P0 用户接口

| 方法 | 路径 | 语义 |
|---|---|---|
| `POST` | `/api/v1/user/profiles` | 从简历文本或文件创建画像版本 |
| `GET` | `/api/v1/user/profiles/current` | 查询当前画像 |
| `PATCH` | `/api/v1/user/profiles/{profile_id}` | 修正画像并创建新版本 |
| `POST` | `/api/v1/user/recommendation-runs` | 发起推荐 |
| `GET` | `/api/v1/user/recommendation-runs` | 查询自己的推荐历史 |
| `GET` | `/api/v1/user/recommendation-runs/{run_id}` | 查询运行状态 |
| `GET` | `/api/v1/user/recommendation-runs/{run_id}/results` | 查询推荐结果 |
| `GET` | `/api/v1/user/jobs/{job_id}` | 查询可公开的岗位事实 |

创建画像时必须提供 `resume_text` 或 `resume_file` 中至少一个。允许实现为同一路径的不同 Content-Type，或由 API 层汇入同一应用服务；对外支持方式必须在 OpenAPI 中明确。

画像修改只接受 `ProfileDraft` 中允许用户修正的字段，并创建新版本，不原地改变历史推荐引用的快照。

发起推荐的最小输入是 `profile_id`，可附带本次 `extra_request`。客户端可通过 `Idempotency-Key` 请求头安全重试创建请求；服务端是否同时接受请求体中的幂等键由 OpenAPI 明确。

### 6.3 P0 管理接口

| 方法 | 路径 | 语义 |
|---|---|---|
| `POST` | `/api/v1/admin/sources` | 创建招聘源 |
| `GET` | `/api/v1/admin/sources` | 查询招聘源 |
| `GET` | `/api/v1/admin/sources/{source_id}` | 查询来源详情与最近状态 |
| `PATCH` | `/api/v1/admin/sources/{source_id}` | 修改或停用来源 |
| `POST` | `/api/v1/admin/crawl-runs` | 为一个或多个来源发起采集 |
| `GET` | `/api/v1/admin/crawl-runs` | 查询采集历史 |
| `GET` | `/api/v1/admin/crawl-runs/{run_id}` | 查询采集状态、计数和错误 |
| `GET` | `/api/v1/admin/jobs` | 查询和筛选岗位 |
| `GET` | `/api/v1/admin/jobs/{job_id}` | 查询岗位质量与来源信息 |
| `GET` | `/api/v1/admin/recommendation-runs` | 查询推荐运行摘要 |
| `GET` | `/api/v1/admin/recommendation-runs/{run_id}` | 查询推荐运行阶段和错误 |

发起采集的最小输入是非空 `source_ids` 数组。强制重新探索属于 P1，在该能力实现前不把相应参数标记为可用。

招聘源修改接受 `SourceInput` 的可变字段子集；修改入口地址后必须重新识别来源，不能继续静默沿用未经验证的旧配置。

### 6.4 系统接口

```text
GET /api/v1/system/health
```

健康检查至少区分应用进程可用和关键依赖不可用，不应返回秘密配置。

### 6.5 P1 接口

收藏、忽略、已投递、重新探索、采集配置编辑、质量面板和审计查询在实现相应 P1 能力时再确定契约。未实现前不创建返回假数据的占位接口。

## 7. 数据所有权与持久化

以下是逻辑实体，而不是强制表清单：

| 逻辑实体 | 所有者 | 关键生命周期 |
|---|---|---|
| 招聘源与有效采集配置 | `collection` | 创建、验证、启停、替换 |
| 采集运行 | `collection` | 待执行、执行、部分成功、成功、失败 |
| 岗位事实 | `catalog` | 首次发现、更新、确认、关闭、待确认 |
| 画像快照 | `profiles` | 创建新版本，不覆盖历史版本 |
| 推荐运行与评估结果 | `orchestration` / `matching` | 绑定用户、画像版本、岗位事实版本和模型配置 |
| 用户岗位动作 | 用户侧应用服务，P1 | 按 `user_id + job_id` 幂等更新 |

### 7.1 岗位身份

岗位目录按以下证据优先建立稳定身份：

1. 来源提供的稳定岗位 ID；
2. 规范化后仍能唯一指向岗位的详情地址；
3. 来源、规范化标题、地点及其他稳定字段的组合。

具体哈希、数据库键和冲突合并算法属于内部实现。任何算法都必须满足同一岗位重复采集不新增、岗位合理变化不改变系统身份、碰撞可检测。

### 7.2 岗位状态同步

```text
创建 CrawlRun
→ 收集 CollectionBatch
→ 校验和 upsert
→ 评估 complete 是否可接受
→ 可接受才处理本次未出现岗位
→ 在同一业务边界内完成运行状态
```

部分成功允许保存已验证岗位，但不得关闭其他岗位。关闭决策应与批次写入保持事务一致，或具备等价的补偿与幂等保证。

### 7.3 搜索与向量

岗位目录必须提供关键词和语义召回能力，但不固定：

- 全文分析器；
- Embedding 厂商与维度；
- 一个岗位使用一个还是多个向量；
- 向量索引类型；
- 融合公式。

首版参考方案是标题与 JD 的 PostgreSQL 全文检索，加一个岗位级 Embedding 的 pgvector 检索。只有评估证明必要时再增加分块、多向量或独立搜索服务。

## 8. 推荐工作流

推荐运行至少经历以下公开阶段：

```text
PENDING
→ PROFILE
→ FILTER
→ RETRIEVE
→ EVALUATE
→ SAVE
→ COMPLETE
```

内部可以拆分或合并节点，只需映射到上述 `current_step`。

- 每个阶段失败都更新正式 `RunView`。
- 只对超时、限流和短暂依赖不可用等可恢复错误有限重试。
- 校验错误、权限错误和业务冲突不做盲目重试。
- 保存结果前重新校验 `job_id` 和 `JobFact`。
- 同一 `idempotency_key` 和相同用户请求返回同一业务运行或等价结果。

LangChain 可用于模型适配与结构化输出，LangGraph 可用于显式状态图和 Checkpoint。它们是参考实现，不改变上述端口，也不得让业务模块依赖其私有状态类型。

## 9. 安全、隐私与外部系统

- 原始简历与联系方式按敏感数据处理；仅在解析所需范围内读取，并支持后续替换或清除。
- 日志记录引用、摘要、计数和错误码，不记录完整简历、Cookie、Token、API Key 或完整模型敏感输入。
- 采集配置的公开部分与秘密凭据分开存储；普通管理响应也不返回秘密。
- 对外请求必须有超时、有限重试、合理 User-Agent、并发和频率限制。
- 不实现验证码破解、登录绕过或其他规避访问控制的逻辑。
- 管理端人工纠正岗位事实时，若实现该能力，必须保留修改原因和前后值。

## 10. 参考实现，不是公共契约

如果仓库尚无既定技术栈，首版优先采用：

- Python、FastAPI 和 Pydantic；
- PostgreSQL，全文检索与 pgvector；
- SQLAlchemy 与 Alembic，或等价的成熟持久化方案；
- `httpx` 处理普通请求，Playwright 用于必须执行浏览器行为的发现阶段；
- LangChain 封装模型能力，LangGraph 编排需要恢复的推荐工作流；
- pytest、离线响应样本和少量显式在线测试；
- Docker Compose 提供本地数据库等依赖。

以下内容由实现者根据现有代码和最小可行原则决定：

- 项目目录和文件数量；
- 函数或类的拆分；
- Repository、Service 或函数式组织；
- 依赖注入框架；
- Worker、调度器和队列；
- 表拆分、JSON 字段、索引和迁移细节；
- ATS 适配器内部是否拆为 detect、resolve、list、detail、normalize；
- Prompt 内容、模型供应商、召回阈值和分数融合公式；
- 是否以及何时引入 Crawl4AI 等额外依赖。

新增抽象或依赖应由当前需求、重复实现或可测量问题驱动，不为“以后可能需要”预建。

## 11. 契约验证与演进

公共契约至少通过以下自动化证据保护：

- 核心 DTO 的必填、可空、范围和序列化测试；
- `complete=false` 不关闭岗位等架构不变量测试；
- 模型输出未知或重复 `job_id` 的拒绝测试；
- API 路径、状态码、分页、错误和身份隔离测试；
- OpenAPI 变更检测；
- 幂等写入与岗位唯一性集成测试。

契约尚未被实现或使用时，可以在同一基础任务中进一步简化。一旦已有调用者、测试或持久化数据，以下变化必须作为显式契约变更处理：

- 字段删除、改名、类型或语义变化；
- 枚举删除或改义；
- 服务端口输入输出变化；
- HTTP 路径、方法、状态码或响应形状的不兼容变化；
- 岗位身份、关闭规则或用户隔离语义变化。

契约变更应同时更新本文、可执行 Schema、OpenAPI、测试和必要迁移。若变化改变的是产品范围或验收结果，还必须先更新 `requirements.md`；纯内部重构不修改本文。
