# JobPicky 架构与公共契约

> 状态：MVP 架构基线
> 需求范围和验收结果以 `requirements.md` 为准。
> 本文只固定跨模块协作所需的边界、数据语义和公开接口；模块内部实现保持弹性。

## 0. 如何使用本文

本文中的内容分为三类：

- **公共契约**：跨模块 DTO、服务端口、HTTP 路径及响应语义。实现后不得静默改变。
- **架构不变量**：无论采用何种框架和存储方案都必须成立的安全与一致性规则。
- **参考实现**：帮助首版快速落地的默认选择，可以在保持契约和需求不变的前提下替换。

除 §1.4 的当前仓库分层落地约束外，没有标为公共契约或架构不变量的私有文件、类、函数、表、索引、
算法和第三方库都不是硬性要求。示例代码用于说明接口语义，不要求照抄私有实现。

## 1. 总体架构

首版的参考落地方式是模块化单体：一个后端部署单元、一个主业务数据库，长任务由同进程后台执行器或独立 Worker 运行。这不是客户端契约；如果现有仓库或部署条件已有更简单的合适方案，可以调整物理结构，但下述逻辑所有权和公共契约保持不变。

### 1.1 逻辑模块

| 模块 | 负责 | 不负责 |
|---|---|---|
| 招聘源与采集 `collection` | 来源识别、平台采集、未知来源探索、原始字段标准化 | 决定系统岗位 ID、关闭岗位、执行推荐 |
| 岗位目录 `catalog` | 岗位事实、身份去重、生命周期，并执行结构化、全文与向量查询 | 调用招聘网站、决定召回策略、生成模型推荐理由 |
| 用户画像 `profiles` | 当前画像表单、简历导入草稿、草稿/快照校验与版本 | 搜索岗位、改变岗位事实 |
| 匹配 `matching` | 生成硬筛选与检索条件、融合候选、模型评估 | 保存或编造岗位事实、控制采集 |
| 编排 `orchestration` | 创建运行、按顺序调用能力、记录进度、失败与恢复 | 承载采集、SQL、检索或模型算法 |
| 接口 `api` | 鉴权上下文、输入校验、DTO 转换、HTTP 语义 | 业务算法和直接数据库访问 |
| 基础设施 `infrastructure` | 数据库、HTTP、浏览器、模型、任务执行器的具体接入 | 定义产品规则 |

模块名称是语义边界。当前仓库的顶层职责位置遵循 §1.4；模块内部可以合并相邻的私有文件，但不得混淆
数据所有权或形成第二套平行业务入口。

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

### 1.4 当前仓库的分层落地约束

当前 FastAPI 模块化单体采用以下依赖方向：

```text
Router / Controller
        ↓
Application Service
        ↓
Port / 私有持久化协议
        ↑
Repository / Infrastructure Adapter
        ↓
PostgreSQL 或外部服务
```

新增用户功能按下列位置扩展；条目只在真实功能实现时创建，不为未来能力预建空目录、空 Service 或空
Repository。现有采集器、Embedding、模型适配器等未展开文件继续保留在其所属模块中。

```text
src/jobpicky/
├── app.py                         # FastAPI 应用创建与依赖装配
├── api/
│   ├── dependencies.py            # 身份上下文和 Service 注入
│   └── routers/                   # HTTP Controller
│       ├── auth.py
│       ├── jobs.py
│       ├── saved_jobs.py
│       ├── profiles.py
│       └── recommendations.py
├── auth/
│   └── service.py
├── collection/                    # 来源采集与标准化
├── catalog/
│   ├── service.py
│   ├── hard_filter.py
│   └── query_terms.py
├── profiles/
│   └── service.py
├── matching/
│   └── service.py
├── orchestration/
│   ├── service.py
│   └── store.py                   # 模块私有记录与持久化协议
├── contracts/                     # 跨模块公共 DTO
├── ports.py                       # 跨模块公共端口
└── infrastructure/
    ├── database.py
    ├── auth_store.py
    ├── credit_store.py
    ├── saved_job_store.py
    ├── job_catalog.py
    ├── profile_store.py
    └── recommendation_store.py    # PostgreSQL 推荐存储适配器
```

