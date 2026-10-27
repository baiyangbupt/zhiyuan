# 方案原子动作 v3（ProposalRequest.add_units）——终检

对象：`docs/superpowers/specs/2026-10-17-plan-action-contract-design.md`（v3）
基线：`616464c`
前次：`docs/superpowers/reviews/2026-10-17-plan-action-contract-review-v2.md`
日期：2026-10-17
方式：只读核对 v3 与代码；不改设计稿/代码。

## 一、结论

**B1' / B2' / B6' 已基本落实，可以视为关闭；但仍有 1 个新 blocker 和 1 个 legacy major，修完才可进入实施。**

- B1'：包内 `resolveEffectiveCandidatesForProposal(state)` + `refresh=false` + 仅 add_units 分支 + prepare/execute 同池 + generate 剔除 40905，**成立**。
- B2'：`result.proposals[]` 提取、`pendingId=null`/blocked/info/superseded/preparing 映射、`prepared` 不透传，**成立**。
- B6'：`ExactTarget` 名称 nullable + ID 二选一、both 交叉校验、add↔targets 条件校验、非 add 必须 `[]`，**schema 可表达**；有一处 minor 遗漏（其他 ProposalRequest 字段未拒绝）。
- 新 blocker：review 失败 **“捕获并返回 40907”** 与 `@Transactional` 回滚 A 冲突；捕获后正常 return 会提交 add，不会回滚。
- 新 major：`generateOrderedPlan` 后的 40905 postcondition 没有按 legacy gate；legacy add_units 可能从“静默成功”变成 40905，违反 v3 目标 5。

## 二、逐项核对

### 1) B1'：effective candidates 同池

**成立。**
- v3 3.2 新增包内 `resolveEffectiveCandidatesForProposal(state)`：`resolveEffectiveCandidates(null, state.getSessionId(), state, false)`。`state.getSessionId()` 是可靠的：`loadPlanningState` 最后的 `normalizePlanningStateDefaults(chatSessionId, state)` 会 `state.setSessionId(chatSessionId)`（`PlanningStateService.java:6058-6062`），`generateUserGoalFixProposals` 用 `loadPlanningState`（`:848`）后 sessionId 已就绪。
- 方法在 `PlanningStateService` 内部，可调用 private 的 `resolveEffectiveCandidates`（`:9426`）；`UserGoalProposalBuilder` 同包，设计说“把它传给 buildAddUnits”，传的是列表，不存在跨类调用 private 的问题。
- `refresh=false` 与 `selectWorkingPlanItems` 一致（`:2218-2220`）；execute 用的是同一入口，prepare/execute 同池成立。
- 仅 add_units 分支使用，fill/priority/scope 仍走 `resolveCandidateFactsForProposalAnalysis`（`:847-851`），范围隔离成立。
- `generateOrderedPlan` 用 `refresh=true`（`:2391`），v3 增加“新增 volunteerIds 仍在 ordered plan，否则 40905 回滚”，覆盖了 overlay/硬约束剔除。**成立**。

**注意**：`resolveEffectiveCandidatesForProposal` 必须显式接收 `chatSessionId` 或依赖已 set 的 sessionId；当前设计依赖后者，但 `loadPlanningState` 已保证，可接受。测试要钉住 prepare 与 execute 对同一批 ID 的资格判断一致。

### 2) B2'：prepare 结果形状与状态映射

**成立。**
- v3 3.3 示例已改成真实 `FixProposalStateDTO`（`status/proposalSource/sourceVersion/proposals[]/total`），`proposals[]` 里才是 `FixProposalDTO`。这与 `prepareUserGoalProposal` 的 `PrepareOutcome(..., preview)` 一致（`PlanningStateService.java:873-926`；`FixProposalStateDTO.java:9-17`）。
- 网关复用现有 proposal 分支 `service.py:2889-2902` 提取 `proposals`，正确。
- 状态映射：
  - `pendingId != null && proposal.status == ready` → ready；
  - `pendingId == null || proposal.status != ready` → blocked/info 无按钮；
  - `superseded` → blocked；
  - `preparing` → info；
  - `prepared` 只作 prepare 状态。
  这与 `prepareUserGoalProposal` 的 `pendingId=null` 分支（`:881-883`）一致，**成立**。
