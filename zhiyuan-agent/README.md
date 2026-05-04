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
| `/ws/chat` | V3 原生 | JSON `{session_id, user_id, content, type}` |
| `/gaotu-assistant-agent/plus/chat/{tenant_id}/bot/{bot_id}/do` | 兼容 | 兼容前端/旧协议 |

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
