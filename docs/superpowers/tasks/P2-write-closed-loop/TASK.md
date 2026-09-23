# P2：写入闭环 E2E（codex 网关侧）

> 指派：待定（任务书由本地会话按推进计划 §四 + 2026-09-22 代码审计写）
> 来源：`docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md` 第四章
> 类型：接线 + 验证（Java 侧已就绪）
> 协议：`docs/superpowers/tasks/README.md`
> 前置：**已解除**（T006 解除了可重置私有数据集的镜像源问题）。

---

## 一、目标

把"用户确认 → 落库"这条写闭环在 **codex 网关**上拉通，并覆盖四类异常。
计划书的原话：

> Gateway confirm → `pending/resolve(confirm)` 取 claim → `pending-command/execute`
> → complete/fail 全链路打通；覆盖陈旧 revision、重复确认、过期 Proposal、执行失败四类异常。

**再加上今晚实测带回来的一条**（计划书 §四 末尾那句，P3 任务书也引了）：

> **写操作路径的工具面要明确到模型能据以判断"这个动作我能不能做"**，而不是让它试出来。

---

## 二、代码审计（2026-09-22 核过，不要重新调查）

| 环节 | 现状 |
|---|---|
| Java `POST …/session/pending/resolve` | **存在** ✓（`ChatSessionInnerController:102`） |
| Java `POST …/session/pending-command/execute` | **存在** ✓（`PlanningStateController:172`），另有保留期任务 `PlanningPendingCommandRetentionTask` |
| agent 侧 `resolve_pending_confirmation` | **接了** ✓（`internal_client.py:1286` → `conversation_actions.py:125` 的 confirm 分支） |
| agent 侧 `execute_pending_planning_command` | **封装在**（`internal_client.py:1628`），但 **4 个调用点全部在 legacy agent**（`app/zhiyuan_agent/tools.py`）——**codex 网关侧没有任何调用** ✗ |
| 当前网关模式 | `GATEWAY_MODE=codex_readonly`——写路径本就不该活着（所以上面那条不是 bug，是 P2 的范围） |
| 前端确认卡片 | 本地部分已完成；按后端真实 CAS 结果更新这一步**需真实后端验证**（要浏览器） |

**结论**：Java 与 legacy 都有参照 ✓；**缺的是 codex 网关侧的 execute 那一步与写模式的开关**。

---

## 二之二、把"execute 需要什么"从生产者侧问清（2026-09-22 复核）

派发前的第二次核查，把 execute 那一步的输入逐个落到**出处**上（不是从期望反推）：

| 输入 | 出处（都有文件行） |
|---|---|
| `pendingId` / `operationId` | **Java 产出**：`ConversationProposalRequestService.PrepareOutcome(pendingId, operationId, result)`。类注释还写明"两者都会重新编译一遍预览、生成一个新的 operationId"——**operationId 是每次编译产出的** |
| `commandType` | `apply_plan_change_proposal`（`PendingPlanningCommandBizService` 的常量分支） |
| `proposalApply` | 类型是 `FixProposalApplyReq`：`proposalId / proposalSource / sourceVersionGuard / regenerateOrderedPlan / rerunReview / …`；Java 侧校验信息原话："apply_plan_change_proposal requires proposalApply and proposalId" |
| `expectedPlanVersion` | 快照 `activeProposal.sourceVersion`（Java 已经扁平暴露） |
| `claimToken` | **网关自己在 confirm 时生成的 uuid**，同一个 token 必须复用到 execute——**这是最容易错的一点**（新生成一个 → Java 拒） |
| pending 的 `data` 里装什么 | **仍未定**：读 `ConversationProposalRequestService` + `PendingConfirmationBizService.upsert` 的 payload 构造即可。**不要从 legacy 的 `executionPayload` 反推**——见下 |

**一条核查记录（初版写错、已更正）**：我最初看到 legacy 的 `_pending_execution_payload()`
读 `pending["raw"]["executionPayload"]`，又发现 **`executionPayload` 在 Java 全仓 0 命中**，
就下结论"那条路径是死的"——**错了** ✗。`executionPayload` 是 **legacy 自己写进去的**
（`app/service.py:819-847` 构造该结构，随 `save_pending_confirmation` 存进 pending 的 data）。

所以正确的事实是：**同一个键，两条链各写各的**——legacy 写 `executionPayload` 这一层包装，
而 Java 的 `execute` 接口要的是**扁平的 `proposalApply`（类型 `FixProposalApplyReq`）**。
新链路的实现**不要照抄 legacy 的包装层**（理由是它不是新链路的约定，而不是"它是死代码"）。

**另一条约定冲突，派发时先定**：legacy 用 `uuid5(NAMESPACE_URL, f"zhiyuan:{pending_id}:{command_type}")`
**自己算 operationId**；而新链路里 operationId 是 Java 编译时产出的。两者不能混用——
**建议跟 Java 的**（幂等键的唯一权威在生产者），但这会改变"重复确认"的语义边界，属裁决。

## 三、步骤

1. **写模式**：给网关一个非只读的模式（命名随现有 `codex_readonly` / `codex_shadow` 的体例），
   让写工具在**该阶段**可见。**门禁语义按 P3 的写法进技能**，不许在 Gateway 加关键词规则
   （P3 任务书的硬约束，同样约束本任务）。
2. **确认链**：confirm → `pending/resolve(confirm)` 取 claim → `pending-command/execute`
   → complete/fail；claim 要**带版本**（陈旧 revision 的判定依据）。
3. **四类异常各一条用例**（这是本任务的主要产出）：
   - **陈旧 revision**：claim 拿到的版本与执行时的不一致 → 拒绝执行、如实回话；
   - **重复确认**：同一 claim 二次确认 → 只执行一次（或明确拒绝第二次），**不许双写**；
   - **过期 Proposal**：过期后确认 → 拒绝，并说清"要重新生成"；
   - **执行失败**：`execute` 返回失败 → 状态落 `failed`，**不许报 completed**（P2b 的只升不降规则在此同样适用）。
4. **前端那一条**（需浏览器，可能由 C 线配合）：确认卡片按后端真实 CAS 结果更新——
   **不是**按本地乐观更新。

---

## 四、验收

```bash
cd zhiyuan-agent
# ① 四类异常：各自一条用例，且每条都要有"对照"（正常路径必须过）
.venv/bin/python -m pytest tests/ -q -k "pending or proposal or write"

# ② 真实栈端到端（本地栈已就绪）：一次真实的 confirm → 落库 → 回读
#    这一步要**真 Java**，替身不算——写路径的验收在替身上没有意义

# ③ 不回归
.venv/bin/python -m pytest tests/unit tests/integration -q
```

**反例要求**：四类异常里至少"重复确认"必须给出**双写为零**的证据（回读数据库计数），
不是"返回码看着对"。

---

## 五、边界

- 不改 P1 的权威证据链（写操作不引入新的证据来源）；
- 不在 Gateway 加关键词规则（同 P3）；
- **不碰前端本地乐观更新那段**（第 4 步只做"按真实 CAS 更新"的验证与接线）；
- `mixed-read-write` 那条场景的期望**不动**——它的"不许调写工具"是只读阶段的规矩，
  写模式上来之后应当**换一条场景**去量写路径，而不是放宽它。
