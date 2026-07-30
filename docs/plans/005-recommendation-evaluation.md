# 005 推荐链路：语义召回与模型评估

## 1. 目标

在现有推荐运行骨架上完成一条可验证、可失败、事实可追溯的推荐链路：

```text
ProfileSnapshot
    ↓
硬过滤
    ↓
关键词召回 ─┐
            ├─ 融合为 RecommendationCandidate
语义召回 ──┘
    ↓
JobEvaluatorPort（DashScope OpenAI-compatible / Kimi）
    ↓
严格校验 MatchAssessment
    ↓
重新读取 JobFact，组装 RecommendationItem
    ↓
保存最终推荐结果
```

本计划分为两个实现小步：

1. **语义召回**：确定本地 Embedding 模型、向量维度、调用方式和超时预算；增加 `job.embedding` 迁移、回填和 pgvector 查询，并把关键词与语义两路接入编排器。
2. **模型评估与事实重组**：实现 `JobEvaluatorPort` 的模型适配器，强制结构化输出，严格校验评估结果，并将候选结果转换为最终 `RecommendationItem` 后保存。

## 2. 已确认的方案与不变量

### 2.1 Embedding 方案

- 第一稿使用本地 `BAAI/bge-small-zh-v1.5`，通过 LangChain 的 Hugging Face Embeddings 适配器加载。
- 模型使用 512 维向量；`job.embedding` 使用 `Vector(512)`。
- 使用归一化向量和 cosine 相似度；第一版每个岗位只有一个岗位级向量，不做分块、多向量或独立字段向量。
- `bge-small-zh-v1.5` 第一版不额外拼接 query instruction，query 和岗位向量统一采用归一化编码；模型输入上限按 512 token 处理。
- 模型只能从本地文件加载，不因联网或模型缺失而自动切换到外部模型。配置可指向已下载的 Hugging Face cache 根目录或具体 snapshot 目录，由适配器解析并固定 revision；仓库不写入开发机绝对路径。
- 由独立的 canonical job embedding text builder 生成岗位向量文本，优先包含岗位标题、地点、招聘性质、学历等结构化字段，再包含 JD 正文，并按模型最大输入长度截断；未来采集写入和本次回填必须复用它。用户画像查询文本仍由 `MatchingPort.build_query_text` 生成，但和岗位文本共享同一套长度/清洗规则。
- 查询和批量回填均通过同一个 Embedding 端口调用。模型加载应懒加载且进程内复用；同步 LangChain 调用放入线程执行，不能阻塞异步事件循环。
- 初始默认预算固定为：单次查询总墙钟预算 5 秒，回填批量 32、单批预算 60 秒；这些数值可配置但必须有明确默认值。第一版本地模型不做网络重试，但加载、维度错误和超时必须转换为明确的依赖错误。
- 未配置 Embedding、模型无法加载、向量维度不为 512 或调用超时时，`semantic_search` 必须显式失败；编排器也必须使本次推荐运行失败，不能退化为“只有关键词召回”或返回假向量、零向量、随机向量结果。
- 后续若切换外部 Embedding 模型，必须单独评估维度、revision 和全量重建/回填；本计划不引入双维度兼容或自动切换。

Embedding 配置使用以下项目环境变量；模型路径指向已下载的 cache 根目录或具体 snapshot 目录，缺失时不提供默认假实现：

```text
JOBPICKY_EMBEDDING_PROVIDER=local
JOBPICKY_EMBEDDING_MODEL_PATH=~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5
JOBPICKY_EMBEDDING_QUERY_TIMEOUT_SECONDS=5
JOBPICKY_EMBEDDING_BATCH_SIZE=32
```

### 2.2 LLM 评估方案

- 评估器使用 LangChain 的 OpenAI-compatible Chat Model 适配方式调用 DashScope：
  - provider：`dashscope`
  - model：`kimi-k2.6`
  - base URL：`https://dashscope.aliyuncs.com/compatible-mode/v1`
  - API key 仅从环境变量读取，不写入代码、配置文件、日志或测试 fixture。
