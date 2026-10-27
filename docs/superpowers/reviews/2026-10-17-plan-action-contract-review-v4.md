# 方案原子动作 v4——最终针对性终检

对象：`docs/superpowers/specs/2026-10-17-plan-action-contract-design.md`（v4）
基线：`616464c`
前次：`...-review-v3.md`
日期：2026-10-17
方式：只读核对 v4 第九节/执行完整性；不改设计稿/代码。

## 一、结论

**v3 终检的两个点（40907 事务、40905 legacy gate）已修正；B1'/B2'/B6' 继续成立。但 v4 的“Java 只认 pending”与现有请求 DTO/校验/客户端存在 1 个新 blocker；P1-1 的 targetCountOverride 计算还有 1 个 correctness blocker（unit mode/current count）。修完这 2 个点后可进入实施。**

## 二、逐项核对

### 1) v3 终检 blocker：40907、40905

**已修正。**
- v4 4.2 第 7 条明确：review 失败必须抛 `BusinessException(40907)`（或 `setRollbackOnly()` 后抛），**不得 catch 后正常 return**；并补“回读方案确认没有加入”的测试。方向正确。
- v4 4.2 第 6 条明确：后置条件/重校验**仅新路径**（`rerunReview=true` 或 `kind=plan_action`），legacy add_units 保持基线；3.5 第 2 条同 gate。方向正确。
- 注意实现：如果选择 catch + `setRollbackOnly()` + 返回 40907，外层事务提交会抛 `UnexpectedRollbackException`；建议直接抛 `BusinessException(40907)`，由异常处理映射。v4 已允许这种写法。

### 2) P1-1 纯加入：targetCountOverride / 配额 / dry-run / 40905

**方向正确，但有两个 correctness blocker。**

#### 2.1 `targetCountOverride` 的“old”必须取当前 working plan 实际数量，不是已确认目标数

v4 3.2.2 写“有已确认总数（如 45）：默认提出 targetCountOverride = old + N（如 51）”。但 `enforceSelection` 的 `resolvedSelectionTarget` 在存在 `selectionTargetCount` 时直接返回它（`CanonicalPlanningRuntime.java:65-78`），并用它作为求解目标。若当前 working plan 实际不是 45（例如 40，历史被剔除/未补齐），override=45+6=51 会要求求解器补到 51，即 **多加 5 条**；用户只确认加入 6 条，最终却多了 11 条。后置条件“总数=override”会通过，但用户意图被放大；若求解器无法补到 51，则 40905 回滚，点名加入失败。

**最小修改**：`old` 取 `currentWorkingPlanCount`（unit mode 取单元数），`targetCountOverride = current + addedUnitCount`；如果已确认 `selectionTargetCount` 与 current 不一致，预览要么显示“当前 40/目标 45，将先按 40→46 加入”，要么 blocked 要求先补齐/调整目标，不能静默用 45+6。

#### 2.2 专业组模式必须用“新增单元数”而非“条目数”做 override

`enforceSelection` 的 `countMode` 为 unit 时，`current.size()`/target 都是单元数（`CanonicalPlanningRuntime.java:50-54`、`:65-78`）。v4 说 `addedCount 条目数 + addedUnitCount`，但 `targetCountOverride = old + N` 用的是 targets 条目数。同组多专业（6 个 target 落在 2 个单元）时 override 会多算 4 个单元，导致求解器补入额外单元或 40905。

**最小修改**：`targetCountOverride = currentUnitCount + addedUnitCount`（unit mode）；entry mode 才用 `currentEntryCount + addedEntryCount`；预览同时展示两个口径，但 override 只取 count mode 对应的那个。

#### 2.3 dry-run 不可用时

v4 说“若求解器 dry-run 不可用 → 必须同时阻断有精确档位配额场景，并在预览中明确后置校验”。没有精确配额时仍可出 ready 卡；执行后可能 40905。这不会静默替换（后置条件会回滚），但“ready”卡不保证成功。建议：dry-run 不可用时对**所有 add** 预览降级为带风险提示的卡或直接 blocked；至少 E2E 要验证 dry-run 在目标环境可用。**major**，不是 blocker。
- 有精确档位配额（exact_counts/range/ratio）阻断：`hardPlanningObjectives.tierQuotaGoal` 非空即阻断，符合现有 DTO（`HardPlanningObjectivesDTO.java:13`）。
- 零删除 dry-run + 后置条件 40905：方向正确；postcondition 会检查新增项在 working/ordered、旧项零删除、总数/档位。**成立**（前提是 2.1/2.2 修正）。

### 3) P1-2/P1-3：显式 applied + postconditionReport；frozenCommand + digest；40908

**设计方向正确；有 1 个新 blocker + 1 个 major。**

#### 3.1 blocker：现有 `validate`/client 会拒绝“只传 pending 字段”的 add_units

v4 4.3 写“调用方只提供 pendingId/operationId/claimToken/expectedPlanVersion；volunteerIds/targetCountOverride/rerunReview 由 Java 从 pending 读取”。但：

- `PendingPlanningCommandBizService.validate` 仍要求 `ADD_UNITS` 的 `req.getVolunteerIds()` 非空（`PendingPlanningCommandBizService.java:381-384`），否则 40001 `add_units requires volunteerIds`；
- `internal_client.execute_pending_planning_command` 构造 payload 时**总是**带 `volunteerIds: volunteer_ids or []`（`internal_client.py:1848-1856`）；即使网关不传，也会是 `[]`；
- `validate` 还要求 `commandType` 非空（`:364`），而 v4 文字说只传 4 个字段；4.3 的伪代码又带了 `command_type="add_units"`，需要统一。

