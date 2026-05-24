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
AGENT_DIALOG_E2E_URL=ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
AGENT_DIALOG_E2E_METRICS_OUTPUT=examples/dialog_regression_303_effect_perf_output.json \
pytest tests/e2e/test_agent_dialog_effect_perf.py -v -s
```

默认使用 `examples/dialog_regression_303_effect_perf_cases.json`，覆盖：

- 方案只读查询的结构化回复、信息丰富度和无工作台误联动。
- 院校专业组移动 preview -> confirm -> apply，要求解释专业组顺序语义和确认边界。
- 排序 preview 说明会实际改变方案/导出顺序，并进入待重新审查。
- Explore 只读职业方向承接、专业对比，不写 pending、不发工作台卡片。
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