分层职责必须满足：

- `app.py` 是装配入口，只创建应用、构造依赖并注册 Router。
- `api/routers/` 只处理 HTTP 参数、身份依赖、状态码和 API DTO，不写 SQL、不决定业务规则，也不直接调用
  Repository。
- 各业务模块的 `service.py` 实现用例，负责权限、事务边界、幂等和业务编排；它不依赖 FastAPI 请求对象、
  ORM 模型或具体数据库实现。
- 跨模块 DTO 只放在 `contracts/`，跨模块调用只依赖 `ports.py`；模块内部专用记录和持久化协议留在模块内，
  不为私有实现扩大公共契约。
- `infrastructure/` 实现数据库、模型、HTTP 和任务执行器等适配器，只负责外部 I/O 和持久化语义，不定义
  产品规则。
- `DAO`、`Repository` 和 `Store` 在本项目中属于同一数据访问角色；同一数据边界只能保留一套实现，不增加
  `Service → Repository → DAO` 的无价值转发层。
- 涉及多表原子写入的用例由 Service 通过同一事务或最小 Unit of Work 完成，禁止由 Router 顺序调用多个
  自动提交的 Store 拼接事务。

现有 `orchestration/store.py` 中的 `PostgresRecommendationRunStore` 是迁移点：下一次修改正式推荐持久化时，
将 PostgreSQL 实现移入 `infrastructure/recommendation_store.py`，模块内只保留记录和私有协议；迁移期间不得
新增第二套并行实现。

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

岗位目录对其他模块提供的内部事实视图。前端不直接复用它，岗位列表、详情、收藏和推荐卡片使用下方专用
API View，避免把 `fact_version`、召回分或其他内部字段泄露到页面契约。

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
| `metadata` | `object` | 否 | 采集质量、来源等非敏感扩展信息 |

普通用户接口不得返回内部去重键、内容哈希、Embedding、原始响应和秘密采集参数。

### 4.6 `ProfileDraft`、`ProfileSaveRequest` 与 `ProfileSnapshot`

首版画像由用户表单直接填写。`ProfileDraft` 只包含用户可编辑字段，`ProfileSaveRequest` 在其上增加可空的
`base_version`；`warnings`、用户 ID、画像 ID、版本和创建时间均为服务端字段，不能由用户提交。

| 字段 | 类型 | 约束 |
|---|---|---|
| `target_roles` | `list[str]` | 1～10 项，每项 1～100 字符 |
| `target_locations` | `list[str]` | 最多 10 项，空列表表示不限 |
| `recruitment_types` | `list[str]` | 仅 `校招`、`社招`、`实习`，最多 3 项 |
| `skills` | `list[str]` | 最多 50 项，每项 1～100 字符 |
| `excluded_roles` | `list[str]` | 最多 20 项，每项 1～100 字符 |
| `education` | `str \| null` | `高中及以下`、`专科`、`本科`、`硕士`、`博士`或空 |
| `graduation_year` | `int \| null` | 当前年份前 80 年至后 10 年 |
| `expected_salary_min` | `int \| null` | 0～1000000 元/月 |
| `experience_summary` | `str \| null` | 最多 5000 字符 |
| `extra_request` | `str \| null` | 最多 1000 字符 |

`skills` 与 `experience_summary` 至少填写一项。标签先去除首尾空白、按规范化值去重，再保存展示文本。
`ProfileSnapshot` 增加 `id`、`user_id`、从 1 递增的 `version`、服务端 `warnings` 和带时区的 `created_at`，
并且不可变。一个用户只有一个逻辑当前画像；内容无变化不生成新版本，版本冲突返回稳定错误。

`CurrentProfileView` 是用户接口专用的只读投影，保留画像字段、版本、警告和创建时间，但不返回 `user_id`。

`ProfileImportDraft` 是文件解析专用的宽松草稿：字段与 `ProfileDraft` 相同，但允许 `target_roles`、`skills`
和 `experience_summary` 暂时为空，因为模型不能为满足正式画像校验而编造信息。`ProfileImportView` 包含
`draft` 与服务端 `warnings`；用户必须校对并通过 `ProfileSaveRequest` 保存，正式画像约束不变。

