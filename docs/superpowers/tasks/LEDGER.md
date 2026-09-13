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
| [P1a](P1a-evidence-ledger/) | Java 证据台账：建表、摘要、签发、四态核验 | 修订计划 P1 切片 | deepseek | 2026-09-10 | `DONE_WITH_CONCERNS` | `ACCEPTED_WITH_FOLLOWUP` | P1b-1 / P1b-2 / P1b-3 |
| [P1b-1](P1b-1-content-digest/) | 数据版本改为 `data` 内容摘要，版本表键改 `(source_system, params_digest)` | P1a REVIEW 跟进 1/3 + 上游实测 | zhiyuan-48 | 2026-09-13 | 执行中 | — | — |
| [P1b-2](P1b-2-evidence-passthrough/) | 打通证据到 Agent 的三处断链，最后删自铸分支 | P1a REVIEW 跟进 2（归因勘误后） | zhiyuan-48 | 2026-09-13 | 排队（P1b-1 之后） | — | — |
| [P1b-3](P1b-3-snapshot-evidence/) | `fillEvidence()` 落地 + snapshot 优先于进程内存 | 设计文档 4.5 / 5.2 | zhiyuan-48 | 2026-09-13 | 排队（P1b-2 之后） | — | — |
| [P1c-1](P1c-1-validator-unblock/) | 拆掉三处恒真的证据检查，让权威证据能进校验器账本 | 断链 4/5/6 | 未派发（等 P1b-2、P1b-3 合入） | — | — | — | — |
| P1c-2 | 四态核验接入 Gateway + 第六章分流表 + 重查一次 | 设计文档 5.3 / 第六章 | 任务书未写（等 P1b 落地后定 API 形状） | — | — | — | — |
| [T008](T008-output-extraction/) | 让 harness 取得到散文包裹的 JSON，并让取不到变成显式失败 | T005 REVIEW 第四节 2 | subagent | 2026-09-13 | 执行中 | — | — |

## P1b 三片的并行关系

三份任务书都已写好，**可以同时派给三个实现方**。改动面基本不重叠：

> **实际派发（2026-09-13）：三片全部给了 `zhiyuan-48` 一个会话，要求串行做、每片单独出报告。** 只有一个实现方可用时，串行是对的——三片共出一份报告会让"哪一项没验过"变得说不出口，而那正是 P1a 的失败方式。

| 片 | 改动面 | 与其它片的重叠 |
|---|---|---|
| P1b-1 | Java：摘要工具类、`GaotuClient`、`ResponseDTO`、`EvidenceSourceVersionMapper`、V15 migration、验收脚本 | 与 P1b-2 **零重叠** |
| P1b-2 | Python：`server.py`、`tools_readonly.py`、`internal_client.py` 及其测试 | 与另两片 **零重叠** |
| P1b-3 | Java：`ConversationSnapshotService`；Python：`service.py:545` | 与 P1b-1 **同改 `EvidenceLedgerService.java`**（P1b-3 只增只读方法，P1b-1 改已有方法体），合并由设计会话处理 |

两条**验收上的**顺序依赖，已写进各自的任务书，派发时不必额外交代：

1. **P1b-2 的端到端验收在 P1b-1 合入前无法对真实上游做绿**——真实上游不返回 `dataVersion`，Java 签不出证据。所以 P1b-2 的验收明确允许用替身（它测的是 Python 管道，替身在这里是被测对象的输入，不是外部世界的证人），但**测试数据的形状必须从 Java DTO 取，不能从替身脚本抄**——替身返回 dict、真实返回数组，照替身抄就会原样复制断链 3。
2. **P1b-3 的"造 `stale`"手法依赖 `evidence_source_version` 的表结构**，而 P1b-1 正在改它的主键。任务书已要求优先写成不依赖表结构的单测。

另有一条**跨片的口径待裁决**（P1a 跟进项 4，三份任务书都写了"不要自行处理"）：`EvidenceLedgerService.verifyOne()` 只在双方 `threadId` 都非空时才校验线程，而 Agent 侧 `strict_scope=True` 要求 scope 必须存在，Java 比 Agent 松。影响面封在单会话内，不构成跨会话泄露。

