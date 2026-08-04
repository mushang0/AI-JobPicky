# 飞书多维表格招聘源接入计划

## 目标

把当前固定 CSV 的校招汇总入口替换为可选的飞书多维表格入口：每天读取指定表格，筛选
2026-06-20 之后的招聘信息，只对新增或内容变化的记录执行现有链接分类、招聘网站解析和
PostgreSQL 幂等入库；CSV 入口继续保留。

本计划记录实现准备、开发边界和验收路径。离线代码、测试和真实飞书只读连通性验证均已完成；
生产 PostgreSQL 迁移和首次正式入库仍需在 Linux 服务器上执行。

## 已确认的最小改造边界

现有链路已经满足后半段需求：

    CSV read_rows()
    → SpreadsheetRow
    → run_pipeline_by_source()
    → PostgresJobCatalog.ingest()

因此：

- 不复制飞书表格，不重写现有链接分类、平台解析器和岗位入库逻辑。
- 新入口只负责 API 分页、更新时间倒序边界、字段转换、日期筛选和记录级增量判断。
- CSV 脚本保持原样，作为离线测试和故障兜底入口。
- 数据读取首版不使用 Playwright、Cookie 或飞书页面导出；仅 OAuth 首次授权会打开本机浏览器。
- 不根据一次不完整的飞书读取关闭或删除岗位；现有 PostgresJobCatalog 的安全关闭边界保持不变。
- 不新增通用 SourceRegistry、SDK 封装或队列；单一飞书来源使用一个具体适配器即可。

为避免无意义的空包，建议将适配器放在现有 collection 模块中：

    src/jobpicky/collection/feishu_bitable.py

而不是先创建只有一个实现的 collection/sources/ 抽象目录。

## 0. 开发前置：5 条记录连通性验证

用户提供的 URL 可解析为：

    app_token = 从源表 URL 的 app_token 参数复制
    table_id  = 从源表 URL 的 table 参数复制
    view_id   = 从源表 URL 的 view 参数复制

### 0.1 创建或选择飞书企业自建应用

在飞书开放平台创建企业自建应用，记录 App ID 和 App Secret，并在权限管理中开通：

- bitable:app:readonly：查看、评论和导出多维表格；
- offline_access：需要长期刷新 user_access_token 时才开通。

权限变更如要求发布应用，应先发布后再授权。用户身份权限必须明确选择
user_access_token，不能只开通应用身份权限。

### 0.2 用用户授权获取一次性测试凭证

user_access_token 不能只靠 App ID、App Secret 直接生成，必须走 OAuth 授权码流程：

1. 在应用安全设置中登记一个本地回调地址，例如 http://localhost:8787/callback。
2. 打开授权 URL，把 CLIENT_ID 和回调地址替换成自己的值：

       https://accounts.feishu.cn/open-apis/authen/v1/authorize?client_id=CLIENT_ID&redirect_uri=http%3A%2F%2Flocalhost%3A8787%2Fcallback&scope=bitable%3Aapp%3Areadonly%20offline_access&state=jobpicky-test

3. 使用本人有权查看源表的飞书账号同意授权，从回调 URL 查询参数中取得 code。
4. 用服务端请求换取 user_access_token 和 refresh_token。refresh_token 是一次性轮换凭证，
   每次刷新后必须保存响应中返回的新值，旧值立即失效。

本次手工测试可以暂时把 user_access_token 放在当前 shell 的环境变量中；不要把它、App Secret
或 refresh_token 发到对话、写入仓库、命令历史或日志。

### 0.3 先查字段，再查 5 条记录

先查字段，确认真实字段名和类型，不假设页面显示名称与 API 字段名完全一致：

    export FEISHU_USER_ACCESS_TOKEN='仅在当前 shell 临时设置'
    export FEISHU_APP_TOKEN='从源表 URL 复制'
    export FEISHU_TABLE_ID='从源表 URL 复制'
    export FEISHU_VIEW_ID='从源表 URL 复制'

    curl --fail-with-body -sS \
      -H "Authorization: Bearer $FEISHU_USER_ACCESS_TOKEN" \
      "https://open.feishu.cn/open-apis/bitable/v1/apps/$FEISHU_APP_TOKEN/tables/$FEISHU_TABLE_ID/fields?page_size=100"

