# J5.5 设计：审查 → 动作（finding / objectiveDelta / PlanCommand 同源）

状态：**设计稿，待独立评审；评审通过前不落地实现**。
日期：2026-10-19
关联：

- J5.0–J5.4 设计：`docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`
- J5.3 solver：`docs/superpowers/specs/2026-10-18-j53-solver-design.md`
- probe 注册表：`docs/superpowers/specs/2026-10-18-plan-evaluation-probe-registry.md`
- 语义权威表：`docs/superpowers/specs/2026-10-18-plan-semantic-authority-map.md`
- 现有实现：`ReviewEvaluationMapper`、`ActionCompiler`、`RepairProposalStateBuilder`、
  `UserGoalProposalBuilder`、`PlanningStateService`、`PendingPlanningCommandBizService`

---

## 1. 目标

把“审查发现问题”和“用户提出目标”收敛成同一条链：

```
PlanEvaluation.findings
  → finding.objectiveDelta           （唯一修复意图）
  → ActionCompiler.compile           （唯一命令编译）
  → PlanCommand                       （统一命令）
  → ReviewFixPlanner                  （直接动作 or 优化器搜索）
  → FixProposalDTO                    （预览）
  → review prepare → pending 冻结
  → 用户确认 → apply 只回放
  → postcondition / receipt           （与普通方案写动作同一套）
```

硬要求：

1. `objectiveDelta` 是修复权威；`suggestedCommand` 必须等于
   `ActionCompiler.compile(delta)`，不允许第二套修复建议。
2. `result_status=pass/not_applicable` 的 finding 必须
   `objectiveDelta=null`、`suggestedCommand=null`。
3. 修复预览与 apply 必须一致：prepare 冻结 `FixProposalDTO`（含
   `solverResult/actions/tierQuotaChange/objective digest`），apply 不再重新生成。
4. 能用优化器解决的 finding（缺数量、覆盖、保底、配比）必须走
   `CandidateSnapshot → ObjectiveCompiler → StagedDeterministicPlanSolver`；
   不能用规则链自己挑条目。
5. 直接动作类 finding（明确的 remove/replace/reorder/组内调整）可以复用现有
   action builder，但必须由 `PlanCommand` 的 targets 驱动，而不是由旧 check 文本驱动。
6. 旧会话仍有 `checks` 时保留回退；`checks` 的删除仍按 J5.2 的三段式推进，不在本批。

---

## 2. 现状链路与缺口

### 2.1 优化器链（已统一）

`UserGoalProposalBuilder` / `CanonicalPlanningRuntime` 对 fill/initial/add/remove/
replace/scope/refill 全部走：

```
CandidateSnapshotBuilder
  → PlanningObjectiveCompiler.enrichV2
  → StagedDeterministicPlanSolver
  → PlanSolverResultDTO(selected/ordered/remove/add)
  → FixProposalDTO
  → prepareUserGoalProposal：冻结 proposal + selection digest + request digest
  → applyUserGoalFixProposal：只回放 frozenProposal
```

### 2.2 审查链（当前未同源）

```
runReviewInternal
  → EvaluationContextBuilder → ReviewEvaluationMapper → findings
  → baseFinding 只给旧 check 翻译出的 finding 挂 objectiveDelta/CompiledAction
  → generateFixProposals
      → resolveReviewFixCandidates
          · 有 delta 时仍要求同 sourceCheck 的旧 failed check 存在
          · 派生 finding（coverage/safety/ratio/...）没有 delta，回退旧 check
      → RepairProposalStateBuilder.buildBaseProposal(check, strategyOverride)
      → RepairRiskActionBuilder / RepairReplacementActionBuilder / 组内 builder
  → applyFixProposal
      → 重新 generateFixProposals（不冻结、不回放）
      → applySupportedFixProposalStrategy 按策略分派
```

具体缺口（文件:行）：