- 遵循项目配置的 `JOBPICKY_` 环境变量前缀。配置语义固定为：

  ```text
  JOBPICKY_LLM_PROVIDER=dashscope
  JOBPICKY_LLM_MODEL=kimi-k2.6         # 必填，无默认模型
  JOBPICKY_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
  JOBPICKY_DASHSCOPE_API_KEY=<从环境注入>
  JOBPICKY_LLM_TIMEOUT_SECONDS=30
  JOBPICKY_LLM_MAX_RETRIES=1
  JOBPICKY_EVALUATION_BATCH_SIZE=10
  JOBPICKY_MODEL_CONFIG_VERSION=recommendation-v1
  ```

- 模型适配器只输出 `MatchAssessment` 允许的字段，外层使用 `{"assessments": [...]}`；Pydantic wrapper 和 assessment DTO 均使用 `extra="forbid"`。
- 请求中明确要求 JSON，并关闭 DashScope/Kimi 的 thinking 输出，以避免把非 JSON 思考内容混入结构化响应。适配器仍必须在应用边界再次解析和校验，不能把 provider 的 JSON mode 当作唯一保证。
- 评估输入只包含冻结的 `ProfileSnapshot`/有效额外请求、候选岗位对应的 `JobFact` 和候选顺序；不发送 embedding、数据库内部字段或无关隐私字段，也不在日志中打印完整简历、JD、prompt 或响应。
- 模型不得输出公司、岗位标题、JD、地点、链接等岗位事实字段。未知字段、事实幻觉字段、非法 JSON、未知 `job_id`、重复 `job_id` 或缺失 `job_id` 都属于评估失败。
- 每批候选使用稳定顺序，默认每批 10 个、单批 timeout 30 秒、最多重试 1 次；仅对 timeout、429、5xx 做有限重试，超出预算或出现不可恢复的结构化校验错误时立即失败。
- `matched=false` 是合法评估结果，但不能组装成最终 `RecommendationItem`；最终结果只保存 `matched=true` 的项目。任一评估批次失败时，不保存部分成功的最终结果，运行在 `EVALUATE` 阶段失败并带上可诊断的阶段和原因。

### 2.3 事实与存储不变量

- `RecommendationCandidate` 继续作为召回与评估之间的内部/中间契约；对外结果和持久化结果切换为 `RecommendationItem`。
- `RecommendationItem.job` 中的公司、标题、JD、地点和链接全部来自评估后重新读取的 `JobFact`，模型输出不能覆盖或补充这些岗位事实。
- 组装时校验 candidate、assessment、JobFact 三者 `job_id` 一致，并使用重新读取的 `JobFact` 快照及其 `fact_version`。
- 当前开发数据库按“可重建”处理：迁移 head 变更后重新建库、回填和播种，不增加旧 `recommendation_run.results` 中 `RecommendationCandidate` JSON 的兼容转换逻辑。
- 结果仍可复用现有 JSONB 列，但读写类型、端口返回类型和快照格式改为 `RecommendationItem`；不另造一套并行结果存储。
- `model_config_version` 改为运行创建时确定且持久化的显式版本，第一版固定为 `recommendation-v1`；它至少覆盖 embedding 模型/revision/维度、LLM provider/model、prompt/schema 版本和融合配置版本。运行过程中不根据当前环境重新计算版本，后续模型或 schema 变化必须升级版本。

## 3. 小步一：语义召回

### 3.1 公共契约与配置

修改公共端口和配置，使依赖可注入、可替换且可测试：

