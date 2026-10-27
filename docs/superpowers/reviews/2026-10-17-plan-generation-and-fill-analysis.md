# 从候选到方案：生成 / 补全 / 点名加入的一致性分析与目标架构

日期：2026-10-17
仓库：`/root/dev/zhiyuan`
分支：`wip/2026-09-28-p2-write-loop-green`
基线：`616464c`
方式：只读分析（未改代码、未提交、未部署）

> **工作树说明**：本次阅读的是**当前工作树**，即 `616464c` 加上未提交的 `add_units` 施工（`PendingPlanningCommandBizService`、`UserGoalProposalBuilder`、`gateway/contracts.py` 等）。正文凡涉及 `add_units` 新链路处会标明“工作树”；其余结论以基线代码为准。未运行测试、未做性能测量；文中数字只来自代码常量/阈值。

---

## 一、结论摘要

1. **当前不存在一套统一的“候选 → 方案”骨架。** 至少有三套候选事实来源（原始候选池、`resolveEffectiveCandidates`、agent 侧候选工件），以及五套排序/选择键（rank 的 `volunteer_score`、水位线 `schoolEnrollRatio`、初始方案 `finalScore`、补全 `intentScore`、solver 的 `stableOrder`）。生成、补全、点名加入、范围调整、审查修复各自复用了其中一部分，但没有共同口径。
2. **canonical solver 只优化“可行 + 少改动 + 贴近历史档位结构”。** 它的权重只有 `CHURN_WEIGHT=1e12` 与 `STRUCTURE_DEVIATION_WEIGHT=1e6`；分数、录取率、地域/专业多样性都不在目标函数里。候选质量只能通过调用方传入的 `stableOrder` 影响求解结果，且只在 churn/结构权重可比时才起作用。
3. **`fill_to_count` 与 `initial-plan/generate` 不同源、不同排序，后置报告也与冻结目标不同源。** fill 用原始候选池 + 投影硬约束，初始方案用 effective candidates（硬约束 + 会话学费）并先做启发式冲稳保选择；scope/tuition 又是第三条（原始候选池 + 硬约束）。同一句“补到 45 个”与“生成完整方案”可能选出不同的候选集合。更严重的是：编译期 coverage = 已确认 + 本轮请求并按身份排序，后置报告只遍历本轮请求、不回落已确认 coverage（priority 已回落），存在 `40905 frozen objective result mismatch` 风险。
4. **两套 `add_units` 路径并存。** Java 的 `UserGoalProposalBuilder` 有 dry-run、档位配额阻断、数量校验；但 pydantic agent 的 `preview_plan_action(add)` 只在 agent 侧建 pending，不经过 Java 预览；确认时若 pending 没有 `frozenCommand`，Java 走 legacy 分支：只 select + 重排，没有目标数/覆盖/档位后置校验，也不重跑审查。codex gateway 的 `proposalRequest` 路径则走 Java `prepare`，会写 `frozenCommand`——两条入口的安全性不同。
5. **“结构最优”现在不是一个可度量目标。** 冲稳保配比、梯度、保底、覆盖、去重、地域/专业多样性分散在：solver 硬约束、初始方案启发式、review 检查、以及只写在报告里的权重表。review 的 `ratio_distribution` 甚至不读取用户已确认的 `tierQuotaGoal`，只看候选池的 `requiredTierCounts`。
6. **建议目标架构**：一个候选快照（含逐候选 eligibility/coverage/utility 标注）→ 一个意图模型（硬约束 / 覆盖要求 / 结构目标 / 排序规则 / 软偏好 / 仅展示）→ 一个 objective compiler（生成、补全、点名加入、范围调整都编译成同一 `CanonicalPlanningObjectiveSet` 的 delta）→ 一个 solver（字典序：硬可行 → 结构偏差 → 改动成本 → 软效用/多样性）→ 一个后置校验器 → 一份结构指标回执 → 审查只做同一指标向量上的诊断。分阶段落地，先统一事实来源与后置条件，再谈“最优”。

---

## 二、入口地图：从用户动作到 Java 能力

| 用户/模型动作 | agent 入口 | Java 入口 | 主要产物 |
|---|---|---|---|
| 预览候选 | `preview_candidates` → `/candidate-preview` | `CandidatePreviewService.preview` | 只读候选页（最多 20 条/页，`total` 为过滤后全量） |
| 查候选池 | `query_planning_candidate_pool` → `/candidate-pool/query` | `PlanningStateService.queryCandidatePool` | 候选池分页；会刷新 overlay 落盘 |
| 生成候选池 | `/candidate-pool/generate` | `generateCandidatePool` | `candidatePoolState` |
| 生成完整方案 | `preview_plan_action(generate)` 确认后 `/initial-plan/generate` | `generateInitialPlan` | 初荐 + 工作方案 + 排序方案 |
| 补齐数量 / 覆盖 / 档位 / 优先 | `preview_plan_change` → Java `user-goal/generate`；确认后 `apply_plan_change_proposal` | `UserGoalProposalBuilder.buildFillToCountProposal` / `buildPriorityProposal` | `FixProposalDTO` + pending（gateway 路径由 Java prepare 物化） |
| 范围调整（只看/至少包含/避开/学费） | `preview_plan_change`（scope/tuition 目标）或 `preview_plan_action(replace/remove)` | `UserGoalProposalBuilder.buildScopeProposal` / `buildTuitionBudgetProposal` | 一次性替换/移出/加入提案 |
| 点名加入 | `preview_plan_action(add)`；或 gateway `proposalRequest(goalType=add_units)` | 工具路径：Java `/pending-command/execute` legacy；gateway 路径：Java `prepare` + `add_units` frozen 执行 | 加入志愿；两条路径后置校验不同 |
| 按档位补足 | `/refill-by-tier`（内部/页面） | `refillWorkingPlanByTierTargets` | 只追加工作方案 |
| 审查 | `review_plan` → `/review/run` | `runReview` | `ReviewStateDTO` |
| 审查修复 | `preview_fix_proposal` / `review_plan` 修复动作 | `generateFixProposals` + `applyFixProposal` | 审查修复提案 |

**入口一致性结论**：codex gateway 的 `proposalRequest` 是“Java 预览 + Java pending + frozen 校验”的闭环；pydantic `tools.py` 的 `preview_plan_change` 是“Java 只读预览 + agent 自建 pending + 确认时 apply”；`preview_plan_action(add)` 则是“agent 自建 pending + Java legacy 执行”。同一语义存在三种信任边界。

---

## 三、各路径逐条拆解

### 3.1 候选池生成（`candidate-pool/generate`）

**输入**：会话成绩、画像、志愿源数据。

**链路**（`PlanningStateService.java:1687-1738`）：

1. `loadPlanningState`；非 force、非 stale、池非空则直接返回（`1689-1695`）。
2. `recommendVolunteerList(tenant, session, false, false)`（`1703`）或 `recommendVolunteerListWithSourceData`（`1699-1701`）。
3. 推荐流水线（`VolunteerBizService.java:103-217`）：
   - 读成绩/画像（`VolunteerDataProvider.java:52-71`）；
   - 合并画像（`VolunteerBizService.java:169`）；
   - 读全量志愿数据并转成 `VolunteerSchoolGroup`（`173-174`）；
   - 计算目标数量：`calculateTargetSchoolCount`（`178`，`VolunteerDataProvider.java:117-127`）；
   - 目标数量 → 冲/稳/保配额（`VolunteerBizService.java:753-764`，`VolunteerIntervalService.calculateTargetCounts`）；
   - 构建筛选条件（`VolunteerFilterChain.buildQueryCondition`，`27-79`）；
   - 过滤（`filterVolunteerData`，`221-268`）；
   - 九宫格切分 + rank 排序 + 合并三区间（`VolunteerSorterAndMerger.java:51-91`）。
4. 响应 → 候选池状态（`buildCandidatePoolStateFromResponse`，`1774-1806`）：把冲/稳/保三段 flatten 成 `CandidateItemDTO`，规范 ID、补专业分类字段、重算 summary、按可用容量归一化档位目标（`1808-2101`）；`CandidatePoolQualityStatusBuilder.apply`（`1804`）。
5. CAS 落盘（`1724-1735`），写 overlay、phase、stale、version（`applyCandidatePoolRefresh`，`1748-1764`）。

**关键事实**：

- **候选池不是 top-N**：`recommendVolunteerList(..., split=false)`（`1703`），`VolunteerSorterAndMerger` 在 `split=false` 时把水位线之后的剩余候选全部追加（`277-287`），因此池是“过滤后的全量（已知档位）”。
- **未知档位被丢弃**：`sortEveryInterval` 过滤 `UNKNOWN_INTERVAL`（`109`），而 `divideVolunteers` 把 `schoolEnrollRatio` 为空/非有限/越界的学校放进 `未知`（`VolunteerIntervalService.java:42-58`）。这些候选不会进入池，也没有 `limitations` 回执。
- **池内顺序不是 rank 顺序**：水位线内按 `schoolEnrollRatio` 升序（`275`），水位线后按九宫格子区间原顺序追加（`277-287`）；`rank_in_tier` 却是按 `volunteer_score` 排名（`VolunteerResponseBuilder.java:147-164`）。列表顺序、`rankInTier`、`finalScore` 三者不同源。
- **专业组模式还会截断专业列表**：`processTruncatedMajorList`（`336-377`）按 `majorCount` 截断并保证至少一个专业录取率不低于组录取率。
- **候选池不含 planning 硬约束**：池按 `VolunteerFilterChain` 过滤（色盲/专项/少数民族/中外合作/学费/录取率/选科），不读取 `constraintState.hardConstraints`。后者只在 `resolveEffectiveCandidates` 里过滤。

