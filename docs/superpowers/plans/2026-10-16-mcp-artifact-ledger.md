# MCP 产物账本实现计划

**Goal:** 将已批准的 SQLite 可信签发设计接入 MCP 与 Gateway，修复模型自造产物和漏检租户问题。
**Design:** `../specs/2026-10-16-mcp-artifact-ledger-design.md`。
**Constraints:** 当前工作区、单 worker；不提交、不部署、不动共享服务及用户构建产物。使用 writing-plans / TDD 工作流。

## 文件职责

- 新增 `zhiyuan-agent/app/gateway/artifact_store.py`：独立 SQLite 账本、原子签发与按作用域读取。
- 修改 `app/mcp_server/tools_readonly.py` / `server.py`：可信成功结果提交后返回引用，生产注入同文件 store。
- 修改 `app/gateway/service.py` / `composition.py`：装配和权威引用查询，不从事件登记。
- 修改 `app/gateway/output_validation.py`：租户、类型、版本严格匹配。
- 新增 `tests/unit/test_artifact_store.py` / `test_gateway_artifact_authority.py`，调整已有 MCP、证据流与组合测试的显式可信 fixture。
- 新增 `docs/mcp-artifact-ledger.md`，更新旧 cache 合同与交接文档。

## 执行检查表

- [x] 先写两项安全反例与持久账本测试，运行确认 RED。
- [x] 实现紧凑不可变 store；验证重开、过期代际、清理和损坏拒收 GREEN。
- [x] 测试 MCP 成功提交、失败无引用，再接入签发和装配。
- [x] Gateway 移除事件权威，按最新输出读取；覆盖重基、修复与跨回合。
- [x] 调整已有明确可信工具 fixture，执行定向与全量离线回归。
- [x] 复审安全边界、更新交接并评估拆分提交，不自动暂存。

## 验证命令

在 `zhiyuan-agent` 使用 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest`，
先运行新 unit 文件，再运行 MCP/output_validation/gateway_evidence_flow/composition，最后走已有受限网络的离线全单元包装器。
每个 RED/GREEN 结果单独记录；只把当前新跑结果用于本批完成声明。