| # | 缺口 | 现状 |
|---|---|---|
| G1 | `CompiledActionDTO` 只是意图 | 只有 strategy/sourceCheck/reasonCode/targets；`executable=false`；没有目标数/档位/约束补丁 |
| G2 | `suggestedCommand` 是 `Object` | 没有类型契约，消费者为零 |
| G3 | 派生 finding 无 delta | `mapSafety/mapCoverage/mapTierRatio/mapProbabilityInversion/...` 绕过 `baseFinding` |
| G4 | delta 被 check 绑定 | `resolveReviewFixCandidates` 找不到 failed check 就丢弃；coverage 永远没有 check |
| G5 | 修复不进优化器 | 修复 builder 按规则/补偿动作挑条目；fill/safety/ratio 没有 solver 参与 |
| G6 | 审查 apply 重新生成 | `applyFixProposal` 每次 `generateFixProposals`；预览与 apply 之间状态变化会漂移 |
| G7 | 无 review prepare | pending 由网关按 `activeProposal` 兜底生成，不带 frozenProposal/selection digest/hard version |
| G8 | 两条 apply 路径 | user_goal 冻结回放 vs review 重新生成＋策略分派 |

---

## 3. 核心设计决策（建议）

### D1. `CompiledActionDTO` 直接升级为 `PlanCommand v1`，不新增并行 DTO

理由：仓库里没有 `PlanCommand` 类；再引入一个 DTO 会形成
`ObjectiveDelta`/`CompiledAction`/`PlanCommand` 三套字段。把
`CompiledActionDTO` 扩展成命令意图，`suggestedCommand` 类型改为它，
JSON 字段向后兼容（现有字段不变，只增字段）。

字段：

```java
class CompiledActionDTO {
    String commandType = "apply_plan_change_proposal";
    String strategy;                 // RepairProposalTaxonomy.Strategy
    String sourceCheck;              // probe registry sourceCheck
    String reasonCode;
    List<EvaluationEntryRefDTO> targets;
    Map<String, Object> constraintPatch;
    Integer targetCountDelta;
    Map<String, Integer> tierQuotaDelta;
    Boolean requiresConfirmation = true;
    Boolean executable = false;      // 编译期能力，不是“可绕过确认”
    String note;                     // unsupported_reason / preview_only_until_confirmation
}
```

`executable=true` 的语义：**该命令有确定的 planner，可以生成可确认预览**；
执行仍然必须 prepare→pending→confirm，绝不能直接执行。

### D2. delta 是唯一修复来源，命令从 delta 编译

- `ActionCompiler.compile(delta)` 只做确定性映射：
  strategy 校验、targets 去重、patch 复制、能力位。
- 编译结果 digest：
  `commandDigest = sha256(canonicalJson(commandType, strategy, sourceCheck,
  reasonCode, targets, constraintPatch, targetCountDelta, tierQuotaDelta))`。
- `finding.suggestedCommand == null` 当且仅当：
  - finding pass/not_applicable；或
  - strategy 不在注册表/不被支持（此时 `objectiveDelta` 可保留，命令为 null，
    `note` 记录 `unsupported_strategy`）。
- 不允许出现 `delta.strategy != command.strategy`；出现即拒绝该 finding 的修复入口。

### D3. 修复规划器分两类：Direct 与 Search

新增 `ReviewFixPlanner`（纯内存，无写操作）：

```
plan(finding, command, state, reviewVersion) -> FixProposalDTO | null
```

**DirectCommandPlanner**（目标已可枚举）

- 适用：`remove_risk_items`、`replace_risk_items`、`sort_by_probability`、
  `adjust_major_group_inner_safety`、范围类（only_keep/must_include/exclude/tuition）。
- 输入：delta targets（unit/item refs）+ constraintPatch。
- 输出：`FixProposalDTO` + actions。复用现有
  `RepairRiskActionBuilder`/`RepairReplacementActionBuilder`/
  `RepairMajorGroupInnerSafetyActionBuilder`，但**入口改为 command targets**；
  check 只用于文案/兼容。
- 不进入 solver。

**SearchCommandPlanner**（目标数/结构缺口，需要重新选条目）

- 适用：`fill_missing_count`、`add_safety_items`、`rebalance_tier_ratio`、
  `fill_probability_gap`、`edge_score`（以及 coverage 缺口映射成的 fill）。
- 输入：`ObjectivePatch`（见 D4）。
- 输出：`FixProposalDTO`（含 solverResult/selected/ordered/actions）。
- 执行：构造 `CandidateSnapshot` + 在 `CanonicalPlanningObjectiveSetDTO` 上应用
  patch → `enrichV2` → `StagedDeterministicPlanSolver`。与 fill 是同一个 solver，
  不是另一套启发式。