### 3.2 完整方案生成（`initial-plan/generate`）

**链路**（`PlanningStateService.java:2487-2519`）：

1. 读 state；若已有工作方案且非 `overwriteExistingDraft`，走重排（`2491-2496`）。
2. 必要时生成/刷新候选池（`2498-2508`）。
3. `applyInitialPlanGeneration`（`2522-2537`）：
   - 必要时 `buildInitialRecommendationState`；
   - `resolveEffectiveCandidates(..., true)`（`2534`）；
   - `replaceWorkingPlanWithInitialRecommendation`（`2535`）；
   - 重算 summary。
4. `reorderWorkingPlanInternal` → `generateOrderedPlan`（`2561-2566`）。

**初荐选择（扁平模式）**（`buildInitialRecommendationSelectionState`，`3429-3473`）：

1. 取候选池 items，`mergeOverlayIntoCandidates`（`3030-3033`），再 `applyConfirmedPlanRequirements`（`3034`）——**硬约束 + 会话学费**过滤。
2. 按 tier 分桶（`3439`），桶内按 `buildInitialRecommendationCandidateComparator` 排序（`3755-3766`）：
   `preferred` → `futureDevelopmentScore` 降序 → `finalScore` 降序 → `admissionRatio` 升序 → `rankInTier`。
3. 按 `targetTierCounts` 逐桶取（`3444-3458`）；`targetTierCounts` 来自 `candidatePool.requiredTierCounts`，为空时回退 30%/30%/40%（`3718-3741`）。
4. 缺口补足（`fillInitialRecommendationCountGap`，`3768-3787`）：按最大缺口档位补，允许向相邻档借（`3789-3831`）。
5. 本省保底修复（`repairInitialRecommendationSafety`，`3834-3868`）：分数 < 580 且本省保底 < 2 时，用本省“保”替换外省项；找不到则记 `safety_guard`。
6. 录取率倒挂修复（`3896-3916`）：相邻录取率倒挂时尝试换人。
7. 录取率梯度修复（`3870-3894`）：候选按录取率全局排序后相邻差 > 8 视为断层，尝试换人；最多 10 次。
8. 档位再平衡（`3918-3944`）：仍低于档位目标时补/换；失败记 `ratio_distribution`。
9. 按档位 → 录取率升序 → `finalScore` 降序排序（`4718-4725`）。

**专业组模式**（`3064-3112`，`3475-3555`）：先按单元聚合并选代表（`buildMajorGroupUnitRepresentative`，`4909-4922`），单元内按 `preferred → futureDevelopmentScore → intentScore → admissionRatio → finalScore` 排序（`4927-4935`）；用代表候选跑同一套初荐选择；再做单元级修复（`repairMajorGroupRepresentativeSelection`，`3498-3532`）。

**排序方案生成**（`applyOrderedPlanGeneration`，`2454-2485`）：

1. `resolveEffectiveCandidates`（`2461`）；
2. 若存在已确认目标（`selectionTargetCount` / coverage / tier allocation），`CanonicalPlanningRuntime.enforceSelection`（`2463-2467`）——**这是初荐之后第二次“选人”**；
3. `buildOrderedItemsFromWorkingPlan`（`2468-2470`）：`regroupByTier=true` 时按 `tierOrder → 录取率 → 本省保底 → futureDev → rankInTier → finalScore` 排序（`12969-12997`）；
4. 专业组模式构建 ordered units（`2471-2473`）；
5. `enforceOrdering` 或 `applyFrozenOrdering`（`2475-2482`）；
6. 重算 summary。

**要点**：

- **初荐启发式与 solver 是串联的两套结构逻辑。** 初荐按档位配比/安全/梯度修补；只要存在 `selectionTargetCount`/coverage/tier goal，solver 随后可以换掉初荐选出的项。两边目标不一致时，用户看到的“初荐解释”与最终方案可能不同。
- **没有已确认目标时根本不跑 solver**（`hasSelectionObjectives`，`CanonicalPlanningRuntime.java:609-617`），此时结构完全由启发式决定。
- **报告里的权重不是求解权重**：`buildInitialPlanObjectiveWeights` 写 `tier_structure 0.24 / preference_match 0.18 / admission_safety 0.18 / future_development 0.14 / recommend_score 0.14 / local_safety 0.07`（`3156-3202`），仅用于 `strategyReport`，不参与任何选择/求解。容易让读者误以为系统在做加权最优化。

### 3.3 `fill_to_count`（补齐 / 保持总数）

**入口**：`UserGoalProposalBuilder.buildFillToCountProposal`（`614-950`）。

**链路**：

1. 校验 targetCount、requirements、priorityRules、tierQuota 组合（`616-651`）。
2. `PlanningObjectiveCompiler.compile(state, req)`（`660-666`）生成 canonical objective set：
   - targetCount；
   - eligibility = `ProjectedHardRequirementSupport.project(state, req.requirements)`（`PlanningObjectiveCompiler.java:53-54`）；
   - coverage = 已确认 coverage + 本轮 include 要求（`174-197`）；
   - tier allocation（若请求带 tierQuotaGoal）；
   - ordering = 请求 priorityRules 或 state 已确认规则（`58-60`）。
3. `candidates(state)` = **原始候选池 items**（`UserGoalProposalBuilder.java:2883-2886`）。
4. `projectCurrentPlan(current, projectedRequirements)`（`673-674`，`3387-3438`）：只用**本轮 requirements**（`ProjectedHardRequirementSupport.project(null, req.requirements)`，`669-670`）判断当前方案哪些项要移出；**不包含**已确认硬约束、也不含学费。
5. 计算 `retainedCount`、`gap = targetCount - retainedCount`；若 retained > target → blocked（`733-738`，fill 不裁剪）。
6. `selectFillCandidates`（`1244-1320`）：
   - `buildFillOptions` 从原始池排除已选、过滤 `isCompensationSafeCandidate`，按 `intentScore 降序 → admissionRatio 降序 → finalScore 降序 → schoolRank 升序` 排序（`1354-1381`，`3045-3052`）；
   - 再用 `projectedHardConstraints`（**含** state 已确认硬约束 + 本轮 requirements）过滤（`1254-1258`）；
   - `capSolverCandidatePool` 把送入 solver 的候选截到 `MAX_CANDIDATES - retained`（`1236-1242`，`1266-1273`）；
   - `PLAN_SOLVER.solve(buildSolverInput(...))`（`1272-1274`）；
   - solver 结果映射为 remove/add（`1303-1318`）。
7. 后置：proposal 状态 / dry-run / actions；确认后 `applyUserGoalFixProposal`（`PlanningStateService.java:1042-1072`）重新生成预览并应用；`applyUserGoalTargetToPlanningState` 持久化 requirements/priority/tier goal/selectionTargetCount（`1075-1111`）；`applySupportedFixProposalStrategy` 对 fill 策略应用 solver 冻结结果（`1183-1203`）。

**要点**：

- fill **不读取会话学费**：`selectFillCandidates` 只传 `projectedHardConstraints`，没有 `loadSessionTuitionRange` / `isEligibleForTuitionRange`；而 `resolveEffectiveCandidates` 会加学费过滤（`PlanningStateService.java:9580-9593`）。如果候选池是在旧学费下生成的，fill 可能选到当前学费范围外的候选。
- fill 的 `projectCurrentPlan` 只用本轮 requirements，不用已确认硬约束；若当前方案有违反已确认硬约束的项，fill 可能保留，直到后置校验失败。
- fill 的候选排序以 `intentScore`（专业分）为先；初始方案以 `finalScore`（志愿综合分）为先；solver 的可用候选以 `intentScore → finalScore` 为稳定序（`CanonicalPlanningRuntime.java:648-655`）。三者不同。
- `preserveCurrentCount`（`persistTargetCount=false`）只允许 include 类覆盖要求，且 targetCount 必须等于当前数（`644-659`）；否则 blocked。

### 3.4 `prioritize_within_tier`（同档前置）

**链路**（`UserGoalProposalBuilder.java:952-1074`）：

1. 只接受 priorityRules，不接受 targetCount/requirements（`954-960`）。
2. `PriorityRuleSupport.analyze` 统计命中、逆序、缺档、pinned 冲突（`974-998`）。
3. `PlanningObjectiveCompiler.compile` → targetCount 设为当前 retained 数（`1000-1014`）。
4. `PLAN_SOLVER.solve`（retained 作为输入，无新增）→ 后置 `applyFrozenOrdering`（`1015-1024`）。
5. 应用时 `applySupportedFixProposalStrategy` 的 `PRIORITIZE_WITHIN_TIER` 分支：有 `proposal.solverResult` 时 `applyFrozenOrdering` + `verifyFrozenState`；没有时退化为 `enforceOrdering`（`failOnPriorityMiss=true`，零命中会 409）（`PlanningStateService.java:1166-1181`），随后 `saveOrderedState` 并可选重跑审查。

