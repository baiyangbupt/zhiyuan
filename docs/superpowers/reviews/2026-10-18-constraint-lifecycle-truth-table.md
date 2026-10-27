# 约束生命周期行为真值表（Batch A2，源码核对版）

日期：2026-10-18。用途：在改卡面文案/持久化前，先记录**当前真实行为**。
状态：已按源码逐项核对（V）。标 `待真栈验证` 的只影响“是否重排”的时序细节；
持久化字段已确认。

## 一、原则

- 卡面只承诺代码真实做到的事；不能统一写“仅本次”，也不能统一写“持久”。
- 目标态区分“本次调整”和“本会话后续规划”；未确认草稿不成为有效约束。
- 学费只保留一个 owner；其他对象引用规范化投影。
- `persistTargetCount` 只表示“是否把 targetCount 写进 requiredCount”，不是通用
  有效期字段。

## 二、真值表（V=源码确认）

| 约束 | 当前写入点 | 读取/生效路径 | 是否触发重排/重建 | 失效/标记 | 卡面应写 |
|---|---|---|---|---|---|
| `targetScopes` / `negativeScopes` | **两类路径**：① pending 冻一份 `userGoalRequest`（`PlanningStateService:910-914`）供预览；② 确认后 `conversation_actions._command_for_goal` 把 scope goal 映射成 `apply_constraint_and_regenerate` + `constraintUpdate`（`conversation_actions.py:773-790`），Java `PlanningStateService.updateConstraintState`（:1426-1432）写 `hardConstraints`/`softPreferences`（`intentMode=constraint` 时走硬约束） | 预览用 `UserGoalProposalBuilder.buildScopeProposal`（:1499-1565）；生效后候选过滤/生成读 `constraintState`（hard/soft preferences） | scope 命令带 `regenerate_ordered_plan=True`（`conversation_actions.py` 同段）→ `generateOrderedPlan` + `refillWorkingPlanByTierTargets` + 再生成（`PendingPlanningCommandBizService:186-204`） | `touchAndSaveConstraint` 标 stale（`recommendationOverlay/initialRecommendation/orderedPlan/planAdjustment/review`，`ReviewInvalidationPolicy:73-85`） | “写入本会话范围（硬/软按措辞），并会重排”；不能写“仅本次” |
| `tuitionRange` | ① `ChatSessionBizService.updateTuitionRange`（:216-245）写 `userScoreDetail.TuitionRange`；② scope/tuition 提案确认后走 `apply_constraint_and_regenerate`，可同时带 `maxTuitionPerYear`（`conversation_actions.py:790+`） | `PlanningStateService.applyConfirmedPlanRequirements`（:9576-9600）/ `loadSessionTuitionRange`（:9600-9636）过滤 effective candidates；`CandidateFitExplainService.explainTuitionRange` 解释 | **直接调用 `updateTuitionRange` 不 bump 版本/不标 stale/不重排**；但通过 scope/tuition 提案的命令路径，`regenerate_ordered_plan=True` 会触发重排 | 直接写无统一 stale；提案命令路径由 `touchAndSaveConstraint` 标 stale | “写入本会话预算；若走约束提案会重排”；不能写“仅本次” |
| `requirements`（include/coverage） | apply 时 `ProjectedHardRequirementSupport.persist`（:59-78）+ `CoverageRequirementSupport.persist`（:80-97）写 `constraintState.hardConstraints`/`hardPlanningObjectives.coverageRequirements`；pending 里也冻结一份 | `RepairCandidateEligibility.isEligibleForConfirmedHardConstraints`、`PlanningObjectiveCompiler`、`CanonicalPlanningRuntime:516` | FILL_MISSING_COUNT 持久化后 `applyUserGoalActions` + `saveAndRefreshAfterFixApply`；`regenerateOrderedPlan` 为 true 才重排（:1281-1300）；命令路径强制 `regenerateOrderedPlan=true`/`rerunReview=true`（:770-774） | 应用时写持久化；版本/ stale 由 apply 路径处理 | “已写入本会话硬要求；可能触发重排（按本次动作）” |
| `priorityRules`（同档前置） | apply 时 `PriorityRuleSupport.persist`（:56-68）写 `hardPlanningObjectives.priorityRules`（只保留第一条） | `PriorityRuleSupport.analyze`、`CanonicalPlanningRuntime` | `PRIORITIZE_WITHIN_TIER` **立即重排**（`enforceOrdering`/`applyFrozenOrdering` + `saveOrderedState`，:1169-1179） | 应用时写持久化 | “已写入同档优先规则，并已重排”；不要只说“记下” |
| `tierQuotaGoal` | `TierAllocationSupport.persist`（:141-150）写 `hardPlanningObjectives.tierQuotaGoal` + `tierQuotaResolution`；仅当 `proposal.tierQuotaChange.stateChanged`（:1083-1088） | **review 不读持久化 goal**：`reviewRatioDistribution`/`reviewCountValidation` 用 `expectedTierCount`（:10787-10809），由 `candidatePoolState.requiredTierCounts` 按 `selectionTargetCount/requiredCount` 缩放；`RepairCandidateSelector` 另有一套未缩放 expectedTierCount（:997-1014） | 生成/补足时按 requiredTierCounts 执行 | 持久化 goal 与 review 实际读的 expectedTierCount 可能不一致 → 诊断，不静默 | “已写入目标配额；审查按缩放后的目标评估” |
| `targetCount` | `applyUserGoalTargetToPlanningState` 总是写 `selectionTargetCount=targetCount`（:1092-1103）；`candidatePoolState.requiredCount=targetCount` 仅当 `persistTargetCount != FALSE`（:1104-1111）；add_units 的 `updateSelectionTargetCount` 两者都写（:1408-1422） | `resolveSelectionTargetCount`（:11138-11144）为权威；`requiredCount` 仍是候选池官方值 | 不单独触发；fill/命令路径按需生成/补足 | 不标 stale 本身 | “目标数量已更新；候选池需求按 persistTargetCount 决定是否同步” |

