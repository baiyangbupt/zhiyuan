# Issue: 大模型效果与性能 Benchmark 修复设计

> Status: Implemented initial runner
> Scope: 真实端到端志愿规划场景、Agent WebSocket 性能、模型直连接口定位
> Created: 2026-05-06

## 1. 背景

当前 agent 使用 OpenAI-compatible 方式接入硅基流动模型。用户体感慢可能来自三类环节：

- 模型接口本身慢：首包慢、总生成慢、长尾波动大。
- agent 多轮工具调用慢：一次用户问题会触发多次模型请求和后端 planning 工具。
- 后端/工作台数据慢：成绩、画像、planningState、候选/方案/审查接口耗时高。

本 issue 的修复目标不是只做一个模型 ping 工具，而是建立能覆盖当前产品真实链路的 benchmark：同一批 provider/API key 在相同志愿规划会话里完成相同问题，比较最终用户看到的效果、卡片联动和等待时间。

## 2. 修复目标

- 以端到端 Agent 场景作为主 benchmark，覆盖会话创建/发送、thinking、最终文本、followup 卡片和断言。
- 保留模型直连接口测试，用来区分“供应商接口慢”和“Agent/后端链路慢”。
- 支持多个 OpenAI-compatible provider 配置，但不把真实 API Key 写入仓库。
- 输出 JSON 结果，便于后续做供应商横向对比和历史回归。
- 默认用例只覆盖低副作用场景，避免反复 benchmark 改乱已有方案状态。

## 3. 端到端场景

默认用例文件：

```text
examples/model_provider_benchmark_e2e_cases.json
```

覆盖当前最需要验证的产品场景：

- “看看现在的方案”：检查回复是否结构化、是否包含冲稳保、是否没有 `@1` / `payload` 等内部格式、是否不发送无联动工作台卡片。
- “帮我审查一下”：检查审查/风险表达，并要求发送 `review` 工作台卡片。
- “候选里有没有计算机类机会”：检查候选查询链路和关键词结果。
- “这版方案怎么调更稳一点”：检查优化建议是否可读、可执行。
- “无方案状态查询”：检查没有正式方案时不伪造保底和已生成结论。

这些场景通过现有兼容 WebSocket 入口运行：

```text
/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do
```

每一步记录：

- 首条消息耗时：通常是 `thinking`，表示用户看到“正在处理”的时间。
- 最终回复耗时：收到 `end=true` 的时间。
- thinking 内容列表：判断是否可理解。
- followup 卡片数量和目标。
- 回复长度、错误类型、超时情况。
- 场景断言：`assertContains`、`assertContainsAny`、`assertNotContains`、`assertFollowupTarget`、`assertFollowupRefresh`、`assertFollowupCount`。

## 4. 模型直连定位

直连测试对每个 provider/model 执行相同 prompt：

- non-stream 总耗时：普通 `/chat/completions` 完成时间。
- stream 首包耗时：`stream=true` 第一段返回时间。
- stream 总耗时：完整流式输出完成时间。
- HTTP 状态、输出长度、错误信息。

它只用于定位 provider 网络、模型调度、首 token 和解码速度，不替代端到端效果判断。

## 5. Provider 配置

不提交真实 API Key。配置文件只写环境变量名：

```json
{
  "providers": [
    {
      "name": "siliconflow-kimi",
      "provider": "openai_compatible",
      "model": "Pro/moonshotai/Kimi-K2.6",
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key_env": "SILICONFLOW_API_KEY"
    }
  ]
}
```

本地运行前设置：

```bash
export SILICONFLOW_API_KEY="..."
```

## 6. 运行方式

### 6.1 端到端场景 benchmark

```bash
.venv/bin/python examples/model_provider_benchmark.py \
  --config examples/model_provider_benchmark.providers.example.json \
  --agent-only \
  --cases examples/model_provider_benchmark_e2e_cases.json \
  --agent-url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --output examples/model_provider_benchmark_results.json
```

### 6.2 为每个 provider 单独启动 agent

要求 server/rank/mysql/redis 已运行。脚本会为每个 provider 单独启动一个 agent 进程，避免不同 provider 互相污染。

```bash
.venv/bin/python examples/model_provider_benchmark.py \
  --config examples/model_provider_benchmark.providers.example.json \
  --cases examples/model_provider_benchmark_e2e_cases.json \
  --start-agent \
  --agent-port 8100 \
  --output examples/model_provider_benchmark_results.json
```

### 6.3 仅测模型直连

```bash
.venv/bin/python examples/model_provider_benchmark.py \
  --config examples/model_provider_benchmark.providers.example.json \
  --direct-only \
  --output examples/model_provider_benchmark_results.json
```

## 7. 结果判断口径

建议至少跑 3 轮，重点看：

- 直连 stream 首包：是否能稳定低于 2 秒。
- 直连 non-stream 总耗时：短回答是否稳定低于 5 秒。
- agent 首条 thinking：用户是否能在 1-3 秒内看到处理反馈。
- agent 最终回复：简单状态查询是否低于 20 秒，方案审查/调整类是否低于 60 秒。
- 超时率：105 秒服务层超时必须重点标记。
- 效果断言失败率：性能更快但断言失败不能直接替换。

## 8. 当前初步观察

对当前硅基流动 `Pro/moonshotai/Kimi-K2.6` 做最小请求压测：

- non-stream 总耗时约 7.6-8.3 秒。
- stream 首包约 0.7-2.3 秒。
- stream 总耗时波动较大，出现过 65 秒长尾。

这说明接口侧本身存在明显延迟和长尾；同时当前 agent 最终回复不是 token 级流式下发，用户仍需等待完整 agent 循环完成。因此只换云端接口可能改善模型等待，但还需要结合 agent 场景跑完整 benchmark 才能确认收益。
