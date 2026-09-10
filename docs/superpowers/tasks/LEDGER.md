# 任务台账

> 状态唯一来源。协议见 `README.md`。
> 状态流：`DISPATCHED` → `REPORTED` → `ACCEPTED` / `ACCEPTED_WITH_FOLLOWUP` / `REJECTED` / `SUPERSEDED`

| ID | 标题 | 来源 | 执行会话 | 派发 | 实现方状态 | 评审判定 | 产出后续 |
|---|---|---|---|---|---|---|---|
| [T001](T001-sse-capture/) | 采集 DeepSeek `/responses` 流式断开现场 | 修订计划 P0 | deepseek | 2026-09-10 | `BLOCKED` | `ACCEPTED` | T003 |
| [T002](T002-drop-resolver/) | 清理悬空 resolver 模块并修正过时文档 | 修订计划 P4 | deepseek | 2026-09-10 | 未按格式提交 | `ACCEPTED_WITH_FOLLOWUP` | T004 |
| [T003](T003-schema-compat/) | 使 `TURN_OUTPUT_SCHEMA` 通过 DeepSeek 校验并跑通复杂回合 | T001 结论 | deepseek | 2026-09-10 | `DONE` | `ACCEPTED` | P1 |

## 已闭环的待办

- **T004**：`zhiyuan-agent/CLAUDE.md` 残留的 `ChatAgent` 引用（T002 漏网项），已由设计会话在 2026-09-10 直接修复。

## 说明

T001 / T002 在本协议建立前派发，因此没有 `REPORT.md`——这正是建立协议的直接原因。两者的 `REVIEW.md` 由设计会话事后补做，判定依据是自行重跑验收，不依赖实现方的聊天转述。
