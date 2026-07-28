# AI JobPicky 协作说明

> 本文件与 `CLAUDE.md` **功能一致、互为补充**：本文件写协作约束，`CLAUDE.md` 补充
> Claude Code 的常用命令与架构导览。**Agent 开始工作前必须两份都读**，以两份文档中
> 更严格的约束为准。

修改前依次阅读：

1. `docs/requirements.md`：产品范围与验收。
2. `docs/architecture.md`：公共契约与架构不变量。
3. `docs/development.md`：实现、验证与交付规则。

基本约束：

- 保持模块化单体，不提前拆微服务。
- 公共 DTO 放在 `src/jobpicky/contracts/`，公共端口放在 `src/jobpicky/ports.py`。
- 业务模块不得绕过端口读取其他模块的私有存储。
- 不完整采集不得关闭历史岗位；模型输出不得成为岗位事实。
- 未实现能力不要创建返回假数据的占位接口。
- 不提交密钥、Cookie、Token、真实简历或未脱敏响应。
- **推送到远端（`git push`、创建远端分支、开 PR）必须先得到用户的明确授权**，不得凭惯性执行。

提交前运行：

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```