再用推荐的 records/search 读取 5 条。第一次不要传 filter 或 sort，让 view_id 真正生效：

    curl --fail-with-body -sS -X POST \
      -H "Authorization: Bearer $FEISHU_USER_ACCESS_TOKEN" \
      -H 'Content-Type: application/json; charset=utf-8' \
      "https://open.feishu.cn/open-apis/bitable/v1/apps/$FEISHU_APP_TOKEN/tables/$FEISHU_TABLE_ID/records/search?page_size=5" \
      -d "{\"view_id\":\"$FEISHU_VIEW_ID\",\"automatic_fields\":true}"

验证通过的最低证据：HTTP/API 返回成功、data.items 最多 5 条、每条有稳定 record_id，且能看到
“公司名称”和“投递链接”（或字段发现后确认的等价字段）。如果返回成功但 items 为空，先检查
视图是否确实为空以及多维表格高级权限；不能把“空数据”直接当成权限成功。

若用户身份 API 失败：

1. 确认应用已发布、当前用户已安装/可使用应用、权限已选择为用户身份；
2. 确认当前用户在该多维表格中确实有查看权限；
3. 如果用户身份长期运行仍被权限策略阻断，需要源表所有者把应用加入可访问范围；当前实现不自动
   绕过权限，也不偷偷切换成另一种身份。

本次真实只读验证结果：OAuth 授权成功，字段接口返回 20 个字段，记录接口成功读取 5 条；正式
倒序扫描按 `更新时间` 读取到日期边界，共返回 891 条候选记录后停止。未输出 Token、原始响应或
记录 ID 到仓库。

## 鉴权和部署决策

### 测试与生产的选择

- 连通性测试：优先 user_access_token，它最直接验证“当前用户能否读取这张表”。
- 当前无人值守生产：使用用户 OAuth 生成的 refresh_token 文件，服务器不需要浏览器；监控过期/撤销，
  失效后在本机重新授权并替换 token 文件。未来若源表所有者允许应用协作者访问，再单独评估 tenant token。
- 不同时实现两套业务流程。数据读取器只接收一个已解析的 Bearer token，鉴权模块负责选择和刷新。

### refresh token 的保存

环境变量适合初始测试，不适合保存会轮换的 refresh_token。当前实现将 access_token 和 refresh_token
一起放在一个 owner-only 文件中，生产采用：

    JOBPICKY_FEISHU_TOKEN_FILE=/var/lib/jobpicky/feishu-token.json

文件由运行用户拥有、权限为 0600；刷新时写入同目录临时文件后使用原子替换。进程内只保存当前
user_access_token，不把 token 写入结构化日志、异常消息、采集快照或数据库状态表。

### 配置命名

遵守仓库现有 JOBPICKY_ 前缀，不新增裸 FEISHU_* 配置契约：

    JOBPICKY_FEISHU_APP_ID
    JOBPICKY_FEISHU_APP_SECRET
    JOBPICKY_FEISHU_APP_TOKEN
    JOBPICKY_FEISHU_TABLE_ID
    JOBPICKY_FEISHU_VIEW_ID
    JOBPICKY_FEISHU_SINCE_DATE=2026-06-20
    JOBPICKY_FEISHU_TOKEN_FILE
    JOBPICKY_FEISHU_LOCK_FILE

当前不提供 tenant token 配置；权限错误显式失败。

## 实施阶段

### 1. 复用现有行模型，补一个来源适配器

新增 FeishuBitableSource，使用标准库 HTTP 能力和现有解析器相同的超时/错误处理风格，不引入
新的 Feishu SDK 依赖。职责只有：