- 在 `src/jobpicky/ports.py` 增加 Embedding 端口，至少覆盖单条 query embedding 和批量 document embedding；明确 512 维、超时和依赖失败语义。
- 在 `src/jobpicky/ports.py` 增加独立的 `JobEmbeddingStorePort`，固定提供“按分页读取待回填 JobFact”和“按 job_id 批量写入 512 维向量”两个能力；由 PostgreSQL 基础设施实现，回填应用服务只能通过该端口读写，不能直接操作私有表。
- 在 `src/jobpicky/config.py` 增加本地 embedding、LLM、评估批量、timeout、retry、融合和配置版本配置。初始默认值为 query 5 秒、回填 batch 32/60 秒、LLM 单批 30 秒、LLM 最多重试 1 次、评估 batch 10、配置版本 `recommendation-v1`。配置解析不能把缺失的模型/API key 静默变成可用的假实现。
- 在 `pyproject.toml` 增加锁定所需的 `langchain-core`、`langchain-huggingface`、`langchain-openai` 和本地 Sentence Transformers 运行依赖，并通过 `uv.lock` 固定解析结果；普通 CI 仍不加载真实模型。
- 保持 `JobFact`、公开 API DTO 不暴露 embedding；embedding 只属于基础设施索引和内部端口。

### 3.2 迁移与索引

新增 `alembic/versions/0005_job_embedding.py`，下接 `0004_profile_and_run.py`：

- 在 `job` 表增加可空的 `embedding vector(512)` 列。
- 为非空向量建立 HNSW cosine 索引，使用 `vector_cosine_ops`；索引名固定、可逆迁移，并覆盖向量查询实际使用的排序表达式。
- 迁移只负责结构，不在 migration 中加载模型、不调用网络、不执行业务回填。
- 利用已有 pgvector 扩展；若迁移需要声明扩展，使用幂等方式，不破坏现有初始化流程。

### 3.3 本地 LangChain 适配器与回填

新增 `src/jobpicky/matching/embedding_text.py`、`src/jobpicky/infrastructure/embeddings.py`、`src/jobpicky/infrastructure/job_embedding_store.py` 和 `scripts/backfill_job_embeddings.py`：

- 使用 `langchain_huggingface.HuggingFaceEmbeddings`，固定本地加载、CPU 默认设备、归一化和模型 revision；不在运行时下载模型。
- 实现懒加载单例/进程内缓存，query 和 documents 复用同一个模型实例；同步调用使用 `asyncio.to_thread`，并用必要的锁保证首次加载与并发调用安全。
- 回填从现有岗位事实读取 canonical embedding text，按批处理写入 `job.embedding`，支持进度、失败计数和可重跑；不能把不完整岗位事实或默认假向量写入数据库。
- 回填与迁移分离：先升级结构，再显式执行回填。回填命令缺少模型配置时直接返回非零状态并报告原因。
- 回填测试使用固定 fake embedding 验证批量、维度、持久化和重复执行；真实本地模型 smoke test 不作为普通 CI 的网络/硬件前置条件。

### 3.4 `semantic_search` 与双路召回

修改 `src/jobpicky/infrastructure/job_catalog.py` 及相关查询测试：

- 从注入的 Embedding 端口生成 query 向量；空的 eligible ID 集合直接返回空结果，不发起无意义的模型调用。
- 以 pgvector cosine distance 做最近邻排序，只查询硬过滤后的 eligible job IDs，排除 `embedding IS NULL`，应用候选上限，并把数据库距离转换为 `SearchHit.score` 约定的 `[0, 1]` 分数。
- 保留 keyword channel 的现有语义；确保 semantic channel 使用同一批 `JobFact` 的 ID 范围，结果排序具有稳定的 job_id tie-breaker。
- 在 `RecommendationRunService` 的 `RETRIEVE` 阶段先硬过滤，再使用 `asyncio.gather` 并行调用关键词和语义两路召回，使用已有 fusion 配置合并为 `RecommendationCandidate`；两路分数、来源和最终 retrieval score 都可追溯。
- 语义依赖不可用时，双路召回整体失败并持久化失败状态，不能只返回关键词结果。

## 4. 小步二：模型评估、事实重组与最终结果

### 4.1 评估 DTO 与模型适配器

修改 `src/jobpicky/contracts/`、`src/jobpicky/ports.py` 并新增 `src/jobpicky/infrastructure/llm_evaluator.py`：

