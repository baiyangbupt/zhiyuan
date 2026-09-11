# 任务台账

> 状态唯一来源。协议见 `README.md`。
> 状态流：`DISPATCHED` → `REPORTED` → `ACCEPTED` / `ACCEPTED_WITH_FOLLOWUP` / `REJECTED` / `SUPERSEDED`

| ID | 标题 | 来源 | 执行会话 | 派发 | 实现方状态 | 评审判定 | 产出后续 |
|---|---|---|---|---|---|---|---|
| [T001](T001-sse-capture/) | 采集 DeepSeek `/responses` 流式断开现场 | 修订计划 P0 | deepseek | 2026-09-10 | `BLOCKED` | `ACCEPTED` | T003 |
| [T002](T002-drop-resolver/) | 清理悬空 resolver 模块并修正过时文档 | 修订计划 P4 | deepseek | 2026-09-10 | 未按格式提交 | `ACCEPTED_WITH_FOLLOWUP` | T004 |
| [T003](T003-schema-compat/) | 使 `TURN_OUTPUT_SCHEMA` 通过 DeepSeek 校验并跑通复杂回合 | T001 结论 | deepseek | 2026-09-10 | `DONE` | `ACCEPTED` | T005 |
| [T005](T005-mcp-execution/) | 让只读 MCP 工具真正执行，并修好语义冒烟的观测仪表 | T003 REVIEW 勘误 | deepseek | 2026-09-10 | `DONE` | `ACCEPTED_WITH_FOLLOWUP` | T008 |
| [T006](T006-registry-unblock/) | 把本地基础设施 compose 指向可达镜像源，解除 P2 前置 | 修订计划 P2 | deepseek | 2026-09-10（口头） | `DONE` | `ACCEPTED` | — |
| [T007](T007-agent-doc-accuracy/) | 修正 `zhiyuan-agent/CLAUDE.md` 的 Tools 一节 | T003 REVIEW 勘误 2 | deepseek | 2026-09-10（口头） | `DONE` | `ACCEPTED` | P5 文档收尾 |
| [P1a](P1a-evidence-ledger/) | Java 证据台账：建表、摘要、签发、四态核验 | 修订计划 P1 切片 | deepseek | 2026-09-10 | `DONE_WITH_CONCERNS` | `ACCEPTED_WITH_FOLLOWUP` | P1b |
| [T008](T008-output-extraction/) | 让 harness 取得到散文包裹的 JSON，并让取不到变成显式失败 | T005 REVIEW 第四节 2 | 未派发 | — | — | — | — |

## 本轮复核的两条结论（影响后续排期）

1. **P0 仍未清零。** 判定 T005 时独立重跑 `reference-complete-history` 8 次得 7 过 1 挂，挂的那次是模型先写散文再补围栏 JSON、harness 取不到 output；`mixed-read-write` 基线 0/3。P0 的验收条（两个复杂场景各连续 3 次 `evaluation.passed == true`）两项都还没满足。解析层转 T008，写操作契约层留 P2。
2. **P1a 建成的机器还没接进产线。** 生产取数路径（`GaotuService.java:603/617`）走的是不带 scope 的重载，等价于不签发；唯一会签发的调用方是 inner 下的 debug controller。另有两项上游契约假设（`dataVersion` 字段是否真实存在、版本是否随查询参数变化）必须用一次真实上游调用定下来，**不能继续在替身上验证**。这三条都是 P1b 派发的前置。

   **更新（2026-09-11）：后两项已实测结案**（`plans/2026-09-11-P1a上游版本契约实测与dataVersion改设计.md`）。结果是最坏的一种——**真实上游根本不返回 `dataVersion`**，照原设计落地则生产上一条证据都签不出来。改为 Java 对 `data` 子对象算内容摘要，版本表键定死为 `(source_system, params_digest)`。**P1b 现在可派发**，剩下的第一项（接会话上下文到生产取数路径）是 P1b 自身的工作，不是前置。

   这条留下一条方法论，已补进 `README.md` 第六节：**替身能证明代码按设计工作，不能证明设计与外部世界相符。** P1a 在替身上九步验收全绿，验的却是一个设计会话编出来的契约。

## 已闭环的待办

- **T004**：`zhiyuan-agent/CLAUDE.md` 残留的 `ChatAgent` 引用（T002 漏网项），已由设计会话在 2026-09-10 直接修复。

## 说明

T001 / T002 在本协议建立前派发，因此没有 `REPORT.md`——这正是建立协议的直接原因。两者的 `REVIEW.md` 由设计会话事后补做，判定依据是自行重跑验收，不依赖实现方的聊天转述。

T003 判定维持 `ACCEPTED`（schema 归一化本身经独立复核成立），但它的**验收条件由设计会话写错**：`status=completed` 量不出场景是否跑通。勘误见 `T003-schema-compat/REVIEW.md` 末尾，由此产生的规则见 `README.md` 规则 4，遗留工作转 T005。

T006 / T007 由设计会话口头派发，没有 `TASK.md`——这是设计会话的欠账，不计入实现方偏离。规则已补进 `README.md` 第七节「口头派发的任务怎么判边界」。

P1a 的 ID 不走 `T0NN` 序列，因为它是修订计划 P1 的切片（P1a/P1b/P1c），归属关系比流水号更重要。切片与 `T0NN` 共用同一套状态词和复核流程。