- `proposalRef=data.pendingId`、`sourceVersion` 取 proposal，正确。

**minor**：`ConversationProposalRequestService.replay` 实际回 `prepared`（`:141-165`），不是 Javadoc/设计里的 `duplicate`；网关把“`prepared` + 已有 pendingId + result ready”当重放即可，不要等 `duplicate` 字符串。

### 3) B6'：`ExactTarget` schema 是否可表达

**可表达，成立。**
- `school_name/major_name/volunteer_id` 全部 nullable；validator `(school && major) || volunteerId`；names-only、ID-only、both 都能通过 Pydantic。
- `_strict_model_schema` 会把三个字段都设为 required（nullable 可为 null），`_normalize_nullable_for_upstream` 能处理 `type: [string, null]`；模型可以输出 `{"schoolName": null, "majorName": null, "volunteerId": "..."}`。
- `ProposalRequest._validate_exact_targets` 覆盖 add 非空、非 add 空、add 不与 target_count/tier/requirements/priority/target_scopes 混用。
- both 交叉校验在 Java（`target_mismatch`），v3 写明。

**遗漏（minor）**：add_units 只拒绝 `target_count/tier_quota_goal/requirements/priority_rules/target_scopes`，没有拒绝 `negative_scopes`、`quality_guards`、`tradeoff_guards`、`source_review_issue_codes`、`persist_target_count`。这些字段若被模型带上，Java add 分支会忽略；建议一并拒绝或明确“忽略”，避免“用户说了但被静默丢掉”。不是阻塞。
**注意（major）**：v3 仍写“规范化/别名/方向括号按现有 resolver 口径”，但 Java 侧没有 Python 那套 `resolve_school_major_ref`；现有可用的是 `containsLoose`（`UserGoalProposalBuilder.java:2709-2714`）和 `CatalogService.lookupSchool` 的精确名/`searchSchools` 关键词（`CatalogService.java:73-94`、`:170-182`）。若模型输出“厦大”这类别名，Java 可能 `no_match`。最小做法：prompt 明确要求从 `recommendation.preview_candidates` 复制**准确** `schoolName/majorName`（或 entityId）；若要承诺别名，需在 Java 增加 resolver 并测试。

### 4) v3 新引入的问题

#### 4.1 新 blocker：review 失败“捕获并返回 40907”不会回滚 add

**问题**
v3 3.5 第 5 条：“`runReview` 抛错 → 加入一起回滚，捕获并返回独立业务码 `40907 review_failed`”。但 `PendingPlanningCommandBizService.execute` 是 `@Transactional(rollbackFor=Exception.class)`（`:63`）。在方法内部**捕获异常并正常 return** 时，事务不会回滚；`selectWorkingPlanItems`/`generateOrderedPlan` 已经写入的 add 会随外层事务提交。除非：
- 不捕获，直接抛 `BusinessException(40907)`（让事务回滚，controller 映射 40907）；或
- 捕获后 `TransactionAspectSupport.currentTransactionStatus().setRollbackOnly()`，再抛 40907。

按 v3 的“捕获并返回”字面实现，review 失败会出现“卡片显示未生效（审查失败），但方案其实已加入”的静默反向分叉，正是 B5 要避免的。

**最小修改**
- 设计改成：review 失败时**抛** `BusinessException(40907, "review_failed")`（不 catch-return），由现有异常处理映射；或在 catch 内 `setRollbackOnly()` 后再抛。
- 如果确实要返回结构化 `reviewStatus=failed` + 40907，需要把 review 放到独立事务/提交后（备选 B），第一期不建议。
- 测试：review 失败后 working/ordered plan 与执行前一致（回滚），且响应码 40907。

