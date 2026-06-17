# Release 3.1.0 Dialog Auto Explorer

本文记录 3.1.0 对话层自动探索验证方案。目标是减少纯人工浏览器验证成本，用脚本从后端/Agent 侧批量模拟真实用户对话，发现问题后按批次修复。

## 1. 目标

- 支持复用已有 `chatSessionId` 跑对话回归。
- 支持在具备 `tk/pf` 和创建 payload 时，从创建会话开始跑完整链路。
- 使用 LLM 模拟用户持续追问，覆盖方案概览、候选筛选、审查修复、数据更新、专业组说明等场景。
- 自动收集 websocket 错误、空回复、内部字段泄露、强制选择话术、用户可见系统错误、超时和重复回复。
- 可选使用 LLM judge 对每轮回复做质量标注，输出 JSON 和 Markdown 报告。

## 2. 工具入口

脚本位置：

```bash
zhiyuan-agent/examples/dialog_auto_explorer.py
```

默认场景：

```bash
zhiyuan-agent/examples/dialog_auto_explorer_scenarios.json
```

默认报告输出目录：

```bash
/tmp/zhiyuan-dialog-auto-explorer
```

## 3. 推荐运行方式

### 3.1 先用已有会话跑固定种子对话

不调用 LLM 生成后续追问，只验证场景种子问题和基础问题检测：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
./.venv/bin/python examples/dialog_auto_explorer.py   --session-id 115   --agent-url ws://127.0.0.1:18091/gaotu-assistant-agent/plus/chat/1/bot/test/do   --backend-url http://127.0.0.1:18090   --disable-llm-user   --clear-history   --clear-backend-pending
```

### 3.2 使用 LLM 自动续聊

需要 `.env` 或环境变量中存在 `LLM_PROVIDER/LLM_MODEL_NAME/LLM_BASE_URL/LLM_API_KEY`：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
./.venv/bin/python examples/dialog_auto_explorer.py   --session-id 115   --agent-url ws://127.0.0.1:18091/gaotu-assistant-agent/plus/chat/1/bot/test/do   --backend-url http://127.0.0.1:18090   --max-turns 6   --extra-turns-after-issue 2   --llm-judge   --clear-history   --clear-backend-pending
```

停止规则：

- 每个场景最多 `--max-turns` 轮。
- 出现首个问题后，默认再多聊 `--extra-turns-after-issue=2` 轮，观察问题是否持续或扩散。
- 如果 LLM 模拟用户认为场景已经充分覆盖且没有问题，可以提前停止。

### 3.3 从创建会话开始跑

具备主站测试登录态时，传入 `tk/pf` 和创建 payload：

```bash
cd /root/dev/zhiyuan/zhiyuan-agent
./.venv/bin/python examples/dialog_auto_explorer.py   --create-session-payload /path/to/integration-create-session.json   --create-mode integration   --tk '<loginToken>'   --pf WEB   --backend-url http://127.0.0.1:18090   --agent-url ws://127.0.0.1:18091/gaotu-assistant-agent/plus/chat/1/bot/test/do   --max-turns 6   --llm-judge
```

约束：

- 默认不会创建新会话；必须显式传 `--create-session-payload`。
- 如果创建的是 `VOLUNTEER`，仍会走真实权益限制和每日次数限制。
- 报告不提交到仓库，避免泄露真实学生信息或 LLM 对话内容。

## 4. 默认覆盖场景

- `overview-to-plan-review`：当前方案概览、冲稳保、风险审查、只读边界。
- `candidate-filter-and-refresh`：候选筛选、地域/专业偏好、候选不足边界。
- `review-repair-preview-confirm`：审查修复建议、替换预览、确认前不落地。
- `data-freshness-volunteer`：3.1.0 数据更新提示、候选刷新和审查动作边界。
- `major-group-count-and-plan-detail`：专业组总专业数与方案已选专业数的解释边界。

可以只跑单个场景：

```bash
./.venv/bin/python examples/dialog_auto_explorer.py   --session-id 115   --scenario data-freshness-volunteer   --disable-llm-user
```

## 5. 问题收集口径

硬规则自动检测：

- websocket error 或请求异常。
- 空回复。
- `payload/action_family/volunteerId/pending_*` 等内部字段泄露。
- `服务器异常/系统错误/当前权益不足` 等用户可见错误。
- 强制选择或内部补偿预览等已知坏话术。
- 超时、过短回复、连续重复回复。

LLM judge 可选检测：

- 答非所问。
- 与工作区状态矛盾。
- 动作边界不清，例如未确认就声称已修改。
- 对候选不足、数据更新、专业组数量的解释不准确。

## 6. 后续批处理流程

1. 先跑 `--disable-llm-user`，确认基础链路稳定。
2. 再打开 LLM 自动续聊和 `--llm-judge`，收集一批问题报告。
3. 按报告中的 `error` 优先级修复后端/Agent/前端文案或工具链。
4. 将确认有价值的失败对话沉淀为固定 `dialog_regression_*_cases.json`，进入稳定回归集。
5. 每批修复后重新跑同一场景，确认问题消失且没有新增回归。