原始简历属于受保护输入，不进入普通画像响应或日志。本阶段不持久化原文件；简历解析和未来 AI 对话都只能
产出草稿，不能绕过 `ProfileSaveRequest` 直接修改正式画像。

### 4.6.1 前端岗位 View

`JobListItem`、`JobDetailView`、`SavedJobView` 和 `JobFilterOptions` 是前端专用 DTO：

- `JobListItem` 只含岗位卡片字段、来源 `{id, name}`、描述预览和可空的 `is_saved`；不含完整 JD、状态、事实版本或内部检索字段。`batch` 保留来源表格中的原始批次文本，不用 `recruitment_type` 的粗粒度映射替代。
- `JobDetailView` 含完整 JD、详情/投递链接、生命周期状态以及 `published_at`、`deadline_at`、`first_seen_at`、
  `last_confirmed_at`、`updated_at` 等时间字段；不含 `fact_version`、去重键、Embedding 或秘密来源配置。
- `SavedJobView` 包含 `saved_at` 与岗位列表视图，岗位状态保留以便展示已关闭或待确认岗位。
- `JobFilterOptions` 提供当前可见岗位池的规范化城市、公司性质、来源、原始招聘批次、招聘类型、学历、届次和分页限制；`batches` 将已知的 `metadata["batch"]` 拆分为单个批次后返回。
- `CompanyListItem` 和 `CompanyPoolPage` 是岗位池的公司视图 DTO；公司组优先使用飞书 `source_record_id`，缺失时使用稳定表格行或岗位标识兜底。
- 岗位池的发布日期筛选使用 `JobListQuery.published_within_days` 或 `published_at_unknown`，只读取岗位事实的
  `published_at`，不把 `first_seen_at` 当作发布日期。

这些 View 不继承或替换 `JobFact`；目录内部仍以 `JobFact` 作为岗位事实唯一来源。

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
| `evidence_details` | `list[MatchEvidence]` | 否 | 岗位要求、候选人证据、匹配关系、重要性和解释 |
| `constraint_conclusions` | `object` | 否 | 模型对客观约束的结构化结论 |

`job_id` 必须来自输入候选且每批最多出现一次。评估中不得包含可覆盖 `JobFact` 的岗位字段。

### 4.10 `RecommendationItem`

内部最终结果使用组合结构，显式区分事实、召回和判断。以下是省略部分字段的结构示例：

```json
{
  "job": {"id": "job-id", "company_name": "某公司", "title": "软件工程师"},
  "retrieval": {"job_id": "job-id", "retrieval_score": 0.82, "sources": ["keyword", "semantic"]},
  "assessment": {"job_id": "job-id", "matched": true, "match_score": 88, "reason": "…", "matched_strengths": [], "gaps": []}
}
```

完整字段分别遵循 `JobFact`、`Candidate` 和 `MatchAssessment`。三个 `job_id` 必须一致；普通结果列表只包含 `matched=true` 的项。`job` 是保存推荐结果前从岗位目录读取并与结果一同保存的事实快照，其 `fact_version` 用于追溯；用户结果投影在查询时优先组合当前岗位的 `status`、`published_at` 和 `deadline_at`，岗位已不存在或字段不可用时回退快照。

`RecommendationCandidate` 只作为召回到评估之间的内部中间契约；推荐运行持久化和用户结果接口使用
`RecommendationItem`，并要求 `assessment.matched=true`。该内部 DTO 保留 `retrieval` 和完整 `JobFact`，
不直接作为前端响应。

