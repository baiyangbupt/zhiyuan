---
task: T001
verdict: ACCEPTED
reviewer: 设计会话（Claude Opus 5）
reviewed_at: 2026-09-10
note: 本任务在分派协议建立前执行，实现方未提交 REPORT.md。本文由设计会话事后补做。
---

# T001 回收判定

## 一、判定

`ACCEPTED`。

实现方声明 `BLOCKED`——任务目标（采集流式断开现场）没有达成。判定仍为通过，因为**目标没达成的原因本身就是结论**：断流现场不存在，任务的前提是错的。产出的对照数据推翻了 P0 的诊断，价值高于原定目标。

## 二、复核了什么

| 复核项 | 结果 |
|---|---|
| 交付物存在 | `.runtime/sse-capture/SUMMARY.md`，22 个 dump，符合声明 |
| 打码 | 抽查 `req-0015` 请求头为 `Authorization: Bearer s…[MASKED len=42]`，无明文 |
| 未提交 git | `git status` 中 `.codex-capture-home/`、`zhiyuan-agent/scripts/sse_capture_proxy.py` 为未跟踪，`.runtime/` 未出现 |
| 边界 | `app/`、`tests/`、`examples/`、`CLAUDE.md`、`.codex-semantic-home/` 均无改动 |
| 事实与推断分离 | 报告只列事实，未给修复建议。符合要求 |
| 核心结论可独立复现 | 是，见下 |

独立复现：对 `app.gateway.service.TURN_OUTPUT_SCHEMA` 做结构扫描，得到 **24 个 `anyOf` 节点不带 `type`**，与上游报错 ``field `anyOf`: field `anyOf`: missing field `type` `` 的嵌套层级吻合（`properties.proposalRequest` → `anyOf[0].properties.targetCount`）。

## 三、采信的结论

1. **DeepSeek `/responses` 没有流式断开问题。** S3b 对照实验是决定性的：同一复杂场景、同一上下文与 MCP 工具，仅替换 schema，3/3 `status=completed`，7 条流最长 9.736s / 691 chunk，全部以 `response.completed` + `CLEAN_EOF` 收尾。

2. **真正的阻塞是 schema 被上游拒绝，请求从未进入流式阶段。** 10 次协议运行 + 1 次不经代理的直连对照，全部在 60–400ms 内返回 HTTP 400，逐字相同。

3. **上游有两条独立的 schema 约束**：
   - ``anyOf`` 节点必须带 `type`（10 次协议运行的报错）
   - `required` 必须覆盖对象的全部 `properties`（S3 探测的报错：`Required properties must match all properties in the object`）

   已核实：`TURN_OUTPUT_SCHEMA` **当前已满足第二条**（`required` 未覆盖全部 properties 的对象数 = 0）。S3 那次报错来自实现方自拟的 schema，不是我们的。修复时不得让这一条退化。

4. 代理 watcher 的跨 chunk 事件切分缺陷已被实现方自行发现、修复并重跑对照（`req-0011` 两个版本）。主动披露自身工具缺陷，可信度加分。

## 四、不采信 / 需要修正的既有记载

`docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md` 第二章 P0 的定性——「复杂回合中流在 `response.completed` 前断开，连续重试 5 次后失败」——**不成立**。同章的构建步骤 `cargo build -p codex-responses-api-proxy` 亦不可执行（系统 cargo 1.72.1，codex-rs 要求 1.95.0 + edition 2024，无 rustup）。两处均已改写。

## 五、产出的后续任务

- **T003**：使 `TURN_OUTPUT_SCHEMA` 通过 DeepSeek 校验并跑通复杂回合。