## 三、命令路径（V）

`PendingPlanningCommandBizService:173-209` 的
`APPLY_CONSTRAINT_AND_REGENERATE`：

1. `constraintUpdate != null` → `updateConstraintState`（step `constraint_updated`），
   `touchAndSaveConstraint`（:2943-2965）会 bump 版本并标 stale：
   `recommendationOverlay/initialRecommendation/orderedPlan/planAdjustment/review`
   （`ReviewInvalidationPolicy.markConstraintIntentStale:73-85`）。
2. `maxTuitionPerYear != null` → `updateTuitionRange`（step `tuition_updated`）。
3. `regenerateOrderedPlan=true` → `generateOrderedPlan(forceOrderedRegenerate())`
   （step `ordered_plan_regenerated`）→ `refillWorkingPlanByTierTargets` →
   `generateOrderedPlan` 再跑一次；否则只 `getPlanningState`（save-only）。
4. 后置校验 `validateConstraintApply`；失败 40905 回滚；方案被清空 40906。

## 四、结论

- **scope 是持久化的**：预览用 pending 里的 `userGoalRequest`；确认后 scope goal
  映射到 `apply_constraint_and_regenerate` + `constraintUpdate`，Java
  `updateConstraintState` 写 hard/soft preferences，并 `regenerate_ordered_plan=True`
  触发重排。卡面不能写“仅本次”。
- **学费是持久化的**：直接 `updateTuitionRange` 写 `userScoreDetail`，不自动重排；
  但通过 scope/tuition 提案的命令路径会带 `regenerate_ordered_plan=True`，会重排。
- **requirements/priorityRules 是持久化的**，且 priority 会立即重排；卡面要写
  真实重排行为。
- **tierQuotaGoal 的持久化与 review 实际读取不是同一个值**：review 读
  `expectedTierCount`（由 requiredTierCounts 缩放），不是 `tierQuotaGoal` 原值。
- **persistTargetCount 不是生命周期字段**，只控制 requiredCount 是否同步。
- 目标态（J4a/B）：一个 owner；学费不重复存；scope 若要持久化，必须新增明确
  生命周期与 stale，不得靠卡面文案冒充。
- **卡面/提示词已按本表更新（2026-10-18）**：ready 的 scope/学费卡明确
  “确认后写入本会话报考要求并重新生成”；无命中的 info 卡明确“尚未写入报考要求、
  后续规划不会自动按它过滤”；`developer_instructions.write.md` 同步同一口径。