#### 4.2 新 major：40905 postcondition 未按 legacy gate

**问题**
v3 3.5 第 7 条“`generateOrderedPlan` 后检查新增 volunteerIds 仍在 ordered plan；被剔除 → 40905 并回滚”没有写 gate。第 2 条重校验已明确“仅当 `rerunReview=true` 或 `kind=plan_action`”，第 5 条 review 也是新链路；但第 7 条是 add_units 分支的通用后置条件。legacy add_units（`rerunReview=false`、`kind=plan_mutation`）如果遇到条目被剔除，旧行为是静默成功，新行为会 40905。这与 v3 目标 5“legacy add_units 行为不变”冲突。

**最小修改**
- 40905 postcondition 与重校验使用同一 gate（`rerunReview=true` 或 `kind=plan_action`）；legacy 跳过，或明确接受并更新目标 5/回归测试。
- 如果选择“全量加 postcondition”，必须在设计里把目标 5 改成“legacy 只保证 ID 校验/版本语义不变，postcondition 统一加严”，并补 legacy 回归。

#### 4.3 其他 minor/major 残留

- `prepareUserGoalProposal` 写 `commandType/volunteerIds/kind`：v3 已写，成立；实现时注意 `primary.getAffectedVolunteerIds()` 必须由 builder 设置，且非 add 保持旧 `kind=plan_change_proposal/actionFamily=apply_plan_change_proposal`。
- apply 早分支控制流：v3 已明确“直接返回/独立函数”，成立；实现时确保 `command_type/expected_plan_version` 不被后续 proposal 分支引用，且 `rerun_review` 沿 client 全链传。
- `reviewState.sourceVersion=N` / `resultPlanVersion=N+1`：v3 已按真实语义修正，成立；E2E 不要再要求两者相等。
- `result.planningState` 替换为重读后 state：v3 已写，成立。
- `candidate_source_unavailable` / `no_plan`：v3 结果表有语义，但 Java 判定来源未写。`CandidatePoolStateDTO.statusCode` 有 `not_generated/empty`（`CandidatePoolStateDTO.java:14-15`），`candidate_source_unavailable` 目前只在 `CandidatePreviewService`（`:50`）。建议明确 `not_generated/empty` → `candidate_source_unavailable`/`no_candidates`，无 working/ordered plan → `no_plan`；否则容易误报 `no_match`。**minor**。
- `exactTargets` 稳定排序：v3 已写；`UserGoalFixProposalReq` 加字段即可。**minor**。
- `PrepareResultDTO.duplicate`：实际 replay 回 `prepared`；网关不要等 `duplicate` 字符串。**minor**。
- `RepairProposalTaxonomy` add strategy、`FixProposalDTO.affectedItems/addedCount`、`actualChanges/reviewState` 全链：v3 已写，成立；实现时按清单逐项落地。**minor/major（实现细节）**。

## 三、最终结论

**B1'/B2'/B6' 关闭；仍有 1 个 blocker（review 失败 catch-return 不回滚）和 1 个 legacy major（40905 未 gate）。**

最小放行条件：
1. review 失败改为**抛出** 40907（或 catch + `setRollbackOnly` + 抛），不要在 `@Transactional` 内 catch-return；补“review 失败后方案回滚”测试。
2. 40905 postcondition 与重校验同 gate（`rerunReview=true`/`kind=plan_action`），或明确改 legacy 目标并补回归。
3. 实现时把 `prepareUserGoalProposal` dataValue/row kind 分支、`rerun_review` 全链、`ExactTarget` 其他字段拒绝/忽略、`candidate_source_unavailable/no_plan` 判定来源写进 S1–S4；prompt 要求从 `preview_candidates` 复制准确名称（或 Java 增加别名 resolver）。

完成 1、2 后可进入实施；3 作为实施中的必做项，不应拖到验收。
