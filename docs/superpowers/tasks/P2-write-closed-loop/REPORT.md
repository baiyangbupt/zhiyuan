---
task: P2
status: PARTIAL（网关侧两段式已接 + operationId 落点已解；② 待写工具面接线后跑真栈）
executor: 本地会话（2026-09-24）
source: docs/superpowers/tasks/P2-write-closed-loop/TASK.md
---

# P2 报告：写入闭环 E2E（codex 网关侧）

## 一、结论

**审计指出的那个缺口补上了**：`confirm` 从"只做到 claim（`applying`）"改成**两段式**
（claim → execute），四类异常各一条用例 + 对照；全量回归过。但 **② 真栈端到端还跑不了**——
它被两处**跨侧**堵点挡住（详见第三节），需要裁决/另一侧改动才能打通。

| 任务书验收 | 状态 |
|---|---|
| ① 四类异常各一条用例 + 对照 | ✓ 已做（新增 6 条，`test_conversation_actions.py` 21 条全绿）。**说明**：任务书要求"重复确认"给**双写为零**的证据（回读数据库计数）——替身层面给的是"execute 只被调一次"；真栈的落库计数随 ② 一起做 ✗ |
| ② 真栈 confirm → 落库 → 回读 | ✗ **就差最后一段**：operationId 的落点已按裁决做完（第三节堵点 1 ✓，Java 编译 + agent 全量都过 ✓），剩下的只有"写工具面接线 + 真栈跑一遍" |
| ③ 不回归 | ✓ `1 failed / 1949 passed / 35 skipped`（那 1 = 旧账 `test_dialog_quality_gate`） |

## 二、改了什么

**`app/gateway/conversation_actions.py`（核心）**：
- confirm 成功（claim 返回 `applying`）后**继续走 execute**：`pending-command/execute`，
  `command_type=apply_plan_change_proposal`；
- **claim token 复用**：claim 时生成、execute 原样带上（任务书点名"最容易错的一点"）；
- `operationId` **只认 Java 编出来的那个**（pending data / activeProposal 里取），**取不到就拒绝执行**
  （`operation_id_missing`）——自铸会让 Java 的幂等键认不出同一次操作，"重复确认不双写"就失去依据；
- `proposalApply` 用**扁平**形状（`FixProposalApplyReq` 那层），**不照抄 legacy 的 `executionPayload` 包装**
  （任务书二之二的更正：那个键是 legacy 自己写的，Java 全仓 0 命中）；
- 失败不许读成成功：沿用既有的 `_status`（"HTTP 成功不等于执行成功"），拿不准一律 `failed`。

**`app/gateway/service.py` / `composition.py`（写模式，最小接线）**：新增模式名 `codex_write`
（与 `codex_readonly` 并列；代码注释写明它**不是**"给模型开写工具"，而是表示确认链在这台实例上是活的）。

**测试**（`tests/unit/test_conversation_actions.py`，新增 6 条）：
对照（同 token + 扁平形状）／陈旧 revision（不执行）／重复确认（execute 只一次）／
过期 Proposal（拒绝 + "要重新生成"如实回传）／执行失败（落 `failed`，不是 `completed`）／
缺 operationId（拒绝执行）。另更新一条旧用例：它记录的正是"claim 只报 applying"的旧行为 ✓（P2 要改的）。

**Java 侧（operationId 落点，2026-09-24 第二轮）**：
`PlanningStateService.prepareUserGoalProposal(...)`（prepareOnce + 把 operationId 写进 pending 的 dataValue ✓）、
新端点 `POST /session/fix-proposals/user-goal/prepare?...&requestId=` ✓、`internal_client.prepare_user_goal_planning_fix_proposals` ✓、
`service.py` 写模式改走 prepare（并同时认 `PrepareResultDTO` 的嵌套 `result` 形状 ✓）。
测试：`tests/integration/test_shadow_gateway.py` 新增写模式用例（含"generate 不许被调"的对照 ✓）→ 该文件 15 条全绿 ✓。
`mvn -o compile` 通过 ✓（Java 单测未补 ✗，见第五节第 5 条）。

## 三、跨侧堵点（② 为什么还跑不了）