**要点**：priority 是“只在档位内重排”，不改变集合；但 `PriorityRuleSupport` 的 `matches` 只支持 include 语义（`221-229`），没有“负向优先/降权”。`orderingTarget` 默认 `rank_before`，`scope` 默认 `within_tier`（`PriorityRuleSupport.java:26-27`，`PlanningObjectiveCompiler.java:243-247`）。

### 3.5 范围 / 学费目标（scope / tuition_budget）

**入口**：`buildScopeProposal`（`1499-1563`）、`buildTuitionBudgetProposal`（`1621-1696`）。

**链路**：

1. `scopesForGoal` / `ScopeMatcher` 把 targetScopes 转成匹配器（`2848-2881`，`3140-3290`）。
2. `candidates(state)` = 原始候选池（`1515`）；当前方案 `currentPlanVolunteers`（`1516`）。
3. 候选匹配集：排除已选、`isCompensationSafeCandidate`、`isEligibleForConfirmedHardConstraints`，按 `buildCandidatePreviewComparator` 排序（`1534-1541`）——**不加学费过滤**。
4. 根据 goalType：
   - `only_keep_scope`：移出范围外（跳过 locked），用范围内候选成对替换（`1565-1619`）；
   - `must_include_scope`：当前已有则 info；没有则方案满时替换 1 组，否则加入 1 条（`1698-1749`）；
   - `exclude_scope`：移出命中项并替换（`1751-1802`）；
   - `tuition_budget_scope`：移出超预算项，用预算内候选替换（`1621-1696`）。
5. 应用：`RepairApplyMutationBuilder.applyUserGoalActions`（`PlanningStateService.java:1151-1159`），然后 `saveAndRefreshAfterFixApply` → 可选 `generateOrderedPlan`（`1291-1296`）。

**要点（最重要的断层之一）**：

- **scope 目标不持久化。** `applyUserGoalTargetToPlanningState` 只持久化 `requirements`、`priorityRules`、`tierQuotaChange`、`selectionTargetCount`（`1075-1111`）；`targetScopes` 不在其中。`only_keep_scope` / `must_include_scope` / `exclude_scope` / `tuition_budget_scope` 都是一次性编辑。
- 应用 scope 后如果 `generateOrderedPlan` 触发 `enforceSelection`（存在 selectionTargetCount/coverage/tier goal），solver 可以为了满足目标数重新加入范围外候选——因为 scope 没有变成硬约束/覆盖要求。用户说“只看北京”，下一次方案重生成可能又出现外地。
- `tuition_budget_scope` 也不写回 `userScoreDetail.tuitionRange`；学费区间更新是另一条接口（`ChatSessionBizService.updateTuitionRange`，`216-245`），且**不标记候选池 stale**。因此“学费上限”在 scope 提案、推荐池、effective candidates 三处可能不同步。
- `must_include_scope` 方案已满时只尝试替换 1 组（`1722-1740`），不是求解器全局最优；找不到就退化为“仅展示候选”（`1742-1747`）。

### 3.6 点名加入 `add_units`

当前有 **两条预览/执行路径**，必须分开看。

#### 3.6.1 Java user-goal 预览（工作树）

`buildAddUnitsProposal`（`UserGoalProposalBuilder.java:231-390`）：

1. `candidates(state)`（工作树中 `generateUserGoalFixProposals` 对 add_units 先替换为 `resolveEffectiveCandidatesForProposal`，即硬约束 + 学费，`PlanningStateService.java:847-858`）。
2. 当前方案为空 → blocked；候选池为空 → blocked（`236-244`）。
3. 已确认 tierQuotaGoal 存在 → **直接 blocked**（`245-251`，`add_units_tier_quota_unsupported`）。
4. 当前方案每一条都必须在有效候选池中，否则 blocked（`261-274`）。
5. `exactTargets` 解析（`279-325`，`436-510`）：ID 优先；名称必须学校+专业同时给；先精确匹配，再宽松匹配；多个匹配 → ambiguous；已在方案中 → already_selected；被 ban → blocked。
6. 当前数必须等于已确认 `selectionTargetCount`，否则 blocked（`341-347`）。
7. `targetAfter = currentCount + addedCount`（unit mode 用新增单元数，`327-349`）。
8. `dryRunAddUnits`（`517-582`）：
   - 无 selection objectives → ok；
   - 有 objectives → 用同一 objective set、`targetCount=targetAfter`，把“当前方案保留项”作为 retained，“点名新增项”作为 available，调用 solver；
   - solver blocked、或结果删掉/漏掉新增/删掉现有、或 selected.size()!=targetAfter → blocked。
9. proposal 输出 affected ids、targetCountOverride、actions、dry-run 元数据（`357-389`）。
10. 确认后 `prepare` 写 `frozenCommand`（`PlanningStateService.java:931-952`）：`volunteerIds`、`targetCountOverride`、`rerunReview=true`、`sourceVersion`、digest。
11. 执行 `executeAddUnitsWithFrozen`（`PendingPlanningCommandBizService.java:365-476`）：
    - `targetCountOverride` 非空 → `updateSelectionTargetCount`（`380-383`）；
    - 每个请求 id 必须仍在 `resolveEffectiveCandidatesForProposal` 中（`386-397`）；
    - `selectWorkingPlanItems` → `generateOrderedPlan(force, regroup)`（`399-406`）；
    - 后置：请求项必须在 working/ordered；现有项不得减少或丢失；总数必须等于 override（`408-437`）；
    - `rerunReview=true` → `runReview`，失败抛 40907 回滚（`439-450`）；
    - 回执 `satisfied=true`，只含 count/added/removed（`465-474`）。

#### 3.6.2 pydantic agent 工具路径（当前 `preview_plan_action(add)`）

- `preview_plan_action(add)` 用 `_resolve_add_candidate_targets` 从 agent 侧 `plan/candidates.json` 工件解析候选（`tools.py:6799-6845`），然后调用 `_resolve_plan_targets(source="candidates")`（`10558`）。
- 解析成功后直接 `_plan_pending_payload` + `_create_plan_pending`（`10614-10623`，`10869-10890`），payload 只有 `action_family=add_units`、`volunteer_ids`、`raw_user_text` 等；**不经过 Java `user-goal/generate`**，没有 Java 的 `targetCountOverride`、tier quota 校验、dry-run、stale plan 校验。
- 确认执行走 `internal_client.execute_pending_planning_command(command_type="add_units")`（`tools.py:8146-8178`），且注释明确“add_units 新链路只发 5 个字段，命令内容以 pending 的 frozenCommand 为准”（`internal_client.py:1855-1857`）。
- 但 agent 自己 `_create_plan_pending` 写入的 pending 并没有 `frozenCommand`；Java `frozenCommand(pending)` 返回 null → 走 legacy 分支（`PendingPlanningCommandBizService.java:230-244`）：只 `selectWorkingPlanItems` + `generateOrderedPlan`，**没有**目标数/覆盖/档位/零删除后置校验，也**不重跑审查**。
- 因此工具路径的实际保障只有：`generateOrderedPlan` 内部的 `enforceSelection`（若存在已确认目标）和 `selectWorkingPlanItems` 的 effective candidate 校验。若没有已确认目标，add 只是“加进去再排序”。

**结论**：Java 侧工作树的 add_units 设计是完整的候选→方案路径；但 agent 工具路径尚未接到这套设计上。两条入口的安全性不一致，是当前最高优先级的断层。

### 3.7 `refillWorkingPlanByTierTargets`

`PlanningStateService.java:12579-12631`：

1. 读 state；pool/draft 为空则返回。
2. `resolveEffectiveCandidates(..., true)`（硬约束 + 学费）。
3. `refillWorkingPlanByTier(draft, effectiveCandidates, pool.requiredTierCounts)`（`12604`，`12615-12631`）：
   - 遍历 `requiredTierCounts`；
   - `addAutoSelectedByTier` 从候选列表**按池内顺序**取同 tier 项，跳过已选/已 ban，直到该 tier 达到目标（`12542-12565`）。
4. 同步 units、重算 summary（`12605-12606`）。

**要点**：只追加、不删除、不调用 solver、不检查 coverage/priority/总数上限；`requiredTierCounts` 是候选池的官方口径，不是用户确认的 `tierQuotaGoal`。如果用户已设置自定义档位目标，refill 仍按池的目标补。`refill` 也没有后置校验。

### 3.8 审查与审查修复

**审查链路**（`PlanningStateService.java:2847-2908`）：

1. `resolveEffectiveCandidates(..., true)`（`2867`）。
2. `buildStructuralOrderedSnapshot` 把当前方案整理成结构化 ordered state（`2873-2875`）。
3. 依次执行 14 项检查（`2878-2894`）：
   - `ratio_distribution`：冲/保占比阈值 40%/20%，并结合 `expectedTierCount`（`10707-10784`）；
   - `safety_guard`：分数 < 580 时本省“保”≥ 2（`10810-10872`）；
   - `probability_inversion`：相邻 ordered 项录取率倒挂（`10874-10932`）；
   - `probability_gap`：相邻录取率差 > 8（`10934-11034`，跨档豁免常量 `false`，`11026`）；
   - `count_validation`：优先 `selectionTargetCount`，否则 `requiredCount`（`11036-11131`）；
   - `high_tuition`、`admission_limit`、`special_enrollment`、`edge_score`、`cooperative_program`、`group_inner_safety_guard`、`major_group_safety_intent_alignment`、两条 notice。
