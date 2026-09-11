# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI 高考志愿填报后端服务（gaotu-zy-agent-v3）。学生通过 WebSocket 与 AI Agent 多轮对话，AI 收集个人信息（成绩、选科、意向院校/专业/城市等）后给出志愿填报建议。基于 Pydantic AI 框架构建，FastAPI 提供 WebSocket 接口。

## 技术栈

- Python >= 3.10
- Pydantic AI (`pydantic-ai-slim[openai,anthropic]`) — Agent 框架
- `pydantic-ai-skills` — 技能按需加载（当前仅 `examples/demo_agent.py` 使用，生产 `ZhiyuanAgent` 未启用 `skill_dirs`，详见「Skills 机制」）
- `pydantic-settings` — 环境变量配置
- FastAPI + Uvicorn — WebSocket 服务
- SQLite — 会话历史持久化
- aiohttp — 内部服务 HTTP 调用
- Logfire — 可观测性/instrumentation
- LLM 支持：OpenAI、Anthropic、OpenAI 兼容接口

## 常用命令

```bash
# 创建虚拟环境并激活
python3 -m venv .venv
source .venv/bin/activate

# 安装
pip install -e .

# 配置环境变量
cp .env.example .env  # 然后填入 LLM_API_KEY 等

# 启动服务
bash start_local.sh
# 或手动: uvicorn app.server:app --reload

# 运行演示
python examples/demo_agent.py

# 测试
pip install -e ".[test]"
bash scripts/run_unit_tests.sh       # 单元测试
bash scripts/run_e2e_tests.sh        # 端到端测试（需要真实 API key）
bash scripts/run_all_tests.sh        # 全部测试
bash scripts/run_tests_with_coverage.sh  # 带覆盖率

# Docker
bash build-docker.sh
bash run-docker.sh
```

## 架构

### 核心层次

1. **LLMConfig** (`app/config.py`) — 从 `LLM_` 前缀环境变量加载配置，支持 openai / anthropic / openai_compatible 三种 provider。同文件还包含 `LogfireConfig`（`LOGFIRE_` 前缀）、`InternalServiceConfig`（`INTERNAL_SERVICE_` 前缀）、`ExtractConfig`（`EXTRACT_` 前缀）、`HistoryConfig`（`HISTORY_` 前缀）
2. **LLMClient** (`app/llm/client.py`) — 根据 LLMConfig 创建对应的 Pydantic AI Model 实例，通过 `match provider` 分发；同时提供 `configure_logfire()` 配置可观测性
3. **BaseAgent[T]** (`app/agent/base_agent.py`) — 泛型 Agent 基类，使用 `agent.iter()` + while 循环手动迭代节点，支持：
   - `tools` 参数传入普通工具
   - `skill_dirs` 参数传入技能目录，自动创建 `SkillsToolset` 并注入 instructions
   - `on_node()` / `on_complete()` 钩子供子类覆写（日志、推送等）
   - `message_history` 支持多轮对话
   - `run_with_message_deltas()` 返回 (output, new_messages, all_messages) 三元组
4. **ChatService** (`app/service.py`) — 会话管理 + Agent 编排层，负责加载/保存历史、获取成绩详情、构建 RequestContext
5. **FastAPI Server** (`app/server.py`) — WebSocket 端点 `/ws/chat`，处理消息收发和错误

### 请求上下文

- **RequestContext** (`app/agent/context.py`) — 请求上下文 dataclass，包含 userid、sessionid、chat_history、batch（本科/专科）、score_detail
- **ScoreDetail** (`app/agent/context.py`) — 学生高考成绩详情 dataclass（province、total_score、subject_list、sex）

### 数据层

- **ChatHistoryStore** (`app/data/history_store.py`) — SQLite 持久化 pydantic-ai 消息历史，按 session_id 存取
- **history_codec** (`app/data/history_codec.py`) — 消息序列化/反序列化
- **MessageStore** (`app/data/message_store.py`) — 通过内部 HTTP 接口持久化前端可见的 WebSocket 消息（用户消息和 Agent 回复）
- **message_utils** (`app/data/message_utils.py`) — pydantic-ai 消息到 dict 的转换工具
- **school_data / major_data / city_data** (`app/data/`) — 院校、专业、城市静态数据