- 定义严格的评估响应 wrapper，字段仅为 `assessments`；每个 assessment 使用现有 `MatchAssessment` 约束，禁止未知字段。
- 实现 `JobEvaluatorPort` 的 DashScope OpenAI-compatible 适配器，注入 provider、base URL、必填 model、API key、timeout 和 retry policy；API key 不出现在异常文本、日志、快照或结果中。
- 将 ProfileSnapshot、候选和 JobFact 映射为固定 prompt/input schema；模型输出只承载匹配判断、分数、理由、优势、缺口和证据，不承载岗位事实。
- 适配器边界负责把 provider 返回的 JSON/tool/text 统一解析为严格 DTO；任何解析、schema 或 provider 错误均转为明确的 recommendation/evaluation failure，而不是空列表。
- `validate_assessments` 改为严格一对一集合校验：assessment ID 必须与输入 candidate ID 集合完全相同，且分别拒绝未知、重复、缺失 ID。保留分数和字段合法性校验。

### 4.2 编排阶段与结果组装

修改 `src/jobpicky/orchestration/service.py`、相关辅助函数和端口类型：

- 构造器显式注入 `JobEvaluatorPort` 和版本化模型配置；不能在服务内部隐式创建真实模型，便于离线 fake 测试。
- 流程变为 `FILTER → RETRIEVE → EVALUATE → SAVE → COMPLETE`。候选为空时按既有空结果语义完成；有候选时必须完整经过评估。
- 以稳定顺序分批评估所有 `RecommendationCandidate`，任何一批失败都将运行标记为失败，不写入部分最终推荐。
- 评估完成后通过 `JobCatalogPort` 重新读取候选岗位事实，组装 `RecommendationItem(job, retrieval, assessment)`；只保留 `matched=true`，缺失 JobFact 不制造对象，并沿用当前可诊断的缺失事实告警/结果语义。
- 组装前后校验 job_id 一致性；最终 `job` 的公司、标题、JD、地点、链接、来源和事实版本都来自目录返回的 `JobFact`。不得接受模型返回的同名字段作为覆盖值。
- 修改 `RecommendationRunRecord`、结果存储的 row parser/serializer、`RecommendationOrchestratorPort.get_results` 和 API 层类型，使结果返回 `Page[RecommendationItem]`。
- 保留数据库 JSONB 列名和整体运行记录结构，更新 JSON 快照为最终推荐格式；按“开发库可重建”原则不添加旧候选结果迁移/兼容分支。
- 运行创建时保存显式 `model_config_version`；失败运行也保存版本和 `EVALUATE` 阶段错误摘要，方便定位失败时使用的模型配置。

### 4.3 错误与安全边界

- 缺少 Embedding 配置、Embedding 加载失败、缺少 evaluator model/API key 或 provider 不可用：使用现有依赖不可用错误，运行明确失败。
- 非 JSON、未知/重复/缺失 job_id、未知字段、幻觉岗位事实字段、候选与事实 ID 不一致：使用评估阶段失败错误，包含阶段、批次和可安全记录的原因，不包含敏感输入和密钥。
- 禁止把异常吞掉后返回空推荐、关键词-only 假结果或自动接受不完整评估。
- 不新增生产 worker、自动恢复、真实数据破坏性回填或 collection ingest 实现；本计划只为现有岗位数据补建 embedding，并为未来采集复用文本构造器。

## 5. 测试与验收

### 5.1 离线单元测试

- **Embedding 配置**：未注入 Embedding 或模型路径缺失时，`semantic_search` 和推荐运行均显式失败；断言不会调用 keyword-only fallback，也不会产生假向量。
- **固定 fake embedding**：使用确定性的 512 维 fake 向量测试 query 生成、维度校验、批量回填、重复回填和融合排序。
- **评估适配器**：使用 fake chat responses 覆盖合法 JSON、非法 JSON、额外/幻觉字段、未知 job_id、重复 job_id、缺失 job_id、非法分数和 provider timeout/retry；断言全部按失败路径处理。
- **组装安全性**：模型试图返回公司、标题、JD、地点、链接等字段时失败；合法 assessment 组装出的这些字段仍逐一等于重新读取的 JobFact。
- **最终结果语义**：`matched=false` 不进入 `RecommendationItem`；候选、assessment 和 JobFact ID 不一致时不保存结果；模型配置版本进入运行记录和结果快照。