前端使用独立的 `RecommendationCardView`：

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
    "status": "OPEN",
    "published_at": "2026-07-30T08:00:00Z",
    "deadline_at": "2026-08-31T15:59:59Z",
    "first_seen_at": "2026-07-20T08:00:00Z"
  },
  "assessment": {"match_score": 89, "reason": "…", "matched_strengths": [], "gaps": [], "evidence": []},
  "is_saved": true,
  "feedback": "LIKE"
}
```

推荐卡片不返回 `retrieval_score`、薪资、学历、届次、完整 JD、来源标识或 `fact_version`。卡片中的
`RecommendationAssessmentView` 是 `MatchAssessment` 的前端投影，只保留匹配分、中文理由、优势、缺口和依据，
不返回内部 `job_id` 或 `matched`。单次任务结果使用扩展的 `RecommendationResultView` 增加 `is_deleted` 和
`deleted_at`，软删除只隐藏“全部推荐”而保留历史任务。

### 4.11 运行与通用响应

`RunAccepted`：

| 字段 | 类型 |
|---|---|
| `run_id` | `str` |
| `status` | `RunStatus`，创建时通常为 `PENDING` |

推荐任务创建使用 `RecommendationRunAccepted`，其 `status` 只允许用户可见的
`PENDING`、`RUNNING`、`SUCCEEDED`、`FAILED`，并增加 `credits_charged` 与 `balance_after`；采集运行继续使用
上述通用 `RunAccepted`。

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
AUTHENTICATION_REQUIRED
SESSION_EXPIRED
ACCOUNT_DISABLED
INVALID_CREDENTIALS
EMAIL_ALREADY_REGISTERED
TOO_MANY_ATTEMPTS
INSUFFICIENT_CREDITS
PROFILE_NOT_FOUND
PROFILE_VERSION_CONFLICT
IDEMPOTENCY_CONFLICT
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

所有用户可见 `message` 使用中文；机器码保持英文大写且一个错误码只表达一个语义。认证、积分、画像版本
和幂等错误必须使用上表中的稳定码。`ErrorBody` 仅用于 HTTP 响应，必须带当前请求的 `request_id`，可选
关联 `run_id`。
后台运行持久化使用不含 `request_id` 的 `RunError`；运行历史不能因为查询请求不同而改变其错误内容。

用户侧推荐任务使用独立的 `RecommendationTaskView`，包含 `PENDING/RUNNING/SUCCEEDED/FAILED`、
`current_step`、`progress_percent`、计数、`CreditUsage` 和脱敏中文错误；它不把管理端或内部采集运行字段
直接暴露给用户。推荐创建使用独立的 `RecommendationRunAccepted`，包含推荐任务状态、`credits_charged` 和
`balance_after`；采集创建继续使用 `RunAccepted`。

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
    ) -> ProfileImportView: ...

    async def parse_images(
        self,
        image_pages: Sequence[bytes],
        extra_request: str | None,
    ) -> ProfileImportView: ...
```

`ProfileParserPort` 由模型基础设施实现，接收画像模块准备好的正文或临时 PNG 页面图片，并返回经过结构校验的草稿。
文件格式识别、DOCX/TXT/Markdown 文本提取和 PDF 页面渲染属于画像模块的导入边界；图片页以进程内字节序列跨过模型端口，
不把临时文件路径或 PDF 格式细节耦合进模型端口。保存、读取和创建新版本仍由画像应用服务负责。

```python
class ProfileSnapshotReaderPort(Protocol):
    async def get_snapshot(self, user_id: str, profile_id: str) -> ProfileSnapshot: ...
    async def get_current(self, user_id: str) -> ProfileSnapshot: ...
```

推荐编排器只能通过该只读端口读取画像快照；画像私有 Repository 或 ORM 不得出现在编排模块。

画像 P0 应用服务最小契约为：按用户读取当前版本，以及用 `base_version` 和幂等键保存完整表单。推荐编排器
只能通过 `get_current` 读取当前快照，不接受前端传入的 `profile_id`。

```python
class ProfileApplicationPort(Protocol):
    async def get_current(self, user_id: str) -> ProfileSnapshot: ...

    async def save_current(
        self,
        user_id: str,
        draft: ProfileSaveRequest,
        idempotency_key: str,
    ) -> ProfileSnapshot: ...

    async def import_resume(
        self,
        user_id: str,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> ProfileImportView: ...
```

