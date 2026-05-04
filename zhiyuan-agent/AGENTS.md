# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

AI 高考志愿填报后端服务（gaotu-zy-agent-v3）。学生通过问答与 AI Agent 交互，AI 收集个人信息后给出志愿填报建议。基于 Pydantic AI 框架构建。

## 技术栈

- Python >= 3.10
- Pydantic AI (`pydantic-ai-slim[openai,anthropic]`) — Agent 框架
- `pydantic-ai-skills` — 技能按需加载
- `pydantic-settings` — 环境变量配置
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

# 运行演示
python examples/demo_agent.py
```

## 架构

### 核心层次

1. **LLMConfig** (`app/config.py`) — 从 `LLM_` 前缀环境变量加载配置，支持 openai / anthropic / openai_compatible 三种 provider
2. **LLMClient** (`app/llm/client.py`) — 根据 LLMConfig 创建对应的 Pydantic AI Model 实例，通过 `match provider` 分发
3. **BaseAgent[T]** (`app/agent/base_agent.py`) — 泛型 Agent 基类，使用 `agent.iter()` + while 循环手动迭代节点，支持：
   - `tools` 参数传入普通工具
   - `skill_dirs` 参数传入技能目录，自动创建 `SkillsToolset` 并注入 instructions
   - `on_node()` / `on_complete()` 钩子供子类覆写（日志、推送等）
   - `message_history` 支持多轮对话

### Skills 机制

技能定义在 `skills/` 目录下，每个技能是一个子目录 + `SKILL.md` 文件（含 YAML frontmatter）。Agent 运行时通过 `pydantic-ai-skills` 的 `SkillsToolset` 按需发现和加载技能。

## docs 目录

- `docs/plan/1.init_plan.md` — 基础架构搭建计划，包含完整的项目结构设计、各模块实现细节和关键 import 路径

## 开发约定

- 新建 Agent 时继承 `BaseAgent[T]`，通过泛型参数指定输出类型
- 新增技能放在 `skills/<skill-name>/SKILL.md`
- 环境变量统一使用 `LLM_` 前缀
- 关键依赖的 import 路径：`pydantic_ai.models.openai.OpenAIChatModel`、`pydantic_ai.providers.openai.OpenAIProvider`、`pydantic_graph.End`、`pydantic_ai_skills.SkillsToolset`
