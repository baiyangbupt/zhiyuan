# 端到端测试说明

## 什么是端到端测试？

`tests/e2e/` 目录下的测试会**真正调用 LLM API**，不使用 mock。

## 运行前准备

1. **创建 .env 文件**：
```bash
cp .env.example .env
```

2. **填入真实的 API key**：
```bash
# 编辑 .env 文件
LLM_PROVIDER=openai  # 或 anthropic / openai_compatible
LLM_MODEL_NAME=gpt-4o
LLM_API_KEY=sk-your-real-key-here
LLM_BASE_URL=  # openai_compatible 需要填写
```

## 运行端到端测试

```bash
# 激活虚拟环境
source .venv/bin/activate

# 仅运行 e2e 测试
pytest tests/e2e/ -v -s -m e2e

# 或运行所有测试（包括单元测试 + e2e）
pytest -v -s
```

## Agent 对话效果与性能 smoke

该测试会通过兼容 WebSocket 访问本地 Agent，并可能触发真实大模型调用。默认跳过，需要显式打开：

```bash
RUN_AGENT_DIALOG_E2E=1 \
AGENT_DIALOG_E2E_URL=ws://127.0.0.1:18291/gaotu-assistant-agent/plus/chat/1/bot/test/do \
AGENT_DIALOG_E2E_METRICS_OUTPUT=examples/dialog_regression_303_effect_perf_output.json \
pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s
```

3.2.0 本地回归调试统一使用隔离端口：Agent `18291`、Backend `18290`、Rank `18292`、Web `3201`。如果需要覆盖默认地址，保证 Agent 启动时的 `INTERNAL_SERVICE_URL` 与回归命令里的后端地址一致，避免连到已有测试环境后读到错误方案状态。

3.2.0 的对话回归区分 evidence 与 workspace mutation：只读方案查询、只读审查、readonly while pending 和 unsupported no-op 不应产生 `planningWorkspaceAction`；只有真实 apply、post-apply readback 或确认卡相关 preview 才应断言 workspace refresh。

3.2.0 的语义回归应断言结构化路由，不断言中文措辞命中：pending 后只读/影响查询、采纳后再查询、采纳后生成方案、新诉求与 active pending 冲突、只读 PlanQuery 和 intent hard cut，均应通过 `turnObservability.routeDecision`、`sideEffect/scenario`、`TurnDecision -> PendingTurn compiler`、`PlanQueryProfile/PlanQuery DSL` 或 action DSL 验证。协议级短确认/取消可以保留固定短语测试，但业务语义不应依赖用户原话字符串。

如果 case 依赖 backend fixture，`cloneBackendStateFromSessionId` 的 clone/clear 失败会作为 environment failure 跳过 WebSocket 步骤；声明需要源 active pending 的 fixture 会连同 `pendingConfirmation/planEditCache` 克隆，只有源 pending 为 active 时才跳过 per-case pending clear，避免脏 pending 伪造回归结果。

默认使用 `examples/dialog_regression_303_effect_perf_cases.json`，覆盖：

- 方案只读查询的结构化回复、信息丰富度和无工作台误联动。
- 院校专业组移动 preview -> confirm -> apply，要求解释专业组顺序语义和确认边界。
- 排序 preview 说明会实际改变方案/导出顺序，并进入待重新审查。
- Explore 只读职业方向承接、专业对比，不写 pending、不发工作台卡片。
- 排序 preview 后用户明确“先不要改方案”的只读分析会清掉旧 pending，后续“确认”不能误执行旧排序。
- 无 pending 确认的快速保护。

`--metrics-output` / `AGENT_DIALOG_E2E_METRICS_OUTPUT` 会输出每步耗时、消息数，以及从本地 SQLite 历史解析出的 `turnObservability`：包含本轮 tool call、`actionFamily`、`resultKind`、`stage`、`applied` 等字段，便于定位慢点是模型路由、工具执行还是动作预览。默认读取 `data/chat_history.db`，可用 `AGENT_DIALOG_E2E_HISTORY_DB` 指定其他历史库。

如果怀疑历史会话污染，保持默认 `AGENT_DIALOG_E2E_CLEAR_HISTORY=1`；它只清理 Agent 本地 SQLite 对话历史，不会复制或修改后端方案数据。方案编辑类样例仍需要使用真实存在且有方案数据的 `sessionId`。

## 测试用例

- `test_real_llm_simple_query` — 简单问答（1+1=?）
- `test_real_llm_with_tool` — 工具调用（天气查询）
- `test_real_llm_multi_turn` — 多轮对话（记住名字）
- `test_real_llm_with_hooks` — 子类钩子（日志记录）
- `test_real_llm_provider_switch` — 切换 provider

## 注意事项

⚠️ **这些测试会产生真实的 API 调用费用**

- 如果没有 .env 文件或 API key 无效，测试会自动跳过
- 建议使用便宜的模型进行测试（如 gpt-4o-mini）