简历导入为同步、无持久化的首版用例：校验文件后，PDF 渲染为临时页面图片、其他格式提取正文，再调用
`ProfileParserPort`，成功时直接返回草稿。
只有真实延迟或恢复需求证明必要时才升级为可查询的异步运行，不提前创建导入表或 Worker。

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
        extra_request: str | None = None,
        idempotency_key: str | None = None,
    ) -> RecommendationRunAccepted: ...

    async def list_runs(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationTaskView]: ...

    async def get_run(
        self,
        user_id: str,
        run_id: str,
    ) -> RecommendationTaskView: ...

    async def get_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationResultView]: ...
```

`get_results` 返回前端 `RecommendationResultView`（见 §4.10）。它由保存前重新读取的 `JobFact` 快照组装，
结果列表不包含 `matched=false` 的评估项目；`RecommendationItem` 只属于内部匹配和持久化边界。

具体图节点和执行器不是端口的一部分。模型工具只包装上述业务端口，不应形成另一套平行业务接口。

管理员推荐历史不复用用户侧 `get_run(user_id, run_id)`，而使用独立的管理员查询端口：

```python
class AdminRecommendationRunQueryPort(Protocol):
    async def list_runs(self, admin_id: str, page: int, page_size: int) -> Page[RunView]: ...
    async def get_run(self, admin_id: str, run_id: str) -> RunView: ...
```

用户认证、积分、收藏和推荐交互使用带用户上下文的最小端口：

```python
class AuthenticationPort(Protocol):
    async def register(self, request: RegisterRequest) -> LoginResponse: ...
    async def login(self, request: LoginRequest) -> LoginResponse: ...
    async def refresh(self, refresh_token: str) -> AccessTokenResponse: ...
    async def logout(self, refresh_token: str | None) -> None: ...
    async def get_current_user(self, user_id: str) -> AuthUserView: ...


class CreditsPort(Protocol):
    async def get_summary(self, user_id: str) -> CreditSummary: ...
    async def charge_recommendation(
        self, user_id: str, run_id: str, amount: int
    ) -> CreditUsage: ...
    async def refund_recommendation(
        self, user_id: str, run_id: str, amount: int
    ) -> CreditUsage: ...


class SavedJobPort(Protocol):
    async def set_saved(self, user_id: str, job_id: str, is_saved: bool) -> SavedJobState: ...
    async def list_saved(self, user_id: str, page: int, page_size: int) -> Page[SavedJobView]: ...


class JobPoolQueryPort(Protocol):
    async def list_jobs(self, user_id: str | None, query: JobListQuery) -> JobPoolPage: ...
    async def get_job(self, user_id: str | None, job_id: str) -> JobDetailView: ...
    async def get_filter_options(self) -> JobFilterOptions: ...


class RecommendationQueryPort(Protocol):
    async def list_recommendations(
        self, user_id: str, page: int, page_size: int, sort: RecommendationSort
    ) -> Page[RecommendationCardView]: ...
    async def update_feedback(
        self, user_id: str, recommendation_id: str, feedback: Feedback | None
    ) -> RecommendationFeedbackView: ...
    async def delete_recommendation(self, user_id: str, recommendation_id: str) -> None: ...
```

这些端口只定义跨模块输入输出和权限上下文，不代表本阶段已经有实现；未实现能力不得创建假数据路由。

来源管理、用户岗位详情和管理端岗位查询也由应用服务端口承接：`SourceApplicationPort`、
`UserJobQueryPort` 和 `AdminJobQueryPort`。它们分别携带 `admin_id` 或 `user_id`，禁止通过调用者自带的
资源 ID 推断权限。

```python
class UserJobQueryPort(Protocol):
    async def get_job(self, user_id: str, job_id: str) -> JobDetailView: ...


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
- 用户接口位于 `/api/v1/user`，公开岗位和认证接口分别位于 `/api/v1/jobs`、`/api/v1/auth`，管理接口位于
  `/api/v1/admin`，系统接口位于 `/api/v1/system`。