### Tools（`app/tools/`）

`app/tools/` 下现有 20 个模块：

- 意向抽取：`school_intent_tool.py`、`major_intent_tool.py`（含负面意向）、`city_intent_tool.py`（含负面意向）、`career_intent_tool.py`
- 分数与建议：`score_query_tool.py`、`major_recommend_tool.py`、`admission_policy_tool.py`、`admission_fit_match_tool.py`
- 方案与校验：`plan_validation_tool.py`、`plan_orchestration_models.py`、`plan_goal_resolution.py`
- 探索与多轮状态：`explore_direction_tool.py`、`explore_followup_tool.py`、`intent_state_tool.py`、`intent_relation_tool.py`、`intent_response_tool.py`
- 共享/基础设施：`candidate_filter_extraction_tool.py`、`extraction_json.py`、`review_issue_registry.py`
- 示例：`example_context_tool.py`

Release 4.0 实际注册到 `ZhiyuanAgent` 的工具定义在 `app/zhiyuan_agent/tools.py`：`acknowledge_readonly`、`answer_policy`、`clarify_request`、`compare_entities`、`confirm_pending`、`discover_options`、`explore_topic`、`preview_intent_change`、`preview_plan_change`、`preview_plan_action`、`query_plan`、`read_state`、`respond_casual`、`review_plan`。在 `app/` 内（`app/tools/` 以外）目前只有 `app/service.py` 与 `app/zhiyuan_agent/tools.py` 引用 `app/tools/` 下的模块，其余引用来自测试。

### Schemas

- `app/schemas/ws.py` — WSMessage、WSResponse WebSocket 消息模型
- `app/schemas/school_intent.py` / `major_intent.py` / `city_intent.py` — 各意向结构化 schema
- `app/schemas/user_profile.py` — 用户画像 schema

### Skills 机制

技能定义在 `skills/` 目录下，共 7 个 `skills/<skill-name>/SKILL.md`（`intake_chat`、`intent_detect`、`explore_chat`、`plan_chat`、`plan_query`、`score_query`、`career_path_chat`）。

注意：这 7 个技能目前**仅由 `examples/demo_agent.py` 加载**（该脚本传 `skill_dirs=["./skills"]`），生产 `ZhiyuanAgent` 未传 `skill_dirs`，因此 `pydantic-ai-skills` 的 `SkillsToolset` 在生产运行时不生效。`skills/codex/` 是给外部 codex 二进制用的独立格式（子目录各自带 `SKILL.md`，另有 `plugin.json`、`base_instructions.md` 等），不走 `SkillsToolset`。

### 工具模块

- `app/util/internal_client.py` — 内部服务 HTTP 调用封装（获取成绩详情、保存消息等）
- `app/util/code_enrichment.py` — 代码数据补充工具
- `app/services/profile_manager.py` — 用户画像管理

## 开发约定

- 新建 Agent 时继承 `BaseAgent[T]`，通过泛型参数指定输出类型
- 新增技能放在 `skills/<skill-name>/SKILL.md`
- 环境变量按功能模块分前缀：`LLM_`、`LOGFIRE_`、`INTERNAL_SERVICE_`、`EXTRACT_`、`HISTORY_`
- 关键依赖的 import 路径：`pydantic_ai.models.openai.OpenAIChatModel`、`pydantic_ai.providers.openai.OpenAIProvider`、`pydantic_ai.models.anthropic.AnthropicModel`、`pydantic_ai.providers.anthropic.AnthropicProvider`、`pydantic_graph.End`、`pydantic_ai_skills.SkillsToolset`
- 测试分层：`tests/unit/`（单元测试）、`tests/integration/`（集成测试）、`tests/e2e/`（端到端，需真实 API key，标记 `@pytest.mark.e2e`）
- pytest 配置：`asyncio_mode = "auto"`，测试目录 `tests/`
