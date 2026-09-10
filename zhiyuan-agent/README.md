# zhiyuan-agent

智愿 AI 志愿填报系统 AI Agent，基于 Pydantic AI + FastAPI。

通过 WebSocket 与前端多轮对话，自动收集学生信息、提取意向，编排志愿方案。

## 技术栈

- Python >= 3.10
- Pydantic AI (Agent 框架)
- FastAPI + Uvicorn (WebSocket 服务)
- aiohttp (异步 HTTP 调用)
- DuckDB + Pandas (本地数据查询)
- 支持 OpenAI / Anthropic / OpenAI 兼容接口

## 开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # 填入 LLM_API_KEY 等
uvicorn app.server:app --port 8000 --reload
```

## 架构

```
app/
├── agent/              # Agent 核心
│   ├── base_agent.py   # 泛型 Agent 基类
│   ├── chat_agent.py   # 志愿填报聊天 Agent
│   ├── context.py      # RequestContext + ScoreDetail
│   └── instructions/   # System prompt 组装
├── plan/               # 方案规划
│   └── handlers/       # 各 action family handler
├── tools/              # 意向提取工具 (school/major/city intent)
├── data/               # 数据层 (history, message, school/major/city data)
├── server.py           # WebSocket 端点
├── service.py          # 会话管理 + Agent 编排
└── config.py           # 环境变量配置
skills/                 # 技能定义 (SKILL.md)
```

## WebSocket 端点

| 路径 | 协议 | 说明 |
|------|------|------|
| `/ws/chat` | V3 原生 | JSON `{tenantId, sessionId, userId, content, type}` |
| `/gaotu-assistant-agent/plus/chat/{tenant_id}/bot/{bot_id}/do` | 兼容 | 兼容前端/旧协议 |

`/ws/chat` 在 `GATEWAY_MODE=codex_readonly` 时进入 Codex 对话执行网关。普通对话消息使用
`type=chat`；确认或取消 Proposal 时使用 `conversationAction` 字段，服务端会返回
`conversationAction.result`。模型的自然语言回复不能作为执行成功依据，客户端应只根据该结构化结果更新方案状态。

## 本地会话验证

完整的隔离式 Codex 本地验证链路（Java、Rank、Agent、Web、端口和私有可重置数据源要求）见
[`../docs/codex-local-stack.md`](../docs/codex-local-stack.md)。它不使用旧的 `scripts/start-all.sh`。

启动只读 Codex 网关：

```bash
GATEWAY_MODE=codex_readonly \
CODEX_APP_SERVER_BINDING_REGISTRY_PATH=/tmp/zhiyuan-bindings.json \
uvicorn app.server:app --host 127.0.0.1 --port 18291
```

检查服务：

```bash
curl http://127.0.0.1:18291/health
```

不依赖前端时，可以使用：

```bash
.venv/bin/python scripts/local_ws_client.py \
  --url ws://127.0.0.1:18291/ws/chat \
  --tenant-id 1 \
  --session-id local-test-session \
  --user-id local-test-user \
  --message "我想了解浙江物理类本科志愿怎么筛选"
```

对当前 Proposal 的确认或取消可显式发送结构化动作：

```bash
.venv/bin/python scripts/local_ws_client.py \
  --url ws://127.0.0.1:18291/ws/chat \
  --tenant-id 1 \
  --session-id local-test-session \
  --user-id local-test-user \
  --conversation-action '{"actionType":"cancel_proposal","proposalRef":"pending-1","expectedSourceVersion":7}'
```

脚本只负责发送和展示协议消息，不替代模型理解、Gateway 校验或 Java 权威状态。动作的实际结果以服务端返回的 `conversationAction.result` 为准。
Codex Gateway 模式要求每条 `/ws/chat` 消息携带 `tenantId`；缺失时返回 `recoverable.error`，不会使用空租户继续访问后端。
`GATEWAY_MODE=codex_readonly` 不再初始化旧 Pydantic AI 模型客户端；模型认证由 Codex App Server 自己的配置负责。`legacy` 和 `codex_shadow` 仍需要 `LLM_*` 配置。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 | openai |
| `LLM_MODEL_NAME` | 模型名称 | gpt-4o |
| `LLM_API_KEY` | API 密钥 | (必填) |
| `LLM_BASE_URL` | 自定义 API 地址 | (可选) |
| `INTERNAL_SERVICE_URL` | 后端地址 | https://zhiyuan.ytell.cn |
| `RANK_SERVICE_URL` | 排序服务地址 | http://localhost:5001 |

## 测试

```bash
pip install -e ".[test]"
bash scripts/run_unit_tests.sh         # 单元测试
bash scripts/run_e2e_tests.sh          # 端到端 (需要 API Key)
bash scripts/run_tests_with_coverage.sh
```

## Docker 部署

```bash
./build-docker.sh <env> <version>   # 构建并推送
./run-docker.sh <env> <version>     # 拉��并运行 (端口 8009)
```