按 v4 字面实现，Java 在读取 frozenCommand 之前就会 40001，功能直接不可用。
**最小修改**：
- `validate` 对 `ADD_UNITS` 允许请求层 `volunteerIds` 为空；由 Java 从已认领 pending 的 frozenCommand 读取并校验非空。
- 客户端对 add_units 要么省略 `volunteerIds`/`rerunReview` 等命令字段，要么 Java 区分“未提供”与“空列表”（`PendingPlanningCommandReq.volunteerIds` 默认空列表无法区分）；最简是客户端 add_units 只发 `commandType/pendingId/operationId/claimToken/expectedPlanVersion`，Java 忽略其余。
- 如果调用方仍携带命令字段，再逐项与 frozenCommand 比较并 40908；不要先被 `validate` 的 40001 挡住。
- 测试：请求只带 5 个字段 → 成功；带篡改 volunteerIds/rerunReview → 40908。

#### 3.2 major：tamper 的 40908 可能先被 replay 的 40903 截走

`execute` 先按 operationId 查 existing，命中后 `replay(existing, ..., req)` 比较 `requestDigest(req)`，不一致直接 `COMMAND_CONFLICT_CODE 40903`（`PendingPlanningCommandBizService.java:67-70`、`:260-278`）。如果调用方篡改 volunteerIds/commandType 等字段，在 replay 路径会得到 40903，不是 v4 承诺的 40908。**最小修改**：先比较 frozenCommand/commandDigest（40908），再做 requestDigest replay；或把 40903 映射/统一到 40908。

#### 3.3 frozenCommand 与 prepareOnce digest 的关系

- prepareOnce digest 只覆盖模型输入（v4 3.2.3），frozenCommand/commandDigest 覆盖解析后的命令；两者分离正确。候选池变化时 replay 返回同一 pending/frozen，execute 再按版本/资格 409，语义成立。
- frozenCommand 的 canonical JSON 未包含 `operationId`，但 v4 目标 4 说 operationId 纳入冻结摘要；建议把 operationId 放进 frozenCommand/digest，或明确 operationId 由 pending/operationId 独立校验。**minor**。
- `targetCountOverride` 是 Java 计算值，纳入 frozenCommand；prepareOnce digest 不覆盖它，重试同一 requestId 返回原 frozen；正确。

### 4) targetCountOverride 持久化 / review 事务

- `targetCountOverride` 写入 `hardPlanningObjectives.selectionTargetCount` 后，`CanonicalPlanningRuntime.resolvedSelectionTarget` 会读取它（`CanonicalPlanningRuntime.java:65-78`），并在同一事务内生效；失败/40905/40907 回滚会恢复。**成立**。
- 需要明确这是**永久目标变化**（用户确认 45→51），不是一次性 override；v4 预览已要求展示，成立。若产品只想一次性添加，需另设非持久 override，v4 明确选择了持久化，可接受。
- review 失败 40907 抛异常回滚；成功后 `planningState`/`resultPlanVersion` 重读；`reviewState.sourceVersion=N`、result=N+1；**成立**。
- 40905 后置条件仅新路径 gate；legacy 保持；**成立**。

### 5) v4 其他小问题

- `exactTargets` 对所有 ProposalRequest 必填的兼容面：v4 已列 schema/fixtures/prompt；S1 要逐项改，否则既有 fill/priority/scope 会多一次修复回合。**minor/major（实现）**。
- Java 别名 resolver：v4 3.3 明确“Java 侧没有 Python legacy 那套别名 resolver，名称必须来自候选行”，prompt 要求先 `preview_candidates` 复制准确名称；这关闭了前次“别名 resolver 缺失”的 major。**成立**。
- `no_plan`/`candidate_source_unavailable` 判定来源：v4 3.2.1 写死（working/ordered 为空；candidatePoolState 空/not_generated）；**成立**。
- `ExactTarget` 其他字段（negative_scopes/quality_guards/tradeoff_guards/source_review_issue_codes）已在 v4 validator 拒绝；**成立**。
- `FixProposalDTO` 新增 affectedItems/addedCount/removedCount/targetCountBefore/After；`pending dataValue` frozen；**成立**。
- `postconditionReport` 复用 `PlanChangePostconditionReportDTO` 可表达 added/removed/target/actual；**成立**。
- `PendingPlanningCommandRes.status` 显式 applied + postconditionReport；网关 `_status` 优先读 status；**成立**。

## 三、最终结论

**仍有 2 个 blocker，暂不可进入实施：**
1. **Java 只认 pending 与现有 `validate`/client 冲突**：add_units 请求会被 40001 挡在 frozenCommand 之前（或空 volunteerIds 被当篡改 40908）。修 `validate` + client 只发 5 个字段/区分未提供，再做 frozen 比较。
2. **targetCountOverride 计算口径**：必须用当前 working plan 实际数量（unit mode 用单元数 + addedUnitCount）计算，不能固定用已确认目标 + N 条目；否则会多补/多算，40905 或用户意图放大。

另需在 S1–S4 处理：tamper 的 40908 先于 replay 40903；frozenCommand 是否纳入 operationId；dry-run 不可用时对 ready 卡降级/阻断；`exactTargets` 兼容面与既有 fixture 同步。

完成 1、2 后可进入实施；3 作为实施中的必做项，不应拖到验收。
