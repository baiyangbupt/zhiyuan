# 对话质量门禁的数据前置检查

单元测试只检查回归样例的结构、数值会话标识和预检器本身，不再要求开发机拥有私有志愿数据。缺少私有数据不代表真实对话/动作回归已通过。

## 只读预检

在 `zhiyuan-agent` 目录运行：

```bash
.venv/bin/python examples/dialog_quality_gate.py --check-fixtures --mode final-action --backend-volunteer-data-dir /path/to/authorized/fixtures
```

- 不带 `--execute`，也不会启动子进程、调用模型、连接数据库或运行回放。
- 按所选 runner 的样例及 defaults/case 覆盖，检查显式 `cloneBackendStateFromSessionId` 对应的 `session_volunteer_<id>.json` 可读且为合法 JSON。
- 缺失或无效时退出码为 2，逐条打印样例名和文件位置。当前工作区 final-action 包缺 94 条引用对应的数据，必须通过授权脱敏资产准备，禁止伪造空文件来换取绿色。
- `--backend-volunteer-data-dir` 同时传给实际 runner，须与隔离 Java 后端的数据目录一致。
- 不传目录时沿用 runner 的 `ZHIYUAN_REGRESSION_VOLUNTEER_DATA_DIR`，再回退到仓库 `zhiyuan-server/data/tmp`。

## 执行门禁

质量 gate 在任何已选命令执行前自动做同一预检；即使指定 `--no-stop-on-failure`，前置检查失败仍整体阻止执行。`--execute --mode local` 不依赖私有夹具。

这不是业务数据完整性或可执行性的证明：JSON 通过后，runner 仍校验克隆、待确认状态、实际动作和后端结果。当前预检只覆盖显式克隆来源，不代替动态会话偏移、远程数据库来源及运行时生成状态的检查。

真实 live/final-action 门禁会写隔离会话并可能调用付费模型，只能在单独授权窗口执行，不能把预检命令改成 `--execute` 当作普通离线测试。