- JSON 为默认格式；文件上传使用 `multipart/form-data`。
- 长任务创建成功返回 `202 Accepted` 和 `RecommendationRunAccepted`；采集运行继续使用 `RunAccepted`。
- 列表使用统一分页，页大小上限由服务配置并写入 OpenAPI。
- `GET /api/v1/jobs` 的多选筛选使用重复 query 参数传递；未提供时按空列表处理，不使用 GET 请求体。
- `batch` 是岗位池对原始招聘批次单元的多选筛选；同一查询的多个批次使用 OR，`recruitment_type` 继续保留为校招、社招、实习等粗粒度规范字段，两者不互相映射。
- 错误使用统一错误响应；内部堆栈不得对外返回。
- OpenAPI 是可执行接口清单，必须通过契约测试与本文语义保持一致。

### 6.1.1 P0 HTTP API 覆盖表

以下表是 P0 HTTP → 应用服务/端口 → DTO → 权限上下文的唯一覆盖清单。当前阶段只固化契约，未实现的
业务 handler 不创建占位接口。

| HTTP API | 应用服务/端口 | 输入/输出 DTO | 权限上下文 |
|---|---|---|---|
| `GET /api/v1/jobs` | `JobPoolQueryPort.list_jobs` | `JobListQuery` → `JobPoolPage` | 可选 `user_id` |
| `GET /api/v1/jobs/filter-options` | `JobPoolQueryPort.get_filter_options` | `JobFilterOptions` | 无 |
| `GET /api/v1/jobs/{job_id}` | `JobPoolQueryPort.get_job` | `JobDetailView` | 可选 `user_id` |
| `GET /api/v1/user/recommendations` | `RecommendationQueryPort.list_recommendations` | `Page[RecommendationCardView]` | `user_id` |
| `GET /api/v1/user/recommendation-runs` | `RecommendationOrchestratorPort.list_runs` | `Page[RecommendationTaskView]` | `user_id` |
| `POST /api/v1/user/recommendation-runs` | `RecommendationOrchestratorPort.start` | `RecommendationRunRequest` → `RecommendationRunAccepted` | `user_id` |
| `GET /api/v1/user/recommendation-runs/{run_id}` | `RecommendationOrchestratorPort.get_run` | `RecommendationTaskView` | `user_id` |
| `GET /api/v1/user/recommendation-runs/{run_id}/results` | `RecommendationOrchestratorPort.get_results` | `Page[RecommendationResultView]` | `user_id` |
| `PUT /api/v1/user/recommendations/{recommendation_id}/feedback` | `RecommendationQueryPort.update_feedback` | `RecommendationFeedbackRequest` → `RecommendationFeedbackView` | `user_id` |
| `DELETE /api/v1/user/recommendations/{recommendation_id}` | `RecommendationQueryPort.delete_recommendation` | `204 No Content` | `user_id` |
| `PUT/DELETE /api/v1/user/saved-jobs/{job_id}` | `SavedJobPort.set_saved` | `SavedJobState` | `user_id` |
| `GET /api/v1/user/credits` | `CreditsPort.get_summary` | `CreditSummary` | `user_id` |
| `GET /api/v1/user/profiles/current` | `ProfileApplicationPort.get_current` | `ProfileSnapshot` → `CurrentProfileView` | `user_id` |
| `PUT /api/v1/user/profiles/current` | `ProfileApplicationPort.save_current` | `ProfileSaveRequest` → `CurrentProfileView` | `user_id` |
| `POST /api/v1/user/profile-imports` | `ProfileApplicationPort.import_resume` | multipart `file` → `ProfileImportView` | `user_id` |
| `POST /api/v1/auth/register` | `AuthenticationPort.register` | `RegisterRequest` → `LoginResponse` | 无 |
| `POST /api/v1/auth/login` | `AuthenticationPort.login` | `LoginRequest` → `LoginResponse` | 无 |
| `POST /api/v1/auth/refresh` | `AuthenticationPort.refresh` | Cookie → `AccessTokenResponse` | Refresh Cookie |
| `POST /api/v1/auth/logout` | `AuthenticationPort.logout` | Cookie → `204 No Content` | Refresh Cookie |
| `GET /api/v1/auth/me` | `AuthenticationPort.get_current_user` | `AuthUserView` | `user_id` |
| `GET /api/v1/user/saved-jobs` | `SavedJobPort.list_saved` | `Page[SavedJobView]` | `user_id` |
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
| `GET` | `/api/v1/jobs` | 岗位池匿名第一页预览或登录后的搜索筛选分页 |
| `GET` | `/api/v1/jobs/filter-options` | 查询岗位筛选规范化选项 |
| `GET` | `/api/v1/jobs/{job_id}` | 查询统一岗位详情 |
| `GET` | `/api/v1/user/recommendations` | 查询全部推荐卡片 |
| `GET` | `/api/v1/user/recommendation-runs` | 查询推荐任务 |
| `POST` | `/api/v1/user/recommendation-runs` | 使用当前画像发起推荐并扣除积分 |
| `GET` | `/api/v1/user/recommendation-runs/{run_id}` | 查询推荐状态与真实进度 |
| `GET` | `/api/v1/user/recommendation-runs/{run_id}/results` | 查询单次推荐结果 |
| `PUT` | `/api/v1/user/recommendations/{recommendation_id}/feedback` | 幂等保存或清除推荐反馈 |
| `DELETE` | `/api/v1/user/recommendations/{recommendation_id}` | 软删除推荐记录 |
| `PUT/DELETE` | `/api/v1/user/saved-jobs/{job_id}` | 幂等收藏或取消收藏岗位 |
| `GET` | `/api/v1/user/credits` | 查询积分余额和推荐价格 |
| `GET` | `/api/v1/user/profiles/current` | 查询当前画像 |
| `PUT` | `/api/v1/user/profiles/current` | 以版本控制保存当前画像 |
| `POST` | `/api/v1/user/profile-imports` | 上传简历并同步生成可校对画像草稿 |
| `GET` | `/api/v1/user/saved-jobs` | 查询收藏岗位 |
| `POST` | `/api/v1/auth/register` | 注册普通用户并初始化积分 |
| `POST` | `/api/v1/auth/login` | 邮箱密码登录 |
| `POST` | `/api/v1/auth/refresh` | 轮换 Refresh Cookie 并返回新 Access Token |
| `POST` | `/api/v1/auth/logout` | 退出当前设备 |
| `GET` | `/api/v1/auth/me` | 查询当前登录用户 |