### D4. `ObjectivePatch`：审查目标补丁（不冒充用户请求）

新增最小 patch 结构（可先作为 `ObjectiveDeltaDTO` 的字段，避免新 DTO）：

```java
class ObjectivePatch {
    HardConstraintsDTO constraintPatch;       // 已存在的结构
    Integer targetCountDelta;
    Map<String,Integer> tierQuotaDelta;       // 冲/稳/保
    Integer safetyMinLocalProtectDelta;
    List<CoverageRequirementDTO> coverageAdds;
    List<String> coverageRemoveIds;
}
```

`ReviewFixPlanner` 把它应用到 `PlanningObjectiveCompiler.compile(state)` 的副本上：

1. `targetCount = selectionTargetCount ?? requiredCount`（现有口径）再加 delta；
2. `tierAllocationConstraint` 的 bounds 加 delta，clamp 到 [0, targetCount]；
3. `structureTarget.safetyFloor.minLocalProtect += delta`；
4. coverage 增删；
5. 最后 `enrichV2` 重算 anchor/utility/policy 并重冻 objectiveDigest。

Search planner 的 `MutationPolicyDTO`：

| strategy | action | lockExisting | countAsChurn | requireCompensationSafe |
|---|---|---|---|---|
| fill_missing_count | FILL | false | true | true |
| add_safety_items | FILL | true | true | true |
| rebalance_tier_ratio | FILL | true | true | true |
| fill_probability_gap | FILL | false | true | true |
| edge_score | FILL | true | true | true |

> 具体 lockExisting 以现有 user-goal fill 语义为准；差异在评审时逐项确认。

### D5. 审查预览也必须 prepare + 冻结

新增 inner 接口（与 user-goal 镜像）：

```
POST /gaotu-assistant-bot/inner/planning/{tenantId}/session/fix-proposals/review/prepare
  ?chatSessionId={id}&requestId={requestId}
Body: {
  "proposalId": "fp_...",           // generateFixProposals 的结果
  "sourceVersionGuard": 14,
  "objectiveDelta": {...} | null,   // finding 的 delta，用于校验“用户确认的就是这个 finding”
  "regenerateOrderedPlan": true,
  "rerunReview": true
}
→ PrepareResultDTO { pendingId, operationId, result: FixProposalStateDTO }
```

Java 侧 `prepareReviewProposal`：

1. `prepareOnce` 幂等 + supersede；
2. 重新执行 review（或读当前 `ReviewStateDTO.findings`），按 `proposalId` 找到
   finding/command，**重新规划一次** `FixProposalDTO`；
3. 校验 `regenerateOrderedPlan/rerunReview=true`（现有 apply 契约）；
4. 冻结到 pending.dataValue：
   - `proposalId`、`proposalSource=review_check`
   - `frozenProposal`（整份 FixProposalDTO）
   - `frozenSelectionDigest`（选中/硬事实/目标/policy）
   - `frozenRequestDigest`（proposalId + sourceVersionGuard + commandDigest）
   - `canonicalObjectiveDigest` / `solverVersion` / `solverInputDigest` /
     `hardObjectiveVersion`
   - `sourceReviewVersion` / `evaluatedStateVersion`
   - `operationId`
5. 只有 `requiresConfirmation=true` 的主提案才落 pending；blocked/preview_only
   只回预览（沿用 user-goal 的脏 pending 防线）。

### D6. review apply 只回放冻结负载

`applyFixProposal` 分支：

```
if proposalSource == review_check:
    frozen = load pending by proposalId
    verify frozenRequestDigest / frozenSelectionDigest / hardObjectiveVersion
    proposal = frozen.frozenProposal
    applySupportedFixProposalStrategy(...)   // 执行动作
    postcondition + receipt
```

- 不再调用 `generateFixProposals`。
- 缺少 frozen 负载 → 409 `review_fix_frozen_proposal_missing`（旧 pending 可走
  一次显式“兼容重新生成”，用 `sourceReviewVersion + proposalId` 限定，并在
  J5.5d 删除）。
- `FrozenSelectionGuard` 复用现有实现；选中实体必须仍在/仍合格，否则 409。

### D7. 命令能力表与可执行边界