**已裁决（2026-09-13）：统一到松的那边——thread 不是证据的隔离边界。** 依据不是偏好而是事实：`service.py:372` 的 `self._threads` 是纯进程内 dict、从不持久化，thread 与 session 是 1:1，**一个会随进程重启而改变的标识符不能承载安全语义**。隔离由 `(tenantId, chatSessionId)` 承担，Java 侧一直强制。P1b-3 任务书已同步更新。

## 第二簇断链：校验器会结构性拒收权威证据（2026-09-13）

裁决上面那条时顺藤查出**另外三处**，编号接 4/5/6（`plans/2026-09-13-P1c证据校验器的三处结构性拒收.md`）。三处都在 `output_validation.py` / `service.py` 这一层，**P1b 全部做完之后链路仍然不通**：

| # | 断链 | 后果 |
|---|---|---|
| 4 | `service.py:770-781` 只从本回合 turn events 建账本，snapshot 里的权威证据不进账本 | `fillEvidence()` 把证据摆到模型面前，模型引用后立刻 `evidence_not_found` |
| 5 | `output_validation.py:143` 要求证据的 `stateVersion` 等于当前 `snapshot_version` | 工作区每写入一次就推进版本 → **第 3 回合的证据在第 7 回合必然 `stale_state`**，直接否掉 P1 的头号验收目标 |
| 6 | `output_validation.py:132` 要求证据的 `threadId` 等于当前 thread，而 thread 进程易失 | **一次 Gateway 重启让所有在世会话的证据全部作废**，fail-closed 下等于每个 fact 回合全线挂 |

三处今天全看不见，原因完全一致：**证据是每回合自铸的，填的就是当前值，于是三个检查恒真、从未真正做过判定。** 这与 `mcpCalls` 恒为 `[]` 是同一类错误的两面——那次是仪表没通电，这次是校验器没通电。由此产生的第三条方法论规则已补进 `README.md` 第六节：**迁移设计时要专门去找"现在永远通过"的检查**，判别办法是问"有没有一种输入能让它失败"。

**P1c 的范围因此扩大**：账本合并 snapshot、删证据的 `stateVersion` 等值检查、删证据的 `threadId` 等值检查（**artifact 那两处同名检查保留**，产物确实绑定线程与工作区版本），三件事都必须排在四态核验接入**之前**。删检查方向上是放松，论证见设计笔记第六节：删掉的是两个恒真因而从未做过判定的检查，换上的四态核验是会真的说"不"的——**防线变强了**；反过来先接核验不删检查，则两道门都关着，`fact` 回合永远出不去。

**因此 P1c 也切两片**，仍按验证面切（同 P1b 的理由）：

| 片 | 内容 | 验证面 | 状态 |
|---|---|---|---|
| P1c-1 | 上面这三件事 | 纯 Python 单测能验完，不需要真实上游、不需要跑通端到端 | 任务书已写，等 P1b-2/P1b-3 合入后派发 |
| P1c-2 | 四态核验接入 + 第六章分流表 + 重查一次 | 需要 Java verify 端点 + 真实工具执行 | **任务书暂不写** |

P1c-2 的任务书暂不写，是有意的：它要调 `/internal/evidence/verify`，而那个端点的请求/响应形状会被 P1b-1 的 `currentDataVersion(String, String)` 改签名波及。现在写等于拿假设当事实——**这正是 P1a 栽过的那个跟头**（README 第六节第五条）。等 P1b-1 合入、形状定死，再写。

**P1c-1 合入后到 P1c-2 合入前，证据侧的拒收能力存在一个真实的中间态**（`stateVersion` / `threadId` 两维暂时不设防，会话/租户隔离、`evidence_not_found`、`dataVersion` 比对、`admission_mode` 都还在）。这是有意接受的，理由同上——但它是**真实存在的窗口，不是纸面上的**，因此 P1c-2 不应长期挂起。


## 本轮复核的两条结论（影响后续排期）