4. `buildCompensationPreview` 生成补足/替换建议（`11489-11565`），并附着到 checks（`2896-2898`）。
5. 写回 reviewState、version+1、phase=reviewed、review stale=false（`2903-2907`）。

**审查修复**：`generateFixProposals`（`830-845`）在 review stale 时先 `runReview`，然后用 `effectiveCandidates` + `buildCompensationPreview` + `buildFixProposalState` 生成提案；应用走 `RepairApplyMutationBuilder` / `RepairDryRunSimulator`，不是 canonical solver 的同一目标集。

**要点**：

- **review 是诊断器，不是生成器的一部分。** 生成/补全/加入都不会自动调用 review；只有显式 `rerunReview` 或用户动作才会。`saveWorkingPlanState`/`saveOrderedState` 每次都会 `markPlanStructureStale`（`13578-13595`），所以 review 结果很容易变 stale，但不会自动重算。
- **review 的 `ratio_distribution` 不读取已确认 `tierQuotaGoal`。** `expectedTierCount` 只看 `candidatePool.requiredTierCounts`（`10791-10807`），并用 `selectionTargetCount/requiredCount` 等比缩放。如果用户确认了自定义档位目标，review 仍按官方池目标判“配比正常/异常”。
- **review 的梯度/倒挂基于 ordered 顺序**；`ordered` 由 `regroupByTier=true` 时按 tier → 录取率排序（`12969-12997`），而初荐的梯度修复按全局录取率排序（`findInitialRecommendationGaps`，`4553-4586`）。两者可能对“断层”给出不同结论。
- **review 没有地域/专业多样性、院校层次覆盖、专业组完整性（除 safety）等检查**；这些只在 `initialPlanStrategyReport` 的 action/tradeoff/reason code 里出现，或完全没有。
- **review 修复与生成/补全不是同一套目标。** 修复路径有自己的 `RepairDryRunSimulator` 质量指标（平均 finalScore 等，`RepairDryRunSimulator.java:147-160`）和目标校验；它不是 canonical objective set 的 solver 解。

---

## 四、横向对比：候选源 / 过滤 / 排序 / 求解 / 后置

| 路径 | 候选源 | 过滤 | 排序/选择键 | 求解 | 后置校验 |
|---|---|---|---|---|---|
| 候选池生成 | 推荐流水线全量（`split=false`） | 色盲/专项/少数民族/中外合作/学费/录取率/选科；不含 planning 硬约束 | 九宫格内 rank `volunteer_score`；水位线按 `schoolEnrollRatio` | 无 | 无（只有数据质量 builder） |
| 候选查询 / 预览 | 候选池 items（+overlay） | 视图过滤器（tier/省/市/校/专业/标签）；**不含硬约束/学费** | `finalScore` 等视图排序 | 无 | 无 |
| 初始方案 | `resolveEffectiveCandidates`（硬约束 + 学费） | 硬约束 + 学费 | 桶内 preferred → futureDev → finalScore → admissionRatio ↑ → rankInTier | 初荐无 solver；随后 `enforceSelection`（仅有目标时） | 无统一后置；靠 generateOrderedPlan 的 frozen/solver 校验 |
| `fill_to_count` | 原始候选池 | 本轮 requirements + 已确认硬约束（`projectedHardConstraints`）；**不含学费** | intentScore ↓ → admissionRatio ↓ → finalScore ↓ → schoolRank ↑ | ojalgo（target/coverage/tier/churn） | `UnifiedPlanPostconditionValidator`（count/requirements/priority/tier/frozen） |
| `prioritize_within_tier` | 原始候选池（仅当前方案） | 无新增 | priority 命中 → within tier | ojalgo（仅排序，target=current） | frozen ordering + postcondition |
| scope / tuition | 原始候选池 | 硬约束；**不含学费**（tuition goal 自身按预算筛） | intentScore ↓ → admissionRatio ↓ → finalScore ↓ → schoolRank ↑ | 无（贪心替换） | `applyFixProposal` 的 applied/postValidation（不含 coverage/tier） |
| add_units Java 预览 | 工作树：effective candidates | 硬约束 + 学费 | 无（用户精确点名） | dry-run solver（target=current+delta） | frozen 执行：count/zero-remove/review |
| add_units agent 工具 | agent `plan/candidates.json` | agent 侧解析 | 无 | 无 Java 预览 | legacy 执行：无专门后置 |
| refill | effective candidates | 硬约束 + 学费 | 池内顺序 | 无 | 无 |
| review | effective candidates | 硬约束 + 学费 | 按 ordered 顺序检查 | 无 | review 自身 |
| review fix | effective candidates | 硬约束 + 学费 | `RepairCandidateSelector` / dry-run | 无 canonical solver | repair report + postValidation |

**一句话**：候选源有 3 套，过滤有 4 套，排序键有 5 套，求解有 2 套（canonical solver / 贪心启发式），后置校验有 4 套（canonical validator / add frozen / add legacy / repair report）。

---

## 五、用户意向到底落在哪一层

| 意向 | 当前载体 | 当前层级 | 生成 | 补全 | 加入 | 一致性问题 |
|---|---|---|---|---|---|---|
| 正向专业 | `UserProfileData.major_intent` / planning `coverage major` / `requirements` | 软：rank 加权；硬：planning 硬约束/覆盖 | 用 effective（硬约束），rank 分 | 用 projected hard + coverage | 用 effective | rank 的 `major_score_new` 与 coverage 的 `majorCategory/majorDiscipline` 是两套匹配；正向专业在推荐池只加分不过滤（`VolunteerFilterChain` 的 major 过滤被注释，`369-385`） |
| 负向专业 | `negative_major_intent` / `mustExcludeMajors` | 软：rank 减分；硬：planning exclude | 同上 | 同上 | 同上 | 推荐池不过滤负向专业，只在 rank 里乘 0.1/0.3（`recommendation.py:806-821`）；planning 才硬排 |
| 地域（省/市） | `city_info` / `negative_city_info` / `mustIncludeRegions` / `mustExcludeRegions` | 软：rank 加减分；硬：planning 硬约束；展示：视图过滤 | 同上 | 同上 | 同上 | `VolunteerFilterChain` 的正/负地域过滤方法存在但**未调用**（`369-385` 注释，`572-602` 定义）；推荐池只靠 rank 调分，负向地域不会从池里删除 |
| 院校 / 院校层次 | `college_info` / `school_level` / `school_nature` / tags | 软：rank 院校分；硬：planning school/level 匹配；展示：视图 | 同上 | 同上 | 同上 | 层次主要靠 rank 的 level_score 与 futureDev；`school_level` 作为覆盖要求时才成为 solver 约束（`CoverageRequirementSupport.java:184-191`） |
| 学费 | `userScoreDetail.tuitionRange` / `tuition_budget_scope` | 硬：候选池生成过滤 + effective candidates；一次性：scope 替换 | 用 effective（含学费） | **不用 live 学费**（只用池快照） | 工作树用 effective（含学费）；agent legacy 用 effective select | 学费更新不标记候选池 stale（`ChatSessionBizService.java:216-245`）；fill/scope 与 effective 口径不一致 |
| 风险偏好 / 冲稳保策略 | `userScoreDetail.strategyType`；`derivedPreferences.riskTolerance` | 结构：strategy 只影响 `calculateTargetCounts` 比例；`riskToleranceInferred` 硬编码 `medium` 且未被消费 | 初始桶目标来自 pool requiredTierCounts | 只有显式 tierQuota 才进 solver | 同 | 没有“风险偏好”到 solver/安全目标的映射；`safety_guard` 只在分数 < 580 时生效（`3834`、`10821`） |
| 职业 / 发展方向 | `latentProfile.futureDevelopment.careerTypes` → `derivedPreferences.employmentOrientationInferred` | 软：仅当含“体制内/考公”时 `futureDevelopmentScore` 生效（`PlanningStateService.java:9693-9743`） | 初荐 comparator 的 tiebreak | 不影响 fill solver | 不影响 add | 职业意向不进入 canonical objective；非“体制内/考公”的职业方向完全不参与选择；review 也不检查 career 匹配 |
| 目标总数 / 冲稳保配额 | `hardPlanningObjectives.selectionTargetCount` / `tierQuotaGoal` | 硬：solver target/tier bounds | `enforceSelection` | objective set | add `targetCountOverride` / tier quota 阻断 | 初始桶目标用 pool requiredTierCounts，不是 selectionTargetCount；review 配比也用 pool requiredTierCounts |
| 覆盖要求（至少 N 个地域/专业/院校/层次） | `hardPlanningObjectives.coverageRequirements` | 硬：solver coverage lower bound | `enforceSelection` | objective set | dry-run 用同一 coverage | scope 的 `must_include_scope` 不持久化为 coverage；review 只按请求 requirements 判，不读已确认 coverage 的完整集合（`populateRequirements` 只看 `userGoal.getRequirements()`，`UnifiedPlanPostconditionValidator.java:197-247`） |
| 同档优先 | `priorityRules` | 排序：solver 后处理 + postcondition | `enforceOrdering` | objective set | 无（add 不涉及） | 只支持 include 语义、只支持一条规则；priority 命中的是“候选事实”，不是“用户原话” |