1. **~~`operationId` 没有人写进 pending 的 data~~ —— 已解（2026-09-24，按裁决走"生产者侧落地"）。**
   生产者侧确认过：operationId 是 Java 编译时产出的 ✓（`ConversationProposalRequestService.PrepareOutcome`），
   但它原来只存在**自己的实体**里（`ConversationProposalRequestEntity`）✗，没有落进 pending 的 dataValue ✗，
   而快照暴露给网关的只有 `activeProposal.data` ✗ → 网关 confirm 时拿不到 ✗（当时按 fail-closed 拒绝执行 ✓
   所以不会错写，但链路是断的）。
   **落地方案（Java 侧，生产者权威）**：
   - `PlanningStateService.prepareUserGoalProposal(...)`：走 `prepareOnce`（幂等/supersede/并发防线都由它承担 ✓），
     work 里**编译预览 → 生成 operationId → upsert 一个 pending（dataValue 带上 `operationId` /
     `proposalSource` / `sourceVersion` / `proposalId`）→ 返回 (pendingId, operationId, 预览)** ✓；
   - 新端点 `POST /session/fix-proposals/user-goal/prepare?chatSessionId=&requestId=` ✓
     （**只读实例继续走 `generate`** ✓——那条路只出预览、不产生待确认，是刻意的 ✓）；
   - agent 侧：`codex_write` 模式下改走 `prepare`（`requestId = 租户:会话:回合`，同回合重试即重放 ✓）；
     `generate` 在写模式下**不许被调**（测试里用"被调到就炸"的替身守着 ✓）。
   → 闭环因此**不再需要网关自己记录 operationId**：它由 Java 落进 pending、由快照带出来，
     和 execute 段的读取（`activeProposal.data.operationId` ✓）正好接上 ✓✓。
   **留一条**：Java 侧这次没有补单测（时间），由 ② 的真栈端到端覆盖 ✓。
2. **写工具面没有真正接线（step 1 比任务书预估的大）。**
   实测：`MCP_WRITE_TOOLS_ENABLED` / `MCP_MODE` 这两个名字在 `app/` 里**没有任何代码读** ✗
   （启动脚本一直在传 ✓；唯一相关的是 `app/config.py` 的 `McpConfig.write_tools_enabled` ✓——
   正是 2026-09-23 死代码普查里 **零引用** 的那个类 ✗）；`composition.MCP_ENV_VARS` 也只透传
   `INTERNAL_SERVICE_URL` / `INTERNAL_SERVICE_TIMEOUT_SECONDS` ✓，MCP 子进程根本收不到这两个开关 ✗。
   → "让写工具在该阶段可见"不是加个 flag，而是要**真的接线**（MCP 侧读开关并据此暴露写工具 ✓
   + 透传 env ✓ + 与模式的一致性检查 ✓）。
   **补一条事实**：新链路的写路径**本来就没有模型可调的写工具** ✓——它由
   "模型出 `proposalRequest` → Java 编译出 pending → 用户确认 → 网关执行"承担 ✓✓
   （P2 任务书二之二的形状），所以"写模式"要开的是**确认链**，不是给模型一把写枪 ✓。

## 四、边界遵守

- 没改 P1 证据链 ✓；没在 Gateway 加关键词规则 ✓；没碰前端乐观更新 ✓；
- `mixed-read-write` 场景期望一个字没动 ✓（写路径要另开场景量 ✓，见任务书 §五）。

## 五、下一步

1. ~~定 operationId 的落点~~ ✓ 已做完（走生产者侧：Java prepare 落进 pending.dataValue + 新端点 + agent 写模式改走它）；
2. 接线写工具面（三节堵点 2：MCP 读开关 + env 透传 + 一致性检查）；
3. ② 真栈端到端 + "重复确认"的**数据库计数**证据（要真 Java ✓）；
4. 新开一条"写路径"场景（别放宽 `mixed-read-write` ✓）；
5. 补 Java 侧 `prepareUserGoalProposal` 的单测（本轮只到"编译过 + 由 ② 覆盖"✗）；
6. ② 开跑前先**重打包重部署 Java**：本地跑的还是 2026-09-22 06:29 的 jar ✗，不含新端点 ✓
   （agent 侧已重启到新代码 ✓，health 200 ✓）。