- 调用 /records/search，按 page_token 分页，单页最多 500 条；
- 正式同步显式按“更新时间”倒序；读取到 `更新时间 <= JOBPICKY_FEISHU_SINCE_DATE` 的记录后停止，
  不再继续读取更早页面。因为飞书传入 sort 后会忽略 view_id，正式同步不依赖视图的隐含排序；
- 每次请求只读取已确认的字段，首次字段发现可暂时不限制 field_names；
- 将字符串、富文本、超链接、日期毫秒值、单选/多选等转换成现有 SpreadsheetRow 语义；
- 保留 record_id 和 API 的 last_modified_time 作为来源元数据；
- 使用 record_id 做稳定身份，row_number 仅用于错误显示，绝不作为增量键；
- 本地执行 JOBPICKY_FEISHU_SINCE_DATE 过滤。首版默认严格晚于 2026-06-20 00:00:00（即从
  6 月 21 日开始）；如果业务要包含 6 月 20 日，改为 >= 前先冻结验收口径。

字段映射在 5 条记录测试后固定为显式映射，不做模糊猜列。至少确认：

    公司名称 → company_name
    投递链接 → apply_links
    更新时间/业务日期字段 → updated_at

其他 CSV 已有字段按实际表头映射；无法确认的字段保持 None，不填默认事实。投递链接的
结构化 URL、展示文本和纯文本 URL统一交给现有链接提取/分类逻辑。

对 SpreadsheetRow 只做兼容性扩展：新增可选的 feishu_record_id 和来源更新时间字段，现有
CSV 构造调用方无需改写。不要把整条原始 API 响应写进岗位 metadata。

### 2. 增加鉴权和 API 小客户端

新增 src/jobpicky/infrastructure/feishu_auth.py，只处理：

- v2 OAuth 授权码换 token 的响应解析；
- v2 refresh token 刷新；
- HTTP 错误、飞书业务 code != 0、超时和有限重试；
- refresh token 原子轮换。

不在 FastAPI 进程内启动定时刷新，也不把 OAuth 回调做成产品接口；初始授权由一次性运维步骤完成。

### 3. 增加记录级同步状态

新增 Alembic 迁移（开发时先确认 0012_recommendation_closure 仍是唯一 head）和最小状态表：

    feishu_sync_state
      app_token              text
      table_id               text
      record_id              text
      record_hash             char(64)
      last_modified_time     timestamptz nullable
      last_processed_at      timestamptz nullable
      status                  text
      last_error              text nullable
      primary key (app_token, table_id, record_id)

record_hash 是选定业务字段规范化后的 SHA-256，不包含抓取顺序和自动更新时间。处理规则：

    无状态记录                         → 处理
    hash 变化                          → 处理
    hash 未变化且上次成功/跳过           → 跳过招聘网站解析
    hash 未变化但上次失败                → 重试并覆盖错误

每条记录独立更新状态；一条记录解析失败不阻断其他记录。API 分页中途失败时本次运行不启动入库，
下一次从头重试，也不做任何历史岗位关闭。

### 4. 新增一次性采集脚本

新增：

    scripts/feishu.py

当前脚本流程：

    读取配置
    → 获取/刷新 token
    → 按更新时间倒序分页读取，直到日期边界
    → 本地日期过滤
    → 读取同步状态并选出新增/变化/待重试记录
    → 对选中记录调用现有 run_pipeline_by_source
    → 调用现有 PostgresJobCatalog.ingest
    → 按记录写成功/跳过/失败状态
    → 输出不含凭证的摘要

脚本只做一次运行，不在 FastAPI 进程里创建 scheduler。首版按变更记录处理，保证失败能精确归因；
实测确有性能瓶颈后，再考虑按来源分组批处理，不提前为此引入复杂编排。

### 5. Linux 无人值守运行

已新增一组 systemd 配置：

    deploy/systemd/jobpicky-feishu.service
    deploy/systemd/jobpicky-feishu.timer