**总判断**：用户意向没有统一的生命周期。硬约束（planning constraintState）是持久的；范围/学费/职业大多是一次性或仅展示；rank 分是另一套软偏好。生成/补全/加入各自读取其中一部分，因此“用户说过的同一句话”在不同动作里可能产生不同结果。

---

## 六、“整体结构最优”当前实际优化了什么

| 结构维度 | 当前落点 | 证据 |
|---|---|---|
| 目标总数 | 硬约束：solver `selection_target` | `OjalgoDeterministicPlanSolver.java:121-124` |
| 冲稳保配比 | 硬约束：solver tier bounds（仅显式 tierQuotaGoal）；启发式：初荐按 requiredTierCounts 分桶 + rebalance；review：占比阈值 | `OjalgoDeterministicPlanSolver.java:137-142`；`PlanningStateService.java:3444-3470`；`10707-10784` |
| 覆盖 | 硬约束：coverage lower bound | `OjalgoDeterministicPlanSolver.java:125-136`；`CoverageRequirementSupport.java:45-65` |
| 梯度（邻接录取率） | 启发式：初荐倒挂/断层修复；review：诊断 | `PlanningStateService.java:3870-3916`；`10874-11034` |
| 保底（本省保底） | 启发式：分数 < 580 时 2 个本省“保”；review：诊断；solver 无 | `PlanningStateService.java:3834-3868`；`10810-10872` |
| 去重 / 单元完整性 | solver entity 粒度 + 工作集同步；专业组 completion 在初荐构建单元时处理 | `CanonicalPlanningRuntime.java:409-428`；`PlanningStateService.java:4784-4820,4950-5040` |
| 地域多样性 | **无** | 无覆盖要求/无目标函数项 |
| 专业多样性 | **无** | 同上 |
| 院校层次多样性 | 只有显式 school_level 覆盖要求；否则无 | `CoverageRequirementSupport.java:169-201` |
| 分数/推荐分 | **不在 solver 目标**；只作为 stableOrder/ comparator | `OjalgoDeterministicPlanSolver.java:38-39, 106-108`；`CanonicalPlanningRuntime.java:648-655` |
| 录取率/风险 | 启发式排序/修复 + review；solver 无 | `VolunteerSorterAndMerger.java:275`；`PlanningStateService.java:12969-12997` |
| 改动成本（churn） | solver 主目标（1e12） | `OjalgoDeterministicPlanSolver.java:38,107-108` |
| 结构偏差（相对当前档位分布） | solver 次目标（1e6） | `OjalgoDeterministicPlanSolver.java:39,265-292`；`TierStructureProjection.java:17-77` |
| 优先规则 | solver 结果后的 within-tier 重排 + 逆序校验 | `OjalgoDeterministicPlanSolver.java:310-350,391-403`；`CanonicalPlanningRuntime.java:80-122` |

**结论**：

- solver 是一个**约束满足 + 最小改动 + 历史结构锚定**器，不是“整体最优”器。它的“结构”只到档位数量/覆盖下限；没有梯度、保底、多样性、分数最大化的目标项。
- 初荐启发式确实追求“配比 + 安全 + 梯度”，但它发生在 solver 之前，且只在没有已确认目标时是最终结构；有目标时 solver 可以推翻它。
- review 是事后诊断，不是优化器；`ratio_distribution` 还使用错误的档位期望来源。
- 报告里的权重（`tier_structure 0.24` 等）不是求解权重，不能作为“系统在加权优化”的证据。

---

## 七、不一致 / 断层 / 风险清单

> 严重度：**P0** = 会产生错误方案或用户可见的矛盾；**P1** = 语义不一致/可导致失败或返工；**P2** = 可维护性/解释性问题。

### P0

1. **两套 add_units 入口，agent 工具路径绕过 Java 预览与 frozen 后置。**
   - `preview_plan_action(add)` 只在 agent 侧建 pending（`tools.py:10557-10623`，`10869-10890`），没有 Java `targetCountOverride`/dry-run/tier quota 校验。
   - Java 执行只有 pending 带 `frozenCommand` 才走严格路径（`PendingPlanningCommandBizService.java:215-229`）；agent 自建 pending 没有 `frozenCommand`，落 legacy（`230-244`），无目标/覆盖/档位/零删除后置，也不重跑审查。
   - gateway 的 `proposalRequest(add_units)` 走 `prepare`（`gateway/service.py:2874-2884`），会写 `frozenCommand`（`PlanningStateService.java:931-952`）——两条入口安全性不同。
2. **scope 目标不持久化，应用后可能被 solver/重生成撤销。**
   - `applyUserGoalTargetToPlanningState` 只持久化 requirements/priority/tier/selectionTargetCount（`1075-1111`），不持久化 targetScopes。
   - `saveAndRefreshAfterFixApply` 会调用 `generateOrderedPlan`（`1291-1296`），后者在有 selection objectives 时 `enforceSelection`（`CanonicalPlanningRuntime.java:40-62`），可以为了目标数重新加入范围外候选。
3. **fill 与 effective candidates 的学费口径不一致。**
   - `resolveEffectiveCandidates` 含会话学费过滤（`PlanningStateService.java:9580-9593`）；fill 的 `selectFillCandidates` 只用 `projectedHardConstraints`（`UserGoalProposalBuilder.java:1254-1258`），不含 live 学费。
   - `updateTuitionRange` 不标记候选池 stale（`ChatSessionBizService.java:216-245`），旧池可能继续被 fill 使用。
4. **review 的档位配比使用 `candidatePool.requiredTierCounts`，不读用户确认的 `tierQuotaGoal`。**
   - `expectedTierCount` 只读 requiredTierCounts 并按 selectionTargetCount 缩放（`PlanningStateService.java:10791-10807`）。
   - 用户设置自定义档位目标后，review 可能给出与 solver 目标相反的“配比正常/异常”。

### P0/P1

5. **canonical 后置校验的 coverage 报告与冻结目标不同源，可能直接 40905。**
   - 编译期 coverage 是“已确认 coverage + 本轮 include 要求”，并按身份排序（`PlanningObjectiveCompiler.java:174-197,218-225`）；solver 的 `objectiveResults` 用 `coverage:index` 顺序输出（`OjalgoDeterministicPlanSolver.java:367-371`）。
   - 后置报告只遍历 `userGoal.getRequirements()`（`UnifiedPlanPostconditionValidator.java:197-247`），**不回落已确认 coverage**；而 priority 明确做了回落（`259-268`）。
   - `validateCanonicalObjectiveResults` 要求冻结结果的每个 objective 在报告里有同 id/同 min/同 actual/同 satisfied 的项（`456-487`）。
   - 后果（推断，未构造用例）：已确认 coverage 未在本轮 request 重复、或本轮有 ≥2 条 include 且排序与身份序不一致时，报告与冻结结果对不上，fill 应用会 `40905 frozen objective result mismatch`。这与 2026-10-16 修复的 priority 回落是同一类问题，coverage 侧尚未修。
6. **候选源三套，过滤四套。** 候选池/预览、initial/refill/review、fill、scope、add 工具各自取不同集合（见第四节表）。用户看到的候选、能加入的候选、能补入的候选不是同一个集合。
7. **排序键五套。** rank `volunteer_score`（`recommendation.py:1041-1049`）、水位线 `schoolEnrollRatio`（`VolunteerSorterAndMerger.java:275`）、初荐 `finalScore` 优先（`3755-3766`）、fill `intentScore` 优先（`3045-3052`）、solver `intentScore → finalScore` 稳定序（`CanonicalPlanningRuntime.java:648-655`）。同一候选在不同路径中的“好坏”排序不同。
8. **solver 不优化候选质量。** 权重只有 churn 与结构偏差（`OjalgoDeterministicPlanSolver.java:38-39`）；分数只通过 `stableOrder` 影响结果。对“从候选里找合适的志愿”这个目标，solver 目前只保证“合规、少改、档位像原来”，不保证“选得更好”。
9. **候选池无上限，但 solver 有 600/64 硬帽，且只有 fill 做输入截断。**
   - `MAX_CANDIDATES=600`、`MAX_COVERAGE_CONSTRAINTS=64`（`OjalgoDeterministicPlanSolver.java:34-35`）。
   - `CanonicalPlanningRuntime.enforceSelection` 把所有 available 候选直接送 solver（`51-59`，`377-391`），没有截断。
   - fill 的 `capSolverCandidatePool` 只截 fill（`UserGoalProposalBuilder.java:1236-1242`）。
   - 候选池是全量（3.1），因此大池 + 已确认目标时 initial/fill 之外的路径可能直接 `solver_complexity_limit`。
10. **`fill_to_count` 的当前方案投影只用本轮 requirements，不含已确认硬约束。**
    - `projectCurrentPlan` 的第二个参数是 `project(null, req.requirements)`（`UserGoalProposalBuilder.java:669-670`），不是 `project(state, req.requirements)`。
    - 当前方案若有违反已确认硬约束的项，fill 可能保留到后置校验才失败。