### 5.2 真实数据库集成测试

在现有测试 PostgreSQL/pgvector 环境中使用真实 migration 和 SQL 查询，但仍注入 fake embedding、fake evaluator：

- 执行 `0005` 后确认 `job.embedding` 为 `vector(512)`，HNSW cosine 索引存在且可回滚。
- 写入固定向量和空向量，验证 `semantic_search` 的 cosine 排序、eligible ID 限制、null 排除、候选上限和稳定排序；该测试必须真正执行 pgvector 查询，而非用 Python 内存排序替代。
- 执行完整推荐运行，验证关键词 + 语义双路召回、批量评估、最终 `RecommendationItem` JSONB 保存、分页读取和结果快照。
- 用可重建数据库从 migration head 重建并重新回填，确认不依赖旧 `RecommendationCandidate` 结果格式。

### 5.3 测试文件调整

至少更新/新增以下测试覆盖：

- `tests/infrastructure/test_job_catalog.py`：从“语义搜索暂不可用”改为 fake embedding + 真实 vector query/依赖失败测试。
- `tests/infrastructure/test_recommendation_run.py`：使用 fake embedding/evaluator 验证数据库运行、版本和最终推荐快照。
- `tests/orchestration/test_service.py`：FakeCatalog 提供两路 hit，FakeEvaluator 覆盖成功与失败批次，断言阶段顺序和失败状态。
- `tests/test_contracts.py`、`tests/test_ports.py`：补充严格评估集合、幻觉字段、`RecommendationItem` 和 `Page[RecommendationItem]` 契约。
- 新增 backfill 测试：验证 canonical text、批量更新、维度和可重跑行为。

普通 CI 不调用真实 DashScope，也不要求联网下载 Hugging Face 模型；可另设显式手工 smoke test，在本地模型和 API 环境齐备时验证适配器连通性，输出必须脱敏。

## 6. 交付顺序

1. 先落公共配置/端口/契约和 `0005` migration，确认新库能升级、回滚和重建。
2. 实现本地 BGE 适配器、canonical text builder、回填入口和真实 pgvector `semantic_search`；先通过 fake embedding 离线测试，再接入编排器双路召回。
3. 实现 DashScope evaluator 适配器、严格结构化响应校验和有限重试；先用 fake response 覆盖全部失败矩阵。
4. 改造编排器的 `EVALUATE/SAVE` 阶段、结果存储和端口返回类型，增加最终推荐快照测试。
5. 在可重建开发数据库上执行 migration、回填、播种和完整集成测试，最后运行项目质量检查。

## 7. 验证命令与完成标准

实现完成后至少执行：

```bash
uv sync --extra dev
uv run alembic upgrade head
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

若提供测试数据库，再执行真实 PostgreSQL/pgvector 集成测试；真实 DashScope smoke test 只能显式开启并从环境读取 key。完成标准是：迁移和回填可重建、双路召回可由真实 pgvector 查询验证、未配置模型不会返回假结果、评估输出严格失败可诊断、最终结果只保存由 JobFact 支撑的 `RecommendationItem`，且版本/失败/幻觉字段/结果快照测试全部通过。

## 8. 参考资料

- [BAAI/bge-small-zh-v1.5 模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5)
- [LangChain Hugging Face Embeddings](https://docs.langchain.com/oss/python/integrations/embeddings/huggingfacehub)
- [DashScope OpenAI-compatible 兼容方式](https://help.aliyun.com/en/model-studio/compatibility-of-openai-with-dashscope)
- [DashScope Kimi API](https://help.aliyun.com/en/model-studio/kimi-api)