`ActionCompiler` 维护 `EXECUTABLE_STRATEGIES`；不在表内 → `executable=false`，
`note=preview_only:<strategy>`，预览仍可生成，但 apply 拒绝（现有
`RepairProposalApplyPolicy.isSupportedStrategy` 同步）。

建议首批：

| strategy | planner | executable |
|---|---|---|
| fill_missing_count | Search | true |
| add_safety_items | Search | true |
| rebalance_tier_ratio | Search | true |
| fill_probability_gap | Search | false（J5.5c） |
| edge_score | Search | false（J5.5c） |
| remove_risk_items / replace_risk_items | Direct | true |
| sort_by_probability | Direct | true |
| adjust_major_group_inner_safety | Direct | true |
| scope 类 | Direct | 已有 user-goal apply 能力，按现有 |

`executable=false` 的 finding 仍可展示“建议”，但不生成可确认 pending。

### D8. 版本与幂等

- `commandDigest`：见 D2。
- `frozenRequestDigest = sha256(proposalId, sourceVersionGuard, commandDigest,
  sourceReviewVersion)`。
- `frozenSelectionDigest`：沿用 `FrozenSelectionDigest.compute`。
- `proposalId` 保持现有 `fp_<sha1(session|stateVersion|checkCode|strategy|affectedIds)>`；
  Search planner 的合成 proposal 也使用同一生成器，把 `sourceReviewVersion`
  纳入 raw，避免同一 state 两次 review 生成相同 id 但不同 delta。
- prepare 的 `requestId` 幂等由 `ConversationProposalRequestService.prepareOnce` 负责。

---

## 4. Probe → Delta → Planner 映射

| probe / finding code | fail 时 strategy | delta 关键字段 | planner | 备注 |
|---|---|---|---|---|
| `safety_guard` | `add_safety_items` | `targetCountDelta = required - actual`；`constraintPatch` 可带生源省 | Search | unknown 仍 block，不给 delta |
| `ratio_distribution` | `rebalance_tier_ratio` | `tierQuotaDelta`（bounds - actual） | Search | 显式配额优先；无约束时沿用旧口径 |
| `count_validation_hard` | 低于官方 → `fill_missing_count`；超上限 → `remove_risk_items` | `targetCountDelta` 到官方边界 | Search / Direct | 现有 count_over_limit 纠正保留 |
| `count_target` | `fill_missing_count` | `targetCountDelta = selectionTargetCount - actual` | Search | 无目标 → not_applicable |
| `coverage:<index>` | `fill_missing_count` | `coverageAdds` 保留原 requirement；`constraintPatch` 带 target scope | Search | 新增 probe，无旧 check |
| `probability_inversion` | `sort_by_probability` | `reorderTargets = affected refs` | Direct | 现有 sort 链 |
| `probability_gap` | `fill_probability_gap` | `targetCountDelta`/tier patch | Search（首期 preview-only） | 需要“用跨档候选替换” |
| `high_tuition` | `replace_risk_items` | `removeTargets = affected`；`constraintPatch.maxTuition` | Direct | 现有替换链 |
| `admission_limit` | `remove_risk_items` | `removeTargets` | Direct | hard/block |
| `special_enrollment` | `remove_risk_items` | `removeTargets` | Direct | |
| `cooperative_program` | `replace_risk_items` | `removeTargets` | Direct | |
| `edge_score` | `add_safety_items` | `targetCountDelta` / `rewriteTier` | Search（首期 preview-only） | 用户分数边缘区间 |
| `group_inner_safety_guard` | `adjust_major_group_inner_safety` | `targets = unit`；组内 major refs | Direct | 组内安全垫 |
| `major_group_safety_intent_alignment` | `adjust_major_group_inner_safety` | 组内 refs | Direct | |
| `plan_update_notice` / `adjustment_notice` | — | — | none | policy，不可优化消失 |

派生 finding 的 delta 由 mapper 统一挂载：在 `map()` 汇总后，对
`result_status=fail/unknown` 且 `objectiveDelta=null` 的 finding，按
`EvaluationProbeRegistry.get(code).sourceCheck` 查 `ReviewRuleRegistry` 的
默认策略，生成与 `baseFinding` 同形的 delta；pass/not_applicable 跳过。
没有注册策略的 probe（首期 coverage）由 mapper 单独构造。

---