画像保存只接受 `ProfileSaveRequest` 的用户字段和 `base_version`，创建或修改当前画像，不原地改变历史推荐引用的快照。
简历导入只接受单个受支持文件并返回草稿，不保存文件或画像版本。
发起推荐的最小输入是可选的 `extra_request`，服务端自动读取当前画像；客户端通过 `Idempotency-Key` 安全重试。

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

### 6.5 尚未实现的接口

忽略、已投递、重新探索、采集配置编辑、质量面板、旧版 DOC 和审计查询在实现相应能力时再确定契约。虽然收藏、认证、
推荐交互和用户画像的契约已经确认，但本阶段只同步 Schema、端口、配置和 OpenAPI 验证，不创建返回假数据的
业务路由。所有未实现能力都必须显式失败或保持无路由状态。

## 7. 数据所有权与持久化

以下是逻辑实体，而不是强制表清单：

| 逻辑实体 | 所有者 | 关键生命周期 |
|---|---|---|
| 招聘源与有效采集配置 | `collection` | 创建、验证、启停、替换 |
| 采集运行 | `collection` | 待执行、执行、部分成功、成功、失败 |
| 岗位事实 | `catalog` | 首次发现、更新、确认、关闭、待确认 |
| 画像快照 | `profiles` | 创建新版本，不覆盖历史版本 |
| 推荐运行与评估结果 | `orchestration` / `matching` | 绑定用户、画像版本、岗位事实版本和模型配置 |
| 用户岗位动作 | 用户侧应用服务 | 按 `user_id + job_id` 幂等更新，包含收藏状态 |

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
- PDF 渲染产生的中间图片与原始简历具有相同敏感级别，只在当前请求生命周期内存在，不写入持久化存储或日志。
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

- §1.4 未固定的模块内部私有文件数量与进一步拆分；
- 函数或类的拆分；
- Service 与 Repository 内部采用类或函数的组织方式；
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