1. **P0 仍未清零。** 判定 T005 时独立重跑 `reference-complete-history` 8 次得 7 过 1 挂，挂的那次是模型先写散文再补围栏 JSON、harness 取不到 output；`mixed-read-write` 基线 0/3。P0 的验收条（两个复杂场景各连续 3 次 `evaluation.passed == true`）两项都还没满足。解析层转 T008，写操作契约层留 P2。
2. **P1a 建成的机器还没接进产线。** 生产取数路径（`GaotuService.java:603/617`）走的是不带 scope 的重载，等价于不签发；唯一会签发的调用方是 inner 下的 debug controller。另有两项上游契约假设（`dataVersion` 字段是否真实存在、版本是否随查询参数变化）必须用一次真实上游调用定下来，**不能继续在替身上验证**。这三条都是 P1b 派发的前置。

   **更新（2026-09-11）：后两项已实测结案**（`plans/2026-09-11-P1a上游版本契约实测与dataVersion改设计.md`）。结果是最坏的一种——**真实上游根本不返回 `dataVersion`**，照原设计落地则生产上一条证据都签不出来。改为 Java 对 `data` 子对象算内容摘要，版本表键定死为 `(source_system, params_digest)`。

   **同日查清第一项的归因错了**（`plans/2026-09-11-P1a证据到不了Agent的三处断链.md`）：不签发的原因不在 `GaotuService.java:603/617`（那条路 Agent 不经过），而在 Python 侧三处互相独立的断链——scope 没上路、信封被 `_data()` 拆掉、`data` 是数组而归一化只吃 dict。**P1b 现在可派发，但改动面比原估计大，重心在 Python 侧。**

   这条留下两条方法论，已补进 `README.md` 第六节：**替身能证明代码按设计工作，不能证明设计与外部世界相符**；**桩的形状要从生产者那一侧取，不要从消费者的期望那一侧编**。P1a 在替身上九步验收全绿，验的却是设计会话编出来的契约；Agent 侧三层测试都有效，缝隙全在层与层之间。

   **任务书已就位（2026-09-11）**：P1b 拆成 P1b-1 / P1b-2 / P1b-3 三份，见上表与并行关系一节。三份都可立即派发。

## 已闭环的待办

- **T004**：`zhiyuan-agent/CLAUDE.md` 残留的 `ChatAgent` 引用（T002 漏网项），已由设计会话在 2026-09-10 直接修复。

## 说明

### 两个实现方同时在一个工作树里（2026-09-13）

T008 与 P1b 系列并行执行，共用 `/root/dev/zhiyuan` 一个工作树。这是有意的——T008 在 harness/scripts 层，P1b 在 Java 与 `app/mcp_server/`、`app/util/` 层，**改动面零重叠**，串行没有收益。

代价有两条，两份任务书都已加防护：

1. **误伤风险。** 一条 `git stash` 能删掉另一方几小时的未提交工作，且不会立刻被发现。两份任务书都明令禁止一切改动工作树的 git 命令（`checkout` / `restore` / `stash` / `reset` / `clean` / `add` / `commit`），只读的 `status` / `diff` 允许。
2. **全量测试互相污染。** 一方跑 pytest 时另一方可能正在改 Python 文件。规则是：**基线以外的失败先看落在谁的面上**，不属于自己的照实记录并注明"疑似并发改动导致，未处理"，不要去修。

复核时相应地**不能只看 `git status` 的总清单**去核对文件声明，要按改动面归属分别核对——这是并行带来的额外复核负担，由设计会话承担。

T001 / T002 在本协议建立前派发，因此没有 `REPORT.md`——这正是建立协议的直接原因。两者的 `REVIEW.md` 由设计会话事后补做，判定依据是自行重跑验收，不依赖实现方的聊天转述。

T003 判定维持 `ACCEPTED`（schema 归一化本身经独立复核成立），但它的**验收条件由设计会话写错**：`status=completed` 量不出场景是否跑通。勘误见 `T003-schema-compat/REVIEW.md` 末尾，由此产生的规则见 `README.md` 规则 4，遗留工作转 T005。

T006 / T007 由设计会话口头派发，没有 `TASK.md`——这是设计会话的欠账，不计入实现方偏离。规则已补进 `README.md` 第七节「口头派发的任务怎么判边界」。

P1a 的 ID 不走 `T0NN` 序列，因为它是修订计划 P1 的切片（P1a/P1b/P1c），归属关系比流水号更重要。切片与 `T0NN` 共用同一套状态词和复核流程。