11. **add_units Java 预览直接阻断已确认 tierQuotaGoal。**
    - `buildAddUnitsProposal` 在 `hard.tierQuotaGoal != null` 时 blocked（`UserGoalProposalBuilder.java:245-251`），尽管 dry-run 已经能把 tier constraint 放进 solver（`528-536`）。这会让“有档位目标时点名加入”永远不可用，属于能力缺口而非真实不可行。
12. **review 与生成不闭环。**
    - 只有显式 `rerunReview` 才重跑；add legacy 路径不重跑（`PendingPlanningCommandBizService.java:230-244`）。
    - 每次 plan save 都 `markPlanStructureStale`（`PlanningStateService.java:13578-13595`），review 很快过期。
    - review 修复使用独立 `RepairDryRunSimulator`/`RepairApplyMutationBuilder`，不是 canonical solver（`RepairDryRunSimulator.java:33-160`）。
13. **最初方案的“结构修复”与 review 的判据不完全同源。**
    - 初荐 gap 修复按全局录取率排序（`4553-4586`）；review 按 ordered 相邻项（`10934-11034`）。
    - 初荐 safety 修复只在分数 < 580（`3834`）；review 同阈值（`10821`），但两者对“本省保底”定义都用省份名包含判断（`containsIgnoreCase`）。
14. **`must_include_scope` 不是“至少保留”的持久约束。**
    - 当前方案已有 → info，不生成动作（`1707-1715`）；方案满时只替换 1 组（`1722-1740`）；否则只展示 1 条候选（`1742-1747`）。这不是覆盖要求，下一次重生成可能丢失。
15. **职业意向只在“体制内/考公”时生效。**
    - `buildFutureDevelopmentSignals` 仅在 derived orientations 含“体制内/考公”时启用（`9693-9706`）；其他 careerTypes 只存在于 profile，不进入选择。用户说“想做产品经理/科研”不会改变方案。
16. **`riskToleranceInferred` 硬编码 `medium` 且无人消费。**
    - `PlanningStateService.java:9313`。风险偏好没有真实的方案层表达。
17. **`add_units` 的 targetCount 语义不统一。**
    - Java 预览要求当前数 == 已确认目标（`341-347`），然后 `targetAfter = current + added` 并写 `targetCountOverride`（`348-349`）；执行时 `updateSelectionTargetCount(override)`（`PendingPlanningCommandBizService.java:380-383`）。
    - agent legacy 路径不写 override，执行只 select + 重排（`230-244`），方案会“静默变长”。
    - 需要产品决策：加入是“显式扩大目标”还是“必须替换”；当前两条路径默认不同。
18. **候选预览/查询不展示硬约束/学费不合格原因。**
    - `CandidatePreviewService` 只做视图过滤（`183-206`），不调用 `RepairCandidateEligibility` 或学费过滤。
    - `queryCandidatePool` 同样（`PlanningStateService.java:2144-2158`）。
    - 用户可能在预览里看到候选，点名加入后被执行侧拒绝（40905/add target_not_found）。
19. **未知录取率候选被静默丢弃。**
    - `VolunteerIntervalService.divideVolunteers` 把无效 ratio 放 `未知`（`42-58`），`VolunteerSorterAndMerger.sortEveryInterval` 过滤掉 `未知`（`109`）；池的 `sourceSummary` 是否记录这部分取决于 `populateCandidatePoolSourceSummary`，但没有面向用户的 limitations 语义。候选池总数会无故变小。

### P2

20. **报告权重与求解权重分离但未标注。** `buildInitialPlanObjectiveWeights`（`3156-3202`）是解释文案，和 solver 权重无关；建议改名为“解释权重”或直接展示 solver 目标。
21. **`rank_in_tier` 与列表顺序不同源。** `VolunteerResponseBuilder.markPreferredSchools` 按 `volunteer_score` 排名（`147-170`），合并列表却按 `schoolEnrollRatio` 排序（`VolunteerSorterAndMerger.java:275`）。前端若同时展示“第 N 名”和列表顺序会困惑。
22. **`isCompensationSafeCandidate` 是另一套硬规则。** 学费 > 20000、中外合作、专项/公费/定向/强基、单科/语种/性别、blocking risk flag 都在这里被排（`RepairCandidateSelector.java:894-911`），与 `VolunteerFilterChain` 的过滤不完全重合；fill/scope 都额外套这一层，initial 不套。
23. **`priority` 只支持一条规则、只支持 include 语义。** `PlanningObjectiveCompiler.validateRequest` 对多条规则/组合有阻断（`116-130`），`PriorityRuleSupport.matches` 只构造 include matcher（`221-229`）。

---

## 八、目标架构建议：一个“候选 → 方案”骨架

### 8.1 设计原则

1. **单一事实来源**：一个会话版本一个候选快照；所有预览、生成、补全、加入、审查读同一份 `CandidateFact`，不再各自 flatten/过滤。
2. **意图分层且可持久**：硬约束、覆盖要求、结构目标、排序规则、软偏好、仅展示，六类明确；默认持久，一次性动作必须显式标记。
3. **所有动作都是 objective delta**：生成 = 从空方案开始；补全 = 在现有方案上增加目标/约束；点名加入 = 精确实体作为“必须选中”的 lower bound + 目标数增量；范围调整 = 硬/覆盖/软偏好的 delta；refill = 目标数/档位/覆盖 delta。它们不各自实现选择算法。
4. **求解与启发式分工明确**：solver 负责硬约束 + 结构 + 软效用；启发式只负责候选预排序、稳定序、和 solver 不可用时的显式降级（降级必须可见）。
5. **后置条件统一**：所有动作执行后过同一个 validator；不满足就回滚，不允许“satisfied=true”的自定义报告绕过。
6. **审查是同一指标向量上的诊断**：review 不另起一套选择/修复目标；review fix 也编译成 objective delta。
7. **可解释回执**：每份方案/提案都带 objective results、结构指标、tradeoff、reason codes；用户能看懂“为什么是这些”。

### 8.2 五层模型

```
Layer 0  CandidateSnapshot
  - sourceDigest / dataVersion / volunteerModel / requiredCount
  - CandidateFact[]:
      id, unitId, school/major identity, region ids/names, school level/nature/category,
      tier, subTier, schoolEnrollRatio, admissionRatio, planNum, tuition,
      baseScore, intentScore, finalScore, futureDevScore, hotIndex, salaryAvg,
      mustSubjects, tags, riskFlags, reasonCodes
  - 每候选派生:
      eligibility(confirmedIntents) + eligibilityReasonCodes
      coverageKeys: region|province|city, major|category|discipline, school|level|nature|tag,
                    admission|tier, tuition|budget
      utilityComponents: quality, preferenceMatch, safety, futureDev, cost
      tierSource: school_ratio | explicit
      admissionRatioSource: school | major

Layer 1  IntentModel（会话级，带生命周期）
  - HardEligibility: exclude/only_keep（区域/院校/专业/层次/性质/招生类型/学费上限）
  - Structural: targetCount, countMode, tierAllocation{exact|range|ratio},
                coverageRequirements[{domain,key,values,minCount}], dedupe, unitCompleteness
  - Ordering: priorityRules[{domain,key,values,rank_before,within_tier}], gradientPolicy,
              pinned/locked
  - SoftPreference: weights{quality,preference,safety,futureDev,cost,diversity},
                    region/school/major level preferences, riskTolerance, careerOrientation
  - DisplayOnly: review notices, explanations
  - Lifecycle: scope=session|once|display; persist=true|false; source=user|inferred

Layer 2  ObjectiveCompiler
  - compile(IntentModel, actionDelta) -> CanonicalPlanningObjectiveSet
  - 所有 action 共用；add/scope/refill 的新增字段进入同一 schema
  - digest 覆盖 weights/actionPolicy

Layer 3  SelectionSolver（唯一选择器）
  - 输入: CandidateFact[], currentPlan, objectiveSet, mutationPolicy
  - 字典序:
      1) hard feasibility (eligibility, count, tier bounds, coverage, locks, pinned)
      2) structural deviation (tier anchor / target)
      3) mutation cost (churn; add policy = no-removal)
      4) soft utility (quality/preference/safety/futureDev/cost) 
      5) diversity penalty (optional, only if user asks / configured)
      6) stableOrder tie-break
  - 候选超帽: 两阶段（先覆盖代表，再按 utility 截断），回执 droppedCount/coveragePreserved

Layer 4  Ordering
  - within tier: priorityMatched first → gradient (admissionRatio ascending) → localProtect
                 → utility → pinned
  - unit mode: 单元内专业排序 + 单元间用 schoolEnrollRatio；组内 safety 单独标记

Layer 5  Postcondition + Receipt + Review
  - 同一个 validator: count/tier/coverage/priority/locks/pinned/no-removal policy/digest
  - 同一个 StructureVector 报告
  - review = 在同一 StructureVector 上跑规则，不再有自己的选择器
```

### 8.3 统一候选事实：`CandidateFact`

建议在现有 `CandidateItemDTO` 上补三类派生字段（不一定落库，可在快照构建时计算）：