## 5. Search planner 与 solver 的接线

### 5.1 输入构造

```
PlanningStateDTO state
  → PlanningObjectiveCompiler.compileConfirmed(state)      // 基准目标
  → apply(ObjectivePatch)                                   // D4
  → PlanningObjectiveCompiler.enrichV2(state, objectives, policy)
  → CandidateSnapshotBuilder.build(state, effectiveCandidates,
        ORDERED_FIRST/UNION 与 fill 同源)
  → StagedDeterministicPlanSolver.solve(snapshot, objectives, policy)
```

- `CandidateSnapshot` 的 `countMode`、`sourceVersion`、`dataVersion` 必须与
  当前 state 一致；不一致 → blocked `review_fix_snapshot_stale`。
- `requireCompensationSafe` 只约束新增（沿用 J5.3 修复）。
- 单元模式的部分移出仍按当前 fill 的 projected removal 过滤 raw candidates。

### 5.2 输出映射

`PlanSolverResultDTO` → `FixProposalDTO`：

| 字段 | 来源 |
|---|---|
| `status` | solver ready/blocked → proposal ready/blocked |
| `strategy` | command.strategy |
| `actions` | ADD/REMOVE/REPLACE/REORDER，按 solver add/remove/ordered |
| `dryRunResult` | selected/added/removed 计数 |
| `solverResult` | 整份 solver 结果（冻结回放用） |
| `canonicalObjectiveDigest` | enrichV2 后的 objectiveDigest |
| `solverVersion/hardObjectiveVersion` | staged solver 常量 |
| `proposalSource` | `review_check` |
| `sourceCheckCodes` | finding.code/sourceCheck（审计） |
| `requiresConfirmation` | solver ready 且 actions 非空 |

### 5.3 失败/降级

- solver `candidate_shortage` / `objective_set_infeasible` → proposal blocked，
  带 `blockingReasonCodes`，不落 pending。
- `executable=false` 的 strategy → proposal preview_only，不落 pending。
- planner 异常 → 降级为旧 repair builder（仅当 finding 有对应旧 check），
  日志 `review_fix_planner_fallback`；连续降级计入指标。

---

## 6. 冻结、确认、执行、回执

### 6.1 pending 载荷（review_check）

```json
{
  "operationId": "...",
  "proposalSource": "review_check",
  "proposalId": "fp_...",
  "sourceVersion": 14,
  "sourceReviewVersion": 9,
  "evaluatedStateVersion": 14,
  "canonicalObjectiveDigest": "...",
  "solverVersion": "ojalgo-48.4.2-j53-staged",
  "solverInputDigest": "...",
  "hardObjectiveVersion": "solver-hard-objective-v1",
  "frozenProposal": { ... },
  "frozenSelectionDigest": "...",
  "frozenRequestDigest": "...",
  "regenerateOrderedPlan": true,
  "rerunReview": true
}
```

### 6.2 确认执行

`PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL` 现有入口可直接复用：

- `assertRequestMatchesFrozen` 对 apply_plan_change_proposal 目前直接返回；
  新增 `proposalId`/`commandDigest` 比对。
- `applyFixProposal` 按 D6 回放冻结 proposal。
- 后置条件：`UnifiedPlanPostconditionValidator` 对 review 产物与 user-goal 使用
  同一 `hardObjectiveVersion`/digest 校验；review 的 `sourceCheckCodes` 只做审计。
- 回执：`RepairReportBuilder` 沿用；新增 `findingCode/commandDigest` 两个字段。

### 6.3 幂等

- 同一 `operationId` replay 返回同一结果（现有 command 表）。
- `proposalId` 变了但 `operationId` 未变 → 409 `command_content_mismatch`。
- pending revision/claimToken 校验沿用现有状态机。

---

## 7. 兼容与迁移

1. **旧会话无 findings**：`resolveReviewFixCandidates` 继续走 checks；旧 pending
   没有 frozenProposal 时，首次 apply 允许一次“重新生成 + 立即冻结”的过渡分支，
   用 `sourceReviewVersion` 限定；J5.5d 删除。
2. **checks 不删除**：Web/Agent 仍可读；findings 是修复入口。删除 checks 仍按
   J5.2 三段式，不在本批。