使用 Type=oneshot + 进程锁防止同一服务器重入，定时器每日执行一次；工作目录、虚拟环境、
环境文件和 token 文件路径全部显式配置。首版只交付 systemd，不同时维护 cron 和 Docker
两套调度说明。

运维验收包括：手动执行一次、查看 journal、重启后 timer 恢复、重复启动被锁阻止、token 文件权限
正确、失败退出码非 0 且下次仍能重试。

### 6. 当前实现和测试状态

已完成：

- `src/jobpicky/infrastructure/feishu_auth.py`：本地 OAuth 回调、token 文件 0600、原子保存和
  refresh token 轮换；
- `src/jobpicky/collection/feishu_bitable.py`：字段转换、显式排序分页、日期边界和稳定 hash；
- `src/jobpicky/infrastructure/feishu_sync_state.py` 及迁移 `0013_feishu_sync_state`：记录级增量状态；
- `scripts/feishu.py`：`auth` 一次性初始化和 `sync` 无浏览器每日执行；
- `deploy/systemd/`：Linux service、timer 和环境模板；
- `tests/collection/test_feishu_bitable.py`、`tests/infrastructure/test_feishu_auth.py`、
  `tests/infrastructure/test_feishu_sync_state.py`：离线覆盖。

已完成真实飞书权限/字段映射 smoke test；尚未完成真实 PostgreSQL 上的迁移和首次同步，这两步
需要在 Linux 服务器的生产数据库和运行用户下执行。

### 7. 测试和交付检查

离线测试不访问真实飞书：

- 鉴权响应成功、业务错误、过期 token 和 refresh token 轮换；
- records/search 多页、空页、重复 page token、429/5xx 有限重试和分页失败；
- 字段类型转换、超链接、多选、日期毫秒值、缺失字段和无效日期；
- 严格日期边界和 record_hash 稳定性；
- 同 hash 跳过、变 hash 重跑、失败重试、单条失败不影响其他记录；
- 现有 CSV 入口和现有 run_pipeline_by_source 回归；
- 数据库迁移、状态表主键和部分运行不关闭历史岗位。

真实环境只保留一个明确的 smoke test，不纳入普通 CI：成功读取 5 条、确认字段映射和权限模式，
不输出完整原始响应到日志或提交到仓库。

完成代码后按仓库约定执行：

    uv run ruff check .
    uv run ruff format --check .
    uv run pytest

## 交付验收

1. 5 条记录 API 测试成功，确认使用的是用户身份还是应用身份，确认视图是否有高级权限限制。
2. 首次脚本只处理 cutoff 之后的记录；重复运行不重新访问未变化记录对应的招聘网站。
3. Feishu API 部分失败、单条解析失败和 token 刷新失败都显式记录并可在下一次重试。
4. 岗位事实仍由现有解析器和 PostgresJobCatalog 产生，模型或飞书原始字段不能替代岗位事实。
5. CSV 入口仍可独立运行，旧的离线测试不依赖网络。
6. systemd timer 可长期运行，refresh token 轮换可恢复，日志和仓库中没有密钥、Cookie、Token 或未脱敏响应。

## 暂不做

- 飞书记录删除与岗位关闭联动；
- 飞书变更事件订阅；每日全表读取已经足够前期规模，性能不足前不引入 webhook；
- 多租户、多表、动态字段映射和通用连接器；
- 自动创建飞书应用、自动安装应用或绕过访问控制；
- 浏览器登录、Cookie 保存和导出 CSV 兜底。

## 官方依据

- 获取 user_access_token：
  https://open.feishu.cn/document/authentication-management/access-token/get-user-access-token?lang=zh-CN
- 刷新 user_access_token：
  https://open.feishu.cn/document/authentication-management/access-token/refresh-user-access-token?lang=zh-CN
- 查询记录：
  https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/bitable-v1/app-table-record/search
- API 权限列表：
  https://open.feishu.cn/document/server-docs/application-scope/scope-list