```java
class CandidateFact extends CandidateItemDTO {
    boolean eligibleForConfirmedIntents;
    List<String> eligibilityReasonCodes;     // hard_region_excluded, tuition_over_budget, subject_mismatch...
    Set<String> coverageKeys;                // "region:北京", "major:计算机类", "school_level:双一流", "tier:冲"
    Map<String, Double> utility;             // quality, preference, safety, futureDev, cost
    String tierSource;                       // school_ratio / explicit
    String admissionRatioSource;             // school / major
    int stableOrder;
}
```

关键点：

- **eligibility 与 visibility 分开**：候选池查询/预览默认返回全部候选，但带 `eligible` 与原因；`includeIneligible=true` 才展示不合格项。这样“候选池有多大”和“能进方案的候选有多少”不再混淆。
- **coverageKeys 统一由同一个函数生成**：`CoverageRequirementSupport` 与 `RepairCandidateEligibility` 的匹配规则必须同源，不能一份用名字子串、一份用 ID。
- **utility 的每个分量都要有来源**：quality=`finalScore/intentScore` 归一化；preference=rank/profile 命中；safety=`admissionRatio` 与保底；futureDev=现有 `futureDevelopmentScore`；cost=学费/中外合作/专项风险。不要在 solver 里现算。

### 8.4 六类意向的统一表达

| 用户说法 | 统一表达 | solver 处理 |
|---|---|---|
| “不要民办/不去外地/不接受中外合作” | `HardEligibility.exclude` / `only_keep` | 候选预过滤 + solver eligibility=0 |
| “至少 N 个北京/至少 2 个计算机类/至少 1 个 985” | `Structural.coverageRequirements` | coverage lower bound |
| “总共 45 个，冲 10 稳 20 保 15” | `Structural.targetCount` + `tierAllocation` | selection_target + tier bounds |
| “保底要本省、要公办” | 若可判定：Hard/coverage；否则 `SoftPreference.safety` | 硬约束或 utility 权重 |
| “优先计算机/优先北京/优先 985” | `Ordering.priorityRules` + `SoftPreference.preference` | within-tier 排序 + utility |
| “更看重就业/想考公/能接受高学费” | `SoftPreference.futureDev/cost/riskTolerance` | utility 权重 |
| “先看看/只是参考” | `DisplayOnly` | 不参与选择；只回执 |

**生命周期建议**：

- 用户明确说“以后都按这个/加入偏好”→ `persist=true`，进 `ConstraintState`/`ProfileState`。
- 用户说“这次只看/这次先这样”→ `persist=false`，提案卡必须写“仅本次生效”。
- scope/tuition/career 不能既不在 constraintState 也不标记 once，否则就是当前“应用后消失”的断层。

### 8.5 solver 目标函数建议

在现有 `OjalgoDeterministicPlanSolver` 上做最小扩展，而不是重写：

```
weight(entity) =
    current ? -CHURN_WEIGHT + stableOrder : CHURN_WEIGHT + stableOrder
  - UTILITY_WEIGHT * normalizedUtility(entity)
  + DIVERSITY_WEIGHT * concentrationPenalty(entity)
```

约束层保持：

- `selection_target = targetCount`（硬）
- `tier:<tier>` lower/upper（硬）
- `coverage:<id>` lower（硬）
- `locked` lower=1/upper=1
- `pinned` 由后置排序保护

建议权重层级（数值仅为示意，落地时统一为整数并写入 digest）：

- 硬约束：不可违反（solver 前过滤 + 约束表达式）
- `CHURN_WEIGHT`：保持现有量级，确保“少改”优先于“更好”
- `STRUCTURE_DEVIATION_WEIGHT`：保持现有量级，确保档位结构优先于软效用
- `UTILITY_WEIGHT`：新加，量级远小于结构偏差，保证只在结构相同/相近时选更好的候选
- `DIVERSITY_WEIGHT`：可选；默认 0，用户明确要“专业/地域多样性”时开启

**不要**把梯度/倒挂做成 solver 的硬约束（非线性、易不可行）；把它们做成：

- 候选预排序（gradient-friendly stableOrder）；
- 后置排序（within-tier admissionRatio ascending）；
- 结构化指标 + review 诊断；
- 若确实要优化，可用线性化的相邻变量/罚项，但这是第二阶段。

### 8.6 生成 / 补全 / 加入 / 范围调整的统一命令

```java
enum PlanAction { GENERATE, FILL, ADD, SCOPE, REFILL, REVIEW_FIX }

class PlanCommand {
    PlanAction action;
    IntentDelta delta;              // 新增/修改的硬约束、覆盖、目标、排序、软偏好
    MutationPolicy policy;          // allowRemove, allowReplace, lockExisting, growTarget
    Integer sourceVersionGuard;
}

PlanResult execute(PlanCommand cmd):
    ctx = loadPlanningContext(session)
    facts = ctx.candidateSnapshot.annotate(ctx.intentModel)   // 同一份
    objective = ObjectiveCompiler.compile(ctx.intentModel, cmd.delta)
    input = SolverInput(facts, ctx.currentPlan, objective, cmd.policy)
    result = SOLVER.solve(input)
    if result.blocked:
        return Diagnostic(result)          // 不落盘，不静默 fallback
    applySelection(ctx.currentPlan, result, cmd.policy)
    ordered = OrderWithinTiers(ctx.currentPlan, objective, facts)
    report = POSTCONDITION.validate(ordered, objective, result, cmd.policy)
    if !report.satisfied:
        rollback(); return Diagnostic(report)
    review = REVIEW.run(ordered, objective, facts)   // 同一指标向量
    return Receipt(result, report, review, StructureVector)
```

各动作只改 `delta` 与 `policy`：

| 动作 | delta | policy |
|---|---|---|
| GENERATE | 会话已确认 intent（target/coverage/tier/priority） | `currentPlan=empty`, allow full selection |
| FILL | 本轮 requirements/tierQuota/priority；targetCount | `lockExisting=true`, `allowRemove=only violations`, `allowReplace=true` |
| ADD | `requiredEntities=exactTargets`, `targetCount += addedCount` 或显式 override | `lockExisting=true`, `allowRemove=false`, `allowReplace=false` |
| SCOPE | `only_keep/exclude/must_include` → hard/coverage；tuition → hard cap；soft preference | `allowRemove=scope violations`, `allowReplace=true`, `persist` 按生命周期 |
| REFILL | 目标数/档位/覆盖（只补不删） | `lockExisting=true`, `allowRemove=false` |
| REVIEW_FIX | 把 review issue 转成 objective delta（例如 coverage/replace/remove） | 由 fix 策略决定 |

### 8.7 结构最优的度量：`StructureVector`

建议每个方案/提案/审查都输出同一个向量（便于 A/B、回归、解释）：

| 维度 | 指标 | 目标 |
|---|---|---|
| 数量 | actualCount, targetCount, delta | 0（或显式 override） |
| 档位 | sprint/stable/protect actual vs bounds; 偏差和 | 0 / 最小 |
| 覆盖 | 每个 coverage requirement 的 actual/min | 全部 ≥ min |
| 梯度 | adjacentInversionCount, gapCount(>8), maxGap | 0 / 0 / 最小 |
| 保底 | localProtectCount（保 + 本省） | ≥ 2（分数 < 580 时） |
| 安全 | 最低 3 条 admissionRatio、保区占比 | 不低于阈值/不低于基线 |
| 质量 | mean/median finalScore、intentScore、preferredMatchRate | 最大化（软） |
| 成本 | 高学费/中外合作/专项数量、平均学费 | 最小化（软） |
| 多样性 | 省/市/专业类/院校层次的熵或覆盖数 | 用户要求时最大化 |
| 改动 | added/removed/changed | 最小化（churn） |
| 风险 | riskFlags 命中数、review block/action 数 | 0 / 最小 |

**“结构最优”定义建议**：

> 在满足全部硬约束（资格、数量、档位、覆盖、锁定/固定）的前提下，使档位偏差最小、梯度无倒挂/断层、保底达标、软效用最大、改动最小；多样性只在用户明确要求时作为次级目标。

不要把它压成一个不透明的总分；保留向量 + 一个可配置的标量用于排序/回归。

### 8.8 审查闭环

- review 只读 `(objectiveSet, orderedPlan, facts)`，输出同一 `StructureVector` + issue list。
- 每个 apply（fill/add/scope/refill）默认 `rerunReview=true`（或至少在回执里标注 review stale）。
- review fix proposal 也编译成 `PlanCommand(REVIEW_FIX, delta, policy)`，走同一 solver/postcondition；不再单独维护 `RepairDryRunSimulator` 的目标判断（可保留其质量指标作为回执）。
- `ratio_distribution` 必须优先读 `tierQuotaGoal`（若有），否则读 requiredTierCounts；与 solver 同源。

---

## 九、实施顺序与验收标准

### 阶段 0：基线与度量（0.5-1 天）

**改动**：只加观测，不改行为。为现有生成/fill/add/refill/review 输出 `StructureVector` 快照；选 5-10 个 golden 会话（含大池、专业组、已确认 tierQuota、scope、add、学费变更）记录当前结果。

**验收**：
- 同一输入重复跑，selected/ordered IDs 与 digest 稳定（solver 确定性）。
- 每个 golden 场景都有结构向量基线；后续阶段可 diff。

### 阶段 1：统一候选事实与 eligibility（P0，2-3 天）