3. **Agent/Gateway**：
   - 新增 `prepare_review_fix_proposal` 内部客户端方法；
   - 确认动作先 review prepare，再走现有 claim/execute；
   - 旧 agent 仍可直接 apply（走过渡分支），但会在响应中带
     `frozenReplay=false` 标记。
4. **开关**：建议 `review.fix.command.enabled`（默认 off）控制
   review prepare/frozen replay；J5.5a（delta/command 形状）不改变执行，直接开。
   稳定后删除开关（本仓库惯例）。

---

## 8. 实施分片

### J5.5a（低风险，先行）

- `CompiledActionDTO` 扩展为 PlanCommand v1；`ActionCompiler` 编译完整字段 +
  `commandDigest`；`suggestedCommand` 类型收紧。
- mapper 给派生 finding 挂 delta（D2/D4 的“同形 delta”）。
- `ActionCompilerTest`、mapper 测试。
- 行为不变：不接 planner，不改 apply。

### J5.5b（冻结回放）

- 新增 `ReviewFixPlanner` 骨架（Direct 路径先接现有 builder）。
- 新增 review prepare 端点 + pending 冻结。
- `applyFixProposal` review 分支改为冻结回放；旧 pending 过渡分支。
- Agent/gateway 新方法 + 确认链。
- 真栈：900045/900040 review fix prepare→confirm→apply→恢复。

### J5.5c（Search planner）

- `ObjectivePatch` + `PlanningObjectiveCompiler` 应用；
- Search planner 接 staged solver；
- safety/ratio/count/coverage 先开，gap/edge 后开；
- golden：10 个真实会话 findings→command 稳定、无 pass/fail 漂移；
- 真栈：900045 缺口场景 review fix apply，postcondition 与 user-goal 一致。

### J5.5d（清理）

- 删除 `RepairDryRunSimulator` 旧规则链（保留过渡适配器注释）；
- 删除 review apply 的重新生成分支；
- 评估 checks 删除（按 J5.2 三段式，不在本批强制）。

---

## 9. 测试矩阵

| 层级 | 用例 |
|---|---|
| 单元 | ActionCompiler 全字段/digest/不支持策略；pass 无 command；mapper 派生 delta；Direct planner targets；Search planner patch/target 数；冻结 digest 变更 409 |
| 契约 | proposalId/commandDigest 不一致拒绝；pending replay 幂等；旧 pending 过渡分支只执行一次 |
| golden | 10 个真实会话：findings/command digest 两次运行一致；旧 check 与 finding 的 pass/fail 无漂移 |
| 真栈 | 900045 review fill/safety/ratio fix prepare→apply→postcondition；900040 只读预览；恢复 HEX |
| 回归 | 全量 Java 1274+；gateway pytest 345+；Web 卡片字段兼容 |

---

## 10. 风险与回滚

| 风险 | 处理 |
|---|---|
| Search planner 改目标导致方案大改 | 首期只开 fill/count/coverage；safety/ratio 需 golden 指标不劣；preview 先只读验收 |
| review prepare 与旧 pending 冲突 | `prepareOnce` supersede；旧 pending 409 明确提示重新预览 |
| delta 与 command 分叉 | 编译期断言 + digest；不一致拒绝该 finding |
| 派生 finding 无对应旧 check | J5.5a 先只挂 delta，不生成提案；J5.5c Search planner 才生成 |
| 回滚 | 关闭 `review.fix.command.enabled` 回旧 apply（重新生成）；新 pending 需重预览；不删数据 |

---

## 11. 待评审拍板

1. **PlanCommand 载体**：扩展 `CompiledActionDTO`（推荐）还是新增
   `PlanCommandDTO`？
2. **Search planner 的补丁载体**：放在 `ObjectiveDeltaDTO` 扩展字段（推荐，
   减少 DTO）还是独立 `ObjectivePatchDTO`？
3. **review prepare 契约**：新增 `/review/prepare`（推荐）还是复用
   `/user-goal/prepare` 加 `proposalSource`？
4. **首批 executable 策略**：是否只开 fill/count/coverage，safety/ratio 等
   golden 后再开？
5. **旧 apply 过渡分支**：保留一轮（推荐）还是直接 fail-closed 要求重新预览？
6. **receipt 字段**：`findingCode/commandDigest` 是否进入用户可见卡面，还是只做
   内部审计？