**改动**：
1. 抽出 `CandidateSnapshotBuilder`（或复用 `buildCandidatePoolStateFromResponse`）生成带 eligibility/coverageKeys/utility 的 fact；所有路径只读它。
2. 候选查询/预览返回 `eligible` + `eligibilityReasonCodes`，默认包含不合格项（可切换）；不再静默隐藏。
3. fill/scope 改用 effective candidates（含 live 学费）；`updateTuitionRange` 标记候选池/规划 stale。
4. add agent 工具路径改为调用 Java `user-goal/prepare`（或至少调用同一 Java 预览），禁止自建无 frozen 的 add pending。

**验收**：
- 同一会话、同一版本，`preview_candidates` / `fill` / `add` / `initial` 的候选集合 digest 一致（允许动作 delta 导致的 required/available 差异，但基础事实一致）。
- 学费更新后，fill/scope/initial 都不再选到超预算候选。
- add 工具路径确认执行时能命中 `frozenCommand`（或明确走 legacy 且回执标注“无严格后置”）；有 tierQuota 时不再无条件 blocked，而是由 solver 判定。

### 阶段 2：统一 objective compiler（P0/P1，3-5 天）

**改动**：
1. 把 add/scope/refill 编译成 `CanonicalPlanningObjectiveSet` 的 delta：
   - add：required entities（lower=1，locked/不可删）+ targetCount 增量；
   - scope：only_keep/exclude → hard；must_include → coverage；tuition → hard cap；
   - refill：target/tier/coverage，lockExisting/no remove。
2. 所有动作调用 `CanonicalPlanningRuntime.enforceSelection`/`enforceOrdering`，删除 `UserGoalProposalBuilder.buildAddUnitsProposal` 里的独立 dry-run 选择逻辑（保留调用 solver 的 dry-run，但输入来自统一 compiler）。
3. scope 目标持久化（带 lifecycle）；`applyUserGoalTargetToPlanningState` 统一持久化所有 delta。

**验收**：
- 生成/fill/add/refill 对同一 intent delta 选出同一集合（在相同 currentPlan 下）。
- scope 应用后重新生成方案，范围不被撤销。
- add 在已确认 tierQuota 下可由 solver 给出可行/不可行诊断，而不是一律 blocked。

### 阶段 3：solver 软效用与候选帽（P1，3-5 天）

**改动**：
1. 加 `UTILITY_WEIGHT` / 可选 `DIVERSITY_WEIGHT`；utility 来自 fact，权重写入 objective digest 与回执。
2. 统一候选截断：两阶段（coverage 代表 + utility 头部），所有路径共用；回执 `candidate_cap_applied`、droppedCount、coveragePreserved。
3. 保持 churn/结构偏差的优先级；软效用不得压过结构/少改。

**验收**：
- 在 golden 场景上，结构指标不劣于基线，quality（mean finalScore/intentScore）不低；
- 大池（>600）不再因复杂度直接 blocked；截断有诊断；
- 同输入确定性不变。

### 阶段 4：统一后置条件（P1，2-3 天）

**改动**：
1. 所有动作走 `UnifiedPlanPostconditionValidator`：
   - count / tier bounds / coverage / priority / locked / pinned / no-removal policy / objective digest；
   - add 的 no-removal 是硬条件；legacy 路径要么补齐后置，要么禁止。
2. 删除 add frozen 的 `satisfied=true` 自定义报告（或让它由统一 validator 生成）。
3. refill/scope 增加后置校验。

**验收**：
- 任何动作不满足后置都会回滚并返回结构化诊断；
- add 请求的每一条都在最终方案，现有条目零删除；
- 回执的 objective results 与 solver result 一致。

### 阶段 5：审查闭环（P1/P2，2-3 天）

**改动**：
1. review 读 `tierQuotaGoal`（若有）而不是只读 requiredTierCounts；
2. 每次 apply 默认 rerun review；回执含 review 结果/stale 标记；
3. review fix 编译成 objective delta，复用统一 solver；
4. review 增加多样性/层次覆盖/职业匹配（作为 notice/action，不默认硬约束）。

**验收**：
- review 的配比结论与 solver tier bounds 一致；
- apply 后 review 不再是 stale；
- review fix 与 fill 对同一目标给出相同集合（在相同 delta 下）。

### 阶段 6：解释与清理（P2，2 天）

**改动**：
1. 报告权重改名为“解释权重”，或替换为 solver 目标；
2. 统一 `rank_in_tier` 与列表顺序的语义（要么都按 score，要么明确“推荐排名”与“填报顺序”两个字段）；
3. 清理 `isCompensationSafeCandidate` 与 filter chain 的重复规则，抽成共享 eligibility predicate；
4. 文档化“一次 vs 持久”的意向规则。

**验收**：
- 用户可见文案不再把解释权重说成优化权重；
- 前端“第 N 名”和列表顺序有明确说明；
- filter/fill/scope 的硬规则只有一份实现。

---

## 十、代码证据 vs 推断

### 有代码证据（file:line）

- 候选池全量、未知档位丢弃、水位线排序、15 候补：
  `VolunteerSorterAndMerger.java:51-91,109,232-327`；`VolunteerIntervalService.java:42-58`；`CandidatePreviewService.java:47,100,144-147`。
- 初始方案启发式：`PlanningStateService.java:3016-3112,3429-3473,3755-3831,3834-3944,4718-4725,4909-4935`。
- solver 权重/约束：`OjalgoDeterministicPlanSolver.java:34-40,100-179,265-292,310-350`。
- fill 候选/排序/截断：`UserGoalProposalBuilder.java:614-950,1236-1320,1354-1381,3045-3052,3387-3438`。
- add_units Java 预览/执行：`UserGoalProposalBuilder.java:231-390,517-582`；`PlanningStateService.java:931-952`；`PendingPlanningCommandBizService.java:207-244,365-476`。
- add_units agent 工具：`tools.py:6799-6845,10557-10623,10869-10890,8146-8178`；`internal_client.py:1220-1242,1855-1857`。
- 审查检查/配比来源：`PlanningStateService.java:2847-2908,10707-11131,11489-11565`。
- 意向过滤/排序：`VolunteerFilterChain.java:27-79,84-211,221-268,273-399,436-494,540-567`；`recommendation.py:301,468-479,562-596,806-837,1014-1049`。
- 硬约束/覆盖匹配：`RepairCandidateEligibility.java:31-48,81-115,152-165,323-435`；`CoverageRequirementSupport.java:45-65,156-177`。
- 后置校验差异：`UnifiedPlanPostconditionValidator.java:47-105,118-159,197-247,298-353,368-400,505-539`；`PendingPlanningCommandBizService.java:230-244,465-474`。
- 学费更新不标 stale：`ChatSessionBizService.java:216-245`。
- 分数来源：`PlanningStateService.java:9320-9378`；`VolunteerRecommendBuilder.java:629-705`；`recommendation.py:1041-1049`；`VolunteerDataTransformService.java:58,171`。

### 推断（无直接代码证据/未实测）

- 大池 + 已确认目标时 initial/fill 之外的路径可能命中 `MAX_CANDIDATES` 阻断：这是从 `MAX_CANDIDATES=600`、`enforceSelection` 无截断、候选池全量三件事推出的**风险**，未构造真实大池验证。
- scope 应用后被 solver 撤销：从“scope 不持久化 + saveAndRefresh 调 generateOrderedPlan + enforceSelection 可选人”推出；是否实际发生取决于当前方案/目标是否触发 solver。
- 两条 add 入口的实际线上分布：从代码路径推出，未统计调用量。
- “用户感知不一致”是设计推断，不是用户访谈数据。
- 性能/超时：未测；solver `TIME_ABORT_MS=2000` 是代码常量，不代表真实耗时。

---

## 十一、关键代码索引（便于复核）

- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/VolunteerBizService.java`
- `.../VolunteerDataProvider.java`
- `.../VolunteerFilterChain.java`
- `.../VolunteerSorterAndMerger.java`
- `.../VolunteerResponseBuilder.java`
- `.../CandidatePreviewService.java`
- `.../PlanningStateService.java`
- `.../UserGoalProposalBuilder.java`
- `.../PlanningObjectiveCompiler.java`
- `.../CanonicalPlanningRuntime.java`
- `.../OjalgoDeterministicPlanSolver.java`
- `.../TierAllocationSupport.java`
- `.../TierStructureProjection.java`
- `.../CoverageRequirementSupport.java`
- `.../PriorityRuleSupport.java`
- `.../ProjectedHardRequirementSupport.java`
- `.../RepairCandidateEligibility.java`
- `.../RepairCandidateSelector.java`
- `.../RepairDryRunSimulator.java`
- `.../UnifiedPlanPostconditionValidator.java`
- `.../ReviewRuleRegistry.java`
- `.../PendingPlanningCommandBizService.java`
- `zhiyuan-agent/app/zhiyuan_agent/tools.py`
- `zhiyuan-agent/app/util/internal_client.py`
- `zhiyuan-agent/app/gateway/service.py`
- `zhiyuan-agent/app/gateway/conversation_actions.py`
- `zhiyuan-rank/services/recommendation.py`
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/volunteer/VolunteerIntervalService.java`
- `.../VolunteerDataTransformService.java`
