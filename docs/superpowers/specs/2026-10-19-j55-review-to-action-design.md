# J5.5 设计：统一“评价 → 命令 → 预览 → 确认 → 执行”框架

状态：**用户已批准按第三轮复核修订后分阶段落地；J5.5a 与 b 的只读冻结排序/原 probe 预检前置已本地实现；旧 Golden 上下文已修复，并修正专业组合作办学漏报；b/c 确认执行写链尚未切换**。
日期：2026-10-19
首轮评审：`docs/superpowers/reviews/2026-10-19-j55-review-to-action-design-review.md`

关联：

- 总设计：`docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`
- J5.3 solver：`docs/superpowers/specs/2026-10-18-j53-solver-design.md`
- probe 注册表：`docs/superpowers/specs/2026-10-18-plan-evaluation-probe-registry.md`
- 语义权威表：`docs/superpowers/specs/2026-10-18-plan-semantic-authority-map.md`
- 切流手册：`docs/superpowers/reviews/2026-10-18-j53-cutover-readiness.md`

---

# 0. 一页结论

只保留**一条方案动作主链**：

```
评价（PlanEvaluation.findings）
  → 修复意图（ObjectiveDelta，展示/审计）
  → 命令（PlanCommandDTO，绝对目标）
  → 规划器（PlanProposalPlanner：UserGoal / Direct / Search）
  → 方案预览（FixProposalDTO）
  → 待确认（PendingCommand，冻结 proposal + patch + digests）
  → 用户确认
  → 执行（FrozenPlanExecutor 只回放）
  → 后置校验（按 finding/probe 复算）+ 回执
```

统一后的边界：

| 层 | 唯一职责 | 不允许 |
|---|---|---|
| Evaluation | 回答“哪里不符合目标” | 不生成修复 |
| Delta/Command | 回答“目标改成什么” | 不选条目 |
| Planner | 回答“选哪些、怎么排” | 不改命令、不写库 |
| Solver | Planner 的唯一搜索实现 | 不直接落库 |
| Preview | 展示最终方案 | 不确认 |
| Pending | 冻结、幂等、状态机 | 不重新规划 |
| Apply | 只回放 + 持久化 + 后置 | 不重新规划 |

**J5.5b 的统一范围**：审查修复与用户目标共享 **proposal / freeze / apply /
postcondition / receipt** 五件套；用户目标在 J5.5b 仍由 `UserGoalPlanner`
适配现有 `UserGoalProposalBuilder`（同一个 `PlanProposalPlanner` 接口），
但**不共享 PlanCommandDTO**。J5.5d 再评估是否把用户目标编译也并入
PlanCommand。Direct 动作只用于**全显式**变更；需要选候选的修复一律走
Search/Solver。

---

# 1. 现状链路

## 1.1 入口与触发

| 层 | 当前实现 | 说明 |
|---|---|---|
| 用户对话 | `zhiyuan-agent/app/zhiyuan_agent/tools.py` `review_plan`（:3311）、`preview_plan_change`（:9598）、`confirm_pending` | 模型决定审查/改方案/确认 |
| 审查修复生成 | `tools.py:3443` → Java `/fix-proposals/generate`（`PlanningStateController:588`）→ `PlanningStateService.generateFixProposals:858` | 返回 `FixProposalStateDTO` |
| 用户目标预览 | `tools.py:9419` → Java `/user-goal/generate`（:596） | 只读预览 |
| 用户目标待确认 | `internal_client.py:1237` → Java `/user-goal/prepare`（:606）→ `prepareUserGoalProposal:912` | 冻结 proposal 后落 pending |
| 确认 | `conversation_actions.py:139` claim（:156-210）→ `:922` applying → `:945` operationId → `:973` expectedPlanVersion → `internal_client.py:1847` → Java `/pending-command/execute`（:244）→ `PendingPlanningCommandBizService.execute:85` | 成功后 complete（:1125） |
| 审查修复 apply | 网关直接调 `/fix-proposals/apply`（:645）→ `applyFixProposal:1130`→**重新生成**（:1139）→ `applySupportedFixProposalStrategy:1550` | 没有冻结回放 |

现状问题：review 预览→确认→apply 不冻结；user-goal 冻结但编译/规划仍独立；
两套 apply；review 工具还会创建 legacy pending（`tools.py:9558`）。

## 1.2 缺口

| # | 缺口 | 影响 |
|---|---|---|
| G1 | 没有真正的命令对象 | 修复意图无法统一执行 |
| G2 | `suggestedCommand` 是 `Object`，命令只有 strategy/targets | 没有类型契约 |
| G3 | 派生 finding 无 delta | safety/ratio/coverage 回退旧 check，coverage 丢失 |
| G4 | delta 仍绑定旧 failed check | checks 退场后修复入口消失 |
| G5 | 修复规划不经 solver | 选条目逻辑与优化器不一致 |
| G6 | review apply 重新生成 | 预览/apply 漂移 |
| G7 | review 无 prepare/freeze | 无 frozenProposal/digest/hard version |
| G8 | 两套 apply | user-goal 回放 vs review 重生成 |
| G9 | 旧规则链与新命令并存 | 两套修复语义 |
| G10 | 死代码/未用字段 | `PlanPreviewCalculator`、4 参 builder 等 |

---

# 2. 统一模型

## 2.1 主链

```
用户目标 ─┐                         ┌─ UserGoalPlanner（适配现有 builder）
          ├─ PlanCommandDTO ────────┼─ DirectPlanner（全显式动作）
审查 finding ┘        │              └─ SearchPlanner（ObjectivePatch → solver）
                      │
                      ▼
                FixProposalDTO（selected/ordered/actions/solverResult）
                      │ prepare（冻结 proposal + patch + digests）
                      ▼
                PendingCommand
                      │ 确认
                      ▼
                FrozenPlanExecutor（回放 selected/ordered + 持久化 patch）
                      │
                      ▼
                FindingPostconditionEvaluator + 回执
```

## 2.2 对象权威

| 对象 | 权威内容 | 不负责 |
|---|---|---|
| `EvaluationContext` | 方案/候选/目标/档位/生源省/分数/风险 | 不产修复 |
| `EvaluationFinding` | 评价结果 + delta + command | 不执行 |
| `ObjectiveDelta` | 展示/审计用的目标变化（可含负数） | 不作为 solver 输入 |
| `PlanCommandDTO` | **绝对目标** + 显式 targets + patch + capability + digest | 不选条目 |
| `FixProposalDTO` | 最终 selected/ordered/actions/solverResult/canonical | 不确认 |
| `PendingCommand` | frozenProposal + frozenPatch + digests + operationId | 不重新规划 |
| `PostconditionReport` | 应用后事实 vs 原 probe | 不改方案 |

## 2.3 硬不变量

1. pass/not_applicable → `objectiveDelta=null`、`suggestedCommand=null`。
2. hard fail/unknown → block；soft → action/notice；policy → notice/info。
3. `suggestedCommand` 只能由 `PlanCommandCompiler.compile(delta, state)` 产生；
   strategy/sourceCheck/reasonCode 必须与 delta 一致。
4. `executable=true` 仅表示“有 planner 能生成可确认预览”，不可绕过确认。
5. 预览/apply 必须是同一份 `FixProposalDTO` + 同一 `previewDigest`；
   apply 不重新规划。
6. 新增条目遵守 `requireCompensationSafe`；current 条目豁免。
7. 同一 `evaluationVersion + planContentDigest + commandDigest` →
   同一 proposalId/previewDigest。
8. `needs_input`/unknown 的 finding（缺生源省、缺官方数量等）不产修复命令。

## 2.4 命令对象：`PlanCommandDTO`

`CompiledActionDTO` 只被 compiler/测试使用，无外协依赖；**重命名为
`PlanCommandDTO` 并删除旧类**。

```java
class PlanCommandDTO {
    String commandType = "apply_plan_change_proposal";
    String strategy;                    // 语义策略（safety/ratio/fill/remove/...）
    String applyStrategy;               // 归一后的执行策略（fill_missing_count 等）
    String sourceStrategy;              // 审计：原 probe 策略
    String sourceCheck;
    String reasonCode;
    String level;                       // unit | volunteer

    // 绝对目标（null=不变）
    Integer targetCount;
    Map<String,Integer> tierTargetCounts;       // 冲/稳/保，总和=targetCount
    TierAllocationConstraintDTO tierConstraint; // 保留已确认的范围边界
    Integer safetyMinLocalProtect;              // 绝对下限
    List<CoverageRequirementDTO> coverageRequirements; // 全量绝对集合
    HardConstraintsDTO constraintPatch;

    // 显式动作（只用于 Direct）
    List<EvaluationEntryRefDTO> targets;
    List<EvaluationEntryRefDTO> forcedRemoveTargets;
    List<ReplacementPairDTO> replacementPairs;
    List<EvaluationEntryRefDTO> reorderTargets;

    String evaluationVersion;
    String commandDigest;
    Boolean requiresConfirmation = true;
    Boolean executable = false;         // planner capability
    String note;
}
```

`targetCount`/`tierTargetCounts`/`safetyMinLocalProtect`/`coverageRequirements`
都是**绝对值**。`ObjectiveDelta` 里的 `targetCountDelta` 只用于卡面
“+2/-3”展示和审计；compiler 用 state 上下文换算成绝对值。

第三轮修订：命令增加 `tierConstraint` 保留现有范围边界。只有用户明确授权
精确配额时才填 `tierTargetCounts`；修复范围目标不把某次解向量升级为新目标。
`constraintPatch` 仅承载授权的持久约束变化；安全等派生 effective target
单独存储，不自动写入永久用户目标。digest 覆盖 `tierConstraint`；重排序列
保持顺序语义，不能像目标集合一样排序去重后丢失执行顺序。

**digest 公式（消除循环依赖）**：

```
commandDigest  = sha256(canonicalJson(
    evaluationVersion, commandType, strategy, applyStrategy, sourceStrategy,
    sourceCheck, reasonCode, level,
    targetCount, tierTargetCounts(sorted), safetyMinLocalProtect,
    coverageRequirements(sorted), constraintPatch(sorted),
    targets/forcedRemove/replacementPairs/reorderTargets(sorted by level+id)))
proposalId     = "fp_" + sha256(evaluationVersion, planContentDigest,
                                commandDigest, canonicalProposalContent)[:16]
previewDigest  = sha256(proposalId, evaluationVersion, planContentDigest,
                        selectedEntityIds, orderedEntityIds,
                        canonicalJson(actions), canonicalJson(dryRunResult))
```

- `proposalId` **不含** previewDigest；
- `previewDigest` 包含 proposalId，反向不成立；
- `canonicalProposalContent` = 策略 + 目标绝对值 + actions 骨架（不含
  solver 结果），用于同一命令的稳定 id。
- map 一律按 key 排序，target/ref 按 level+id 排序，列表稳定。

## 2.5 预览对象

继续使用 `FixProposalDTO`（协议兼容）。新增：

- `commandDigest`
- `previewDigest`（见 §4.1）
- `sourceStrategy` / `findingCode` / `evaluationVersion`
- `objectivePatch`（冻结 patch，供 apply 持久化）
- `solverObjectiveDigest`（enrich+patch 后的 solver 目标摘要）

`canonicalObjectiveDigest` **必须保存 enrich 之前的 digest**（与
`UserGoalProposalBuilder:104` 同口径），供 apply 时
`compileConfirmed(state)` 对比；`solverObjectiveDigest` 单独保存
enrich+patch 后的值，仅用于审计/solver 复现。两者不得混用。

`solverResult / solverVersion / solverInputDigest / hardObjectiveVersion`
继续作为冻结/后置权威。

---

# 3. 怎么触发

## 3.1 触发矩阵

| 场景 | 入口 | 写？ | 结果 |
|---|---|---|---|
| 问方案问题 | `review_plan` → `/review/run` | 读 | findings，无 pending |
| 审查修复预览 | `review_plan` → `/fix-proposals/generate` | **纯读** | findings + proposals（含 previewDigest） |
| 用户目标预览 | `preview_plan_change` → `/user-goal/generate` | 纯读 | 用户目标 proposal |
| 审查修复确认 | **新增** `prepare_review_fix_proposal` → `/fix-proposals/review/prepare` | 写 pending | frozen review proposal |
| 用户目标确认 | `prepare_user_goal_planning_fix_proposals` → `/user-goal/prepare` | 写 pending | frozen user-goal proposal |
| 确认执行 | `confirm_pending`/网关 claim → `/pending-command/execute` | 写 | 只回放 |
| 测试/内部 | inner endpoints | 视接口 | 同上 |

只读实例（`codex_readonly`）只能执行“读”行；Java prepare/execute 端点必须做
**服务端只读拒绝**（不能只靠 agent 工具层）：内部请求带
`X-Assistant-Mode: readonly`（由网关/agent 从运行时模式注入），Java 在
prepare/apply 入口校验；未带或非 `write` → 403 `readonly_mode`。同时保留
配置开关 `planning.write.enabled` 供只读实例整体关闭写路径。

## 3.2 用户对话判定

1. 问状态/方案 → `review_plan`，只返回 findings 摘要；
2. 要修改：
   - 用户给目标（补数量/地区/专业/档位）→ 用户目标预览；
   - 用户确认某条审查问题 → 审查修复预览；
3. 预览 ready → 输出 `proposalApply` + `artifactRefs` + `previewDigest`；
4. 用户明确要求修复时 → prepare → pending，并展示已经冻结的可确认卡；
5. 用户对冻结卡一次确认 → claim/execute。纯查看建议不创建 pending，
   也不把没有 active pending 的只读预览当成确认入口。

审查修复卡必须带：

```json
{
  "proposalId": "fp_...",
  "proposalSource": "review_check",
  "commandDigest": "sha256:...",
  "previewDigest": "sha256:...",
  "evaluationVersion": "ev_...",
  "sourceVersion": 14,
  "requiresConfirmation": true
}
```

网关只允许确认**当前 active proposal**；proposalId/previewDigest 不一致 →
重新预览。

## 3.3 审查新鲜度与版本

- 目标态 `runReviewInternal(persist=true)`：显式 `/review/run`，写 `reviewState` 并
  清 stale；`evaluatedStateVersion` = 评价时的 stateVersion。
- **审查写不推进计划版本**：`reviewState` 使用独立的 `reviewVersion`
  （或直接以 `evaluationVersion` 作为版本），不得修改 `planningState.version`、
  不得改变 `planContentDigest`。否则 prepare/confirm 之间跑一次 review 就会
  触发 `expectedPlanVersion`/`sourceVersionGuard` 409（现网 off-by-one：
  900045 v14/review13、900040 v5/review4）。
- `runReviewInternal(persist=false)`：预览/修复生成使用，**纯内存**，不写
  reviewState、不 bump 任何版本。
- 方案写操作通过 `ReviewInvalidationPolicy`（:41-83）标 stale。
- `planContentDigest` = hash(workingPlan + orderedPlan + constraints + targets)；
  **不包含 version/reviewState**。apply guard 用它判断方案是否变化。
- `evaluationVersion = hash(evaluatedStateVersion, planContentDigest,
  candidateSourceVersion, dataVersion, objectiveModelVersion)`。
- preview→prepare 校验当前评价与预览内容；冻结后 `evaluationVersion` 用于
  请求/pending 来源绑定。apply 不重算整池评价版本来判失效，而校验计划内容、
  硬目标/动作契约及选择/显式动作涉及的硬事实；未选候选刷新不使 pending 失效。
  `sourceVersionGuard` 取 prepare 时的当前 plan version。
- 预览的候选解析必须 **in-memory refresh**：`resolveEffectiveCandidates` 的
  refresh 分支不得写 overlay（现 `:9894/:10000-10002` 会 save）；若数据已
  stale 且无法内存刷新，直接 409 `review_fix_stale`，不写库。

阶段边界：a 的独立 preview 已与旧持久审查计算分离；旧 `/review/run` 的
版本递增行为暂时保留，独立 reviewVersion/内容 guard 的写链迁移属于 b，
不能把此处的目标态描述当成旧端点已经完成迁移。

---

# 4. 怎么执行

## 4.1 只读预览（纯内存）

```
Agent review_plan
  → Java generateFixProposals (persist=false)
      → runReviewInternal(persist=false)
      → EvaluationContextBuilder → ReviewEvaluationMapper → findings
      → ReviewFixPlanner.plan(command)（不写库）
      → FixProposalStateDTO
  → 返回 proposalId/commandDigest/previewDigest/evaluationVersion/sourceVersion
```

`previewDigest` 公式见 §2.4（proposalId 由 evaluationVersion +
planContentDigest + commandDigest 生成，previewDigest 再覆盖 selected/
ordered/actions/dryRun，不存在循环）。

预览期间：

- 候选解析 in-memory；不保存 overlay、不写 reviewState、不 bump version；
- 不创建任何 pending；a 新增独立 `/session/fix-proposals/preview`，仅返回
  review/findings/typed commands 和空 proposals，status=preview_only。
  旧 generate/tool/pending 保持原样，b 的 prepare/gateway 能力完成后才切流；
- 只读实例（`codex_readonly`）止步于此。

## 4.2 审查修复 prepare

```
POST /inner/planning/{tenantId}/session/fix-proposals/review/prepare
  ?chatSessionId=...&requestId=...
Body {
  proposalId, proposalSource="review_check",
  sourceVersionGuard, evaluationVersion, commandDigest, previewDigest,
  regenerateOrderedPlan=true, rerunReview=true
}
```

`prepareReviewProposal`：

1. `ConversationProposalRequestService.prepareOnce` 幂等/supersede；
2. 加载 state/reviewState，校验 guard/evaluationVersion/planContentDigest；
3. 按 `proposalId` 从当前 evaluation 的 findings/commands 中**定位唯一 command**
   （多 proposal 时 proposalId 必须唯一；找不到 → 409 `review_fix_changed`），
   重新运行 `PlanProposalPlanner.plan(command)`（不信任网关回传内容，只信
   proposalId/digest），重新计算 `previewDigest`；与请求不一致 → 409
   `review_fix_changed`；
4. 只有 `requiresConfirmation=true` 的主提案才落 pending；
5. 冻结：

```json
{
  "operationId": "uuid",
  "proposalSource": "review_check",
  "proposalId": "fp_...",
  "sourceVersion": 14,
  "evaluationVersion": "ev_...",
  "planContentDigest": "...",
  "commandDigest": "...",
  "previewDigest": "...",
  "objectivePatch": { "...绝对目标..." },
  "canonicalObjectiveDigest": "...",
  "solverVersion": "ojalgo-48.4.2-j53-staged",
  "solverInputDigest": "...",
  "hardObjectiveVersion": "solver-hard-objective-v1",
  "frozenProposal": { /* FixProposalDTO 全量 */ },
  "frozenSelectionDigest": "...",
  "frozenRequestDigest": "...",
  "regenerateOrderedPlan": true,
  "rerunReview": true
}
```

6. 返回 `PrepareResultDTO { pendingId, operationId, result }`。

## 4.3 确认执行

```
claim pending（active→applying，claimToken）
  → POST /pending-command/execute
     body: operationId, pendingId, claimToken, expectedPlanVersion,
           commandType=apply_plan_change_proposal, proposalApply
  → PendingPlanningCommandBizService.execute
     1 validatePendingOwner（pendingId/claimToken/applying/claim 未过期）
     2 proposalApply 顶层比对：proposalId/commandDigest/previewDigest/
       evaluationVersion 必须与 pending.dataValue 一致
     3 operationId 幂等 replay
     4 expectedPlanVersion 校验（= prepare 时 plan version；review 写不推进）
     5 command 行插入
     6 executeCommand → FrozenPlanExecutor
     7 postcondition + 回执
     8 command succeeded
  → complete pending（applying→applied）
```

`apply_plan_change_proposal` 的 `assertRequestMatchesFrozen` 不再早退：
改成比对 `proposalApply.proposalId / commandDigest / previewDigest /
evaluationVersion` 与 pending.dataValue；不一致 → 409
`command_content_mismatch`。不依赖 `frozenCommand`（现有 review 数据没有它）。

`FrozenPlanExecutor`（**按 proposal 是否带 solverResult 分派，不看 source**）：

- 有 `solverResult`：
  - `applyFrozenSelection`（selected/remove/add 回放）；
  - `applyFrozenOrdering`（orderedEntityIds 回放）；
  - `regenerateOrderedPlan=true` 的语义改为“按冻结 orderedEntityIds 同步
    ordered plan”，**不是** force regenerate；实现上禁止重新调用
    `enforceSelection/enforceOrdering`；
  - `rerunReview=true` 在 apply 事务提交后执行，允许 bump review 版本，
    但不改变方案/顺序；
  - apply 同事务先持久化 `objectivePatch`（target/tier/safety/coverage），
    再用 frozen selection 回放，最后后置校验。
- 无 `solverResult`（Direct 显式动作）：
  - 按 frozen actions 执行 remove/replace/reorder/group；
  - reorder 必须回放冻结 `orderedEntityIds`，不能重新排序。

`applyFixProposal` review 分支不再调用 `generateFixProposals`；canonical
校验对所有带 solverResult 的 proposal 生效（不再只对 user_goal），且比较的是
**enrich 前的 canonicalObjectiveDigest**（见 §2.5）。

**唯一写入口**：审查修复只能走 `/review/prepare` → `/pending-command/execute`；
直连 `/fix-proposals/apply` 对 `review_check` 返回 409
`review_fix_requires_pending`（legacy 旧 pending 过渡按 §6 处理）。

## 4.4 后置校验与回执

`FindingPostconditionEvaluator`（新）：

| 来源 | 判定 |
|---|---|
| Search（fill/safety/ratio/coverage） | 冻结 solverResult.objectiveResults 与最终 state 一致 + 原 probe fail→pass |
| Direct（remove/replace/reorder/group/inversion） | 按 finding code 复算原 probe（高收费消失、倒挂=0、组内安全>=下限） |
| count | 官方/目标计数满足 |
| coverage | 原 requirement 匹配数 >= 要求 |

以上 evaluator 也是 planner 的纯内存 preflight：solver ready 不代表原问题
修复成功。候选后态必须满足原 probe 和硬约束后才能出可确认卡；仍有安全缺口
等情况返回 blocked/preview_only（`repair_goal_unreachable`），不能等确认后才回滚。

- 评价输入不可用（缺字段/候选刷新）→ fail-closed，40905。
- 回执 `RepairReportDTO` 增 `findingCode/commandDigest/sourceStrategy`；
  Web 可选展示，默认内部审计。
- 后置校验不通过 → 方案事务回滚。
- **失败状态另事务写**：command failed / pending fail/expired 用
  `REQUIRES_NEW` 失败写入器（或 outbox），不能与回滚的方案事务共用同一事务；
  失败行必须可审计，claim 过期后重新领取要换新 claimToken。

## 4.5 失败矩阵

| 场景 | 结果 |
|---|---|
| preview blocked/preview_only | 只回预览，不落 pending |
| previewDigest/evaluationVersion 变化 | 409 `review_fix_changed` |
| 方案内容变化（planContentDigest） | 409 `review_fix_stale` |
| pending/claim 不匹配或过期 | 409 `pending_mismatch` |
| expectedPlanVersion 不一致 | 409 `plan_version_conflict` |
| frozenSelectionDigest 不匹配 | 409 `solver_input_stale` |
| search 不可行 | proposal blocked，不落 pending |
| apply/postcondition 异常 | 事务回滚；command failed；pending fail/expired |
| 只读模式止步 prepare/execute | 403 `readonly_mode`（Java 端校验 header/config） |

---

# 5. 规划期实现（核心）

## 5.1 组件

| 组件 | 职责 |
|---|---|
| `ReviewEvaluationMapper` | findings + 逐 probe delta |
| `PlanCommandCompiler`（原 ActionCompiler） | delta + state → 绝对命令 + digest |
| `PlanProposalPlanner`（接口） | command → FixProposalDTO |
| `UserGoalPlanner` | 适配现有 `UserGoalProposalBuilder`（J5.5b 过渡） |
| `DirectPlanner` | 全显式动作 |
| `SearchPlanner` | ObjectivePatch → snapshot → solver |
| `PlanningObjectiveCompiler.applyPatch` | enrichV2 后应用绝对补丁并重冻 digest |
| `FrozenPlanExecutor` | 回放 selected/ordered + 持久化 patch |
| `FindingPostconditionEvaluator` | 按 finding/probe 复算 |

## 5.2 delta → command（绝对目标）

`PlanCommandCompiler.compile(delta, state, context)`：

1. `baseTarget = selectionTargetCount ?? requiredCount`；
2. `targetCount = delta.targetCountAbsolute`（若 delta 只给变化量，则
   `baseTarget + delta.targetCountDelta`，clamp ≥0）；
3. `tierTargetCounts`：若 delta 给绝对值直接用；若给变化量，加到当前
   resolved counts，clamp，校验总和=targetCount、min≤max；
4. `safetyMinLocalProtect = max(0, requiredAbs)`（绝对值，不叠加）；
5. `coverageRequirements`：按 identity 合并；已有项取 max，新项加入；
6. `constraintPatch` 复制；
7. `applyStrategy`：
   - Search 选条目（fill/safety/ratio/coverage/gap/edge）→ `fill_missing_count`；
   - 明确移出/替换（forcedRemove/replacementPairs）→ `remove_risk_items`/
     `replace_risk_items`；
   - `sourceStrategy` 保留原语义；
8. `commandDigest = sha256(canonicalJson(所有绝对字段, targets 排序,
   maps key 排序, evaluationVersion))`。

`ObjectiveDeltaDTO` 增加：

```java
Integer targetCountAbsolute;
Map<String,Integer> tierTargetCounts;   // 绝对
Integer safetyMinLocalProtect;          // 绝对
List<CoverageRequirementDTO> coverageAdds; // 合并入绝对集合
List<CoverageRequirementDTO> coverageRemove;
```

## 5.3 delta 挂载（逐 probe typed）

不再用“策略名包含 add/remove/sort”泛化。每个 probe 一个 builder：

| probe | delta | 备注 |
|---|---|---|
| `safety_guard` | `safetyMinLocalProtect=requiredAbs`；targetCount=baseTarget | required=0 或 province_excluded → 无修复 |
| `ratio_distribution` | `tierConstraint` 原边界；targetCount=baseTarget | 无显式 tierConstraint → 无命令；精确目标才带绝对 tierTargetCounts |
| `count_validation_hard` | 低于官方 → targetCount=officialMin；超上限 → forcedRemoveTargets | **空 reasonCode + passed/warn**（缺官方数）→ needs_input；`count_missing` 是“当前低于官方下限”，正常产 fill |
| `count_target` | targetCount=selectionTargetCount | 无 selectionTargetCount → not_applicable |
| `coverage:<i>` | coverageRequirements 绝对集合 | 已满足项不重复加；无 requirement → 不产 |
| `probability_inversion` | reorderTargets=affected | Direct |
| `probability_gap` | targetCount/tierTargetCounts | 首期 preview_only |
| `high_tuition` | replacementPairs（显式）或 forcedRemoveTargets → Search | 无候选 → blocked |
| `admission_limit` | forcedRemoveTargets | hard |
| `special_enrollment` | forcedRemoveTargets | |
| `cooperative_program` | replacementPairs/forcedRemoveTargets | |
| `edge_score` | safetyMinLocalProtect/tierTargetCounts | 首期 preview_only |
| `group_inner_safety_guard` | `replacementPairs`（组内 from→to 专业）；无显式配对 → preview_only，无命令 | 不回退 unit-level Search |
| `major_group_safety_intent_alignment` | 同上 | 同上 |
| notices | 无 | policy |

unknown/needs_input（缺省/缺官方数/缺评价输入）→ `fixability=needs_input`，
不产 delta/command。

## 5.4 Direct planner

只做**全显式**动作，不选候选：

- `sort_by_probability`：reorderTargets；preview 时由 PlanOrderingEngine 生成
  冻结 orderedEntityIds，apply 只回放。
- `adjust_major_group_inner_safety`：必须给**组内 from→to 专业**
  `replacementPairs`；只给 unit 不构成可执行命令，保持 preview_only。
  当前 unit solver 不能表达同组专业替换；以后另设组内 planner 才能开放。
- `remove_risk_items`：仅当 targets 已明确且无需补偿选择；否则转 Search
  `forcedRemoveTargets`。
- `replace_risk_items`：仅当 `replacementPairs` 已给出；否则转 Search。
- 生成 `FixProposalDTO.actions + dryRunResult`（dryRunResult 由 Direct 自己产，
  不依赖旧 `RepairDryRunSimulator`）。

## 5.5 Search planner

### 5.5.1 patch 应用顺序（修复 P0-2）

```
base = PlanningObjectiveCompiler.compileConfirmed(state)
PlanningObjectiveCompiler.enrichV2(state, base, policy)   // 先 enrich
applyPatch(base, command):                               // 后 patch
  1 targetCount
  2 tierTargetCounts + tierAllocationConstraint/resolution 同步
  3 structureTarget.safetyFloor.minLocalProtect
  4 coverageRequirements
  5 constraintPatch
  6 重新计算 tierAnchor / resolvedCounts
  7 重冻 `solverObjectiveDigest`；`canonicalObjectiveDigest` 保持 enrich 前值
```

补丁持久化（仅明确授权的 durable change，apply 同事务，先写后回放）：

- 派生 safety 仅为 effective target，随成绩/生源省/范围重新计算，不自动
  写成最高优先级显式硬目标；未来显式用户安全目标需单独定义授权和失效规则。
- `CoverageRequirementSupport.persist` 增加按 identity 删除；现有实现只
  add/max，无法移除。
- 修复现有 tier 范围保留 confirmed goal 原 bounds，不写回本次精确解；
  只有用户明确修改目标时才写 durable tier/count/coverage patch。
- 持久化完成后再执行 frozen selection；后置校验读写入后的 state。

必须单测断言：`StagedDeterministicPlanSolver` 收到的 objective 中
`structureTarget.tierAnchor`、`safetyFloor`、coverage 与命令一致；apply 后
再次 compileConfirmed 仍带同样补丁。

### 5.5.2 快照与 solver

```
CandidateSnapshotBuilder.build(state, effectiveCandidates, source)
  countMode/sourceVersion/dataVersion 与 state 一致
policy = mutationPolicy(sourceStrategy)
StagedDeterministicPlanSolver.solve(snapshot, base, policy)
```

MutationPolicy 按 **sourceStrategy**（不是归一后的 applyStrategy）选择：

| sourceStrategy | action | lockExisting | countAsChurn | requireCompensationSafe | forced |
|---|---|---|---|---|---|
| fill_missing_count / count_target | FILL | true | true | true | 合规存量硬保留 |
| add_safety_items | REVIEW_FIX | false | true | true | 明确 removableEntityIds 授权范围 |
| rebalance_tier_ratio | REVIEW_FIX | false | true | true | 明确 removableEntityIds 授权范围 |
| fill_probability_gap | REVIEW_FIX | false | true | true | 首期 preview_only |
| edge_score | REVIEW_FIX | false | true | true | 首期 preview_only |
| coverage / safety | REVIEW_FIX | false | true | true | 明确 removableEntityIds 授权范围 |
| remove_risk_items | REMOVE | false | true | true | forcedRemoveTargets |
| replace_risk_items | REPLACE | false | true | true | replacementPairs |

`safety`/`ratio` 不能用 `lockExisting=true`：actual=0 / 全冲场景下 current 会被
强制保留，目标不可行。结构修复仅在授权的 removableEntityIds 内允许换项，
其他合规 current 硬保留，churn 只在授权范围内最小化改动；普通数量 FILL
不能仅靠 churn 保留存量，也不能继承结构修复的任意换项权限。

### 5.5.3 结果 → proposal

- `FixProposalDTO.strategy = applyStrategy`（**必须是 taxonomy 的
  applyable 值**：选条目用 `fill_missing_count`，移出用
  `remove_risk_items`，替换用 `replace_risk_items`），否则
  `RepairProposalApplyPolicy`/`applySupportedFixProposalStrategy` 仍会拒绝；
- `sourceStrategy` 保留原语义（safety/ratio/coverage）用于展示/审计；
- `actions` 由 solver add/remove/ordered 生成；
- `solverResult` 整份冻结；
- `objectivePatch` 一并冻结，apply 持久化；
- `canonicalObjectiveDigest` 存 enrich 前值，`solverObjectiveDigest` 存
  enrich+patch 后值；
- `previewDigest` 覆盖 selected/ordered/actions/dryRun。

### 5.5.4 失败

- candidate_shortage/objective_infeasible/timeout → blocked，不落 pending；
- snapshot stale → `review_fix_snapshot_stale`；
- planner 异常：仅旧 check 可用时回退 Legacy adapter（J5.5b 保留），
  日志+指标；J5.5d 删除。

---

# 6. 清理与简化

已完成的低风险清理（全量 clean test 1268/0/0/9）：

| 项 | 处理 |
|---|---|
| `PlanPreviewCalculator` + test | 无生产调用，删除 |
| 4 参 `RepairProposalStateBuilder.buildBaseProposal` | 仅测试用，折叠为 5 参 |

J5.5 落地时：

| 项 | 处理 | 时机 |
|---|---|---|
| `CompiledActionDTO` → `PlanCommandDTO` | 单一命令对象 | J5.5a |
| review 预览的 legacy pending 创建（`tools.py:9558`） | 预览纯读，prepare 才落 pending | J5.5a/b |
| `applyFixProposal` review 重新生成（:1139） | FrozenPlanExecutor 替代；**旧分支保留到 J5.5d 供回滚** | J5.5b 新增，J5.5d 删除 |
| review-only 不可达分支（PRIORITIZE solver-null、FILL user-goal legacy） | 新链不再产生；回滚依赖，J5.5d 再删 | J5.5d |
| 直连 `/fix-proposals/apply` 的 review 分支 | 返回 409 `review_fix_requires_pending`；旧 pending 走 Legacy adapter | J5.5b |
| `RepairDryRunSimulator` | Direct 自产 dryRunResult 后删除 | J5.5c |
| `RepairProposalStateBuilder` 旧 check 路径 | Legacy adapter 保留；checks 退场后删 | J5.5d |
| `RepairProposalApplyPolicy` 冗余策略分支 | 归一后删除 | J5.5d |
| 旧测试 | 按行为删除/改写 | 对应分片 |

**不删**：

- `candidateShortages`（Web/agent 读：`tools.py:3258`、`service.py:5613`、
  `fix_proposal_formatter.py:237`、`ProposalCard.tsx:81`）。
- `targetCountAfter`（进入 FrozenSelectionDigest）。
- `RepairDryRunSimulator`（J5.5b Direct 仍用；J5.5c 由 Direct 自产
  dryRunResult 后再删）。
- checks 回退与旧 builder（旧会话）。
- replay/claim/postcondition 相关测试。

---

# 7. 典型案例（可复现）

## 案例 A：本省保底不足（Search）

Fixture：44 组，safety floor required=2，actual=0（如 900045），
targetCount=44。

delta：`safetyMinLocalProtect=2`，targetCount=44。
command：`applyStrategy=fill_missing_count`，safety=2，target=44，
`lockExisting=false`。
planner：solver 在 44 个名额内换入 2 个本省保底。
预期：selected=44，remove=2，add=2；后置 safety actual>=2、count=44。
若候选不足：blocked `candidate_shortage`，不落 pending。

## 案例 B：数量低于目标（Search）

Fixture：selectionTargetCount=45，current=42，required=45。
delta：`targetCountAbsolute=45`。
command：target=45，applyStrategy=fill。
预期：selected=45，add=3，remove=0；后置 count=45。
无 selectionTargetCount：`count_target=not_applicable`，不产命令；
官方数量缺失：`needs_input`，不产命令。

## 案例 C：高收费（Direct）

Fixture：u1 学费 21000，u2 同组替换候选 18000。
delta：`replacementPairs=[{from:u1,to:u2}]`。
planner：Direct；action=REPLACE_VOLUNTEERS，dryRun remove=1/add=1。
预期：预览列出 u1→u2；apply 后无 >20k 条目；后置 high_tuition pass。

## 案例 D：冲稳保配比失衡（Search）

Fixture：显式 tier quota 目标 {冲:5,稳:5,保:0}，current {冲:10,稳:0,保:0}，
target=10。
delta：`tierTargetCounts={冲:5,稳:5,保:0}`。
校验：总和=10，min≤max，非负。
planner：solver 换入 5 个稳档；预期 add=5/remove=5，最终计数 5/5/0。
无 tierConstraint：not_applicable。

## 案例 E：覆盖缺口（Search）

Fixture：已确认 coverage requirement `region=浙江,min=3`，actual=1。
delta：coverageRequirements 绝对集合（保留原 requirement）。
planner：solver 在 target 内补 2 个浙江。
预期：coverage matched>=3；后置按 requirement 复算。

## 案例 F：录取率倒挂（Direct）

Fixture：u1 position1 ratio80，u2 position2 ratio40，档位相同。
delta：`reorderTargets=[u1,u2]`。
planner：PlanOrderingEngine 生成冻结 orderedEntityIds。
apply：FrozenPlanExecutor 回放顺序；不重新 sort。
预期：inversion=0，集合不变。

## 案例 G：组内安全垫不足（Direct）

Fixture：unit u1 内 3 个 major，安全垫 ratio 低于下限；候选池有同组替代专业。
delta：`replacementPairs=[{from:u1-majorA,to:u1-majorB}]`（逐对显式）。
planner：Direct；action=ADJUST_MAJOR_GROUP_INNER_SAFETY，列明 from/to 专业。
无显式配对：preview_only，无命令；不使用 unit-level forcedRemove/forcedAdd
模拟同组专业替换，也不允许 Direct 自己挑专业。
预期：action 列明专业替换；后置 group_inner_safety pass。

## 案例 H：只读/陈旧/篡改

- readonly：prepare 端点 403 `readonly_mode`（服务端判定，不只 agent 层）；
- 方案内容变化：`planContentDigest` 变 → 409 `review_fix_stale`；
- preview 内容变化：`previewDigest` 变 → 409 `review_fix_changed`；
- 篡改 proposalApply：`proposalId/commandDigest/previewDigest` 与 pending
  不一致 → 409 `command_content_mismatch`；
- claim 过期：409 `pending_mismatch`，需重新确认；
- stateVersion 变：409 `plan_version_conflict`。

---

# 8. 测试方案

## 8.1 单元

| 目标 | 用例 |
|---|---|
| typed delta | 16 probe 的 pass/fail/unknown/not_applicable；unknown/needs_input 无命令 |
| 绝对目标 | safety 2/0、count 42/45(+3)、ratio 10/0/0→5/5/0、coverage 合并 |
| command digest | canonical 排序/稳定；command→previewDigest |
| Direct | 仅显式动作；无 replacement pair 转 Search；reorder 冻结顺序 |
| Search | patch 在 enrich 后生效；solver 输入断言；输出映射；lock/forcedRemove |
| 失败 | shortage/infeasible/timeout/snapshot stale → blocked/409 |
| 冻结 | previewDigest/evaluationVersion/planContentDigest/selection guard；proposalId 不含 previewDigest（无循环） |
| 后置 | 每个 finding code fail→pass；评价不可用 fail-closed |
| 幂等 | prepareOnce/operationId replay/claim CAS/revision；失败行 REQUIRES_NEW |
| 纯读预览 | generate 不写 extra_data/reviewState、不 bump plan version、不建 pending |
| patch 持久化 | apply 后 compileConfirmed 仍带 target/tier/safety/coverage；移除项真的消失 |
| 版本 | review-only 写不改变 plan version；prepare/confirm 之间跑 review 不 409 |
| 只读 | Java prepare/execute 带 readonly header/config → 403 |

## 8.2 契约

- `PlanCommandDTO` / `suggestedCommand` JSON schema；
- pending 冻结字段（frozenProposal/patch/digests/hard version）；
- gateway Python 透传 commandDigest/previewDigest/evaluationVersion；
- apply 请求篡改 → 409 码表；
- Web 旧 payload 回退（new fields optional）。

## 8.3 回归与集成

- **自动 apply 不调用 planner**：mock planner，apply 只读 frozen；
- evaluation unavailable → checks fallback 正常；
- 旧 pending（无 frozen）→ 过渡分支只执行一次；
- user-goal fill/priority/scope 全回归；
- 未选候选刷新允许冻结回放；选中/显式动作涉及实体资格变化 → selection guard 409；
- solver ready 但原 safety probe 仍 fail → 不出可确认卡；
- 范围修复后仍保留范围；派生 safety 随成绩更新重新计算；
- count fill 不删合规旧项，safety repair 只允许授权范围内最小必要替换；
- 预览后跑一次 review → plan version/planContentDigest 不变，prepare 不 409；
- 并发 claim、同 operationId replay、两个 proposal 重叠；
- 409 端到端：stale/changed/tamper/expired；
- readonly header/config 的 Java 端点拒绝；
- 全量 Java clean test；gateway pytest；WS e2e 审查卡确认。

## 8.4 Golden

10 会话（900018/28/38/900040/900045/900016/900047/10041981/10041983/
10041984）：

- findings/commandDigest/previewDigest 两次一致；
- fail/pass 与旧 checks 无漂移；
- selected/ordered 两次一致；
- Search utility/coverage/safety 不劣；
- 大池 12,510 候选不超时。

## 8.5 真栈

900045/900040 只能覆盖 fill/safety/倒挂/组内；count/ratio/coverage 需要
**专用 fixture**（900058/10041984 克隆或临时约束），不能假设 900045 具备。

每个写用例：

1. 全行备份 `assistant_chat_session_extra_data`（planningState/
   planningCandidatePool/userScoreDetail）、pending、command、request；
2. 唯一 requestId/operationId；
3. prepare→claim→execute→postcondition；
4. 恢复 `UNHEX(...) USING utf8mb4`，删 pending/command/request 测试行；
5. GET 复核 14/44、5/80。

必须覆盖：安全 2/0、count 42/45（临时 selectionTargetCount）、ratio 显式
5/5/0、coverage 浙江、高收费替换、倒挂排序、组内安全、readonly/stale/tamper。

## 8.6 性能

- 单 finding command 编译 <10ms；
- Search p95 <1s（大池 <2s）；
- 10 并发 preview 无重复 selection；
- planner fallback 计数为 0（J5.5d 前允许灰度计数）。

## 8.7 验收门槛

1. 全量 Java clean test 0 fail；gateway pytest 0 fail；
2. golden 10/10 无漂移；
3. 真栈 7 类 finding 至少各 1 条全链通过并恢复；
4. checks fallback/user-goal 无回归；
5. 删除项 grep 无引用且全量绿。

---

# 9. 分片

## J5.5a：命令模型 + typed delta（不改执行）

- `PlanCommandDTO` 替换 `CompiledActionDTO`；绝对目标 + digest；
- mapper 逐 probe delta；unknown/needs_input 无命令；
- 新增独立纯读 preview，不建 pending；旧 generate/tool 路由不切换；
- 单测/golden；执行行为零变化。

## J5.5b：冻结回放（不依赖 Search）

2026-10-19 前置批次进度：只读 `/fix-proposals/preview` 已接入普通专业模式的
显式作用域概率排序，返回完整 working/ordered/selected facts 的冻结后态与
previewDigest；共享 `FindingPostconditionEvaluator` 已用于新鲜审查 preflight。
所有新卡仍 `preview_only`、`requiresConfirmation=false`，命令
`executable=false`。组模式、pin/lock、已确认优先排序尚不支持；原 probe 或
硬目标不满足、缺事实时不返回冻结后态。下列 prepare/冻结执行/gateway 工作仍待落地，
不能把该前置批次视为 b 完成。详见
`docs/superpowers/plans/2026-10-19-j55b-frozen-preview-preflight.md`。

2026-10-19 后续（Direct 倒挂切片）：`/review/prepare` + pending 冻结 +
FrozenPlanExecutor 回放 + 原 probe 前后置校验 + Python 一次确认已接通；
灰度开关 `review.fix.command.enabled` 默认关。Java 1356/0/0/10、
Python unit 2923 passed/32 skipped；未部署、未做真栈验收。详见
`docs/superpowers/reviews/2026-10-19-j55b-prepare-frozen-replay-acceptance.md`。

- `PlanProposalPlanner` 接口 + `LegacyReviewAdapter`：现有 review builder
  产出的 proposal 也能进入统一冻结/回放；
- Legacy adapter 必须物化完整 selected/ordered/专业级后态和事实摘要；
  无法物化的策略保持 preview_only，不伪造 solverResult；
- `FrozenPlanExecutor` + 最小 `FindingPostconditionEvaluator`，预览 preflight
  与 apply 共用原 probe 判定；有 durable patch 的策略需持久化能力才可开放；
- review prepare 端点 + frozen replay；canonical guard 对所有 solver proposal；
- Python `prepare_review_fix_proposal` + tools/gateway confirm；
- 开关 `review.fix.command.enabled`；旧重新生成分支保留供回滚；
- 真栈仅验收已经具备冻结后态及后置校验的 fill/倒挂/显式专业配对；
  safety/ratio 如依赖 Search，后移 c 验收。
- **前置**：previewDigest、版本 guard、PlanProposalPlanner 接口；
  **不要求** Search planner（c 才接）。

## J5.5c：Search planner

- `applyPatch`（enrich 后）+ patch 持久化；
- Search：fill/count/coverage 先开；safety/ratio golden 后开；
  gap/edge preview_only；
- 扩展 b 的 `FindingPostconditionEvaluator` 到 Search probe；
- Direct 自产 dryRunResult，删除 RepairDryRunSimulator；
- 开关 `review.fix.search.enabled`。

## J5.5d：清理（回滚窗口结束后）

- 删除 Legacy adapter、review 重新生成分支、旧 check builder、未用字段/测试；
- checks 退出按 J5.2 三段式；
- 稳定后删除开关；
- **J5.5b/c 不删旧分支**，否则 §10 的回滚不成立。

---

# 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| Search 改目标过大 | 首期只开 fill/count/coverage；safety/ratio golden 后灰度 |
| preview/apply 漂移 | previewDigest + frozen proposal + FrozenPlanExecutor |
| patch 不持久 | frozen objectivePatch + 同事务写 + 后置复算 |
| 旧 pending 兼容 | Legacy adapter + 双开关；J5.5d 再删 |
| delta/command 分叉 | compiler 唯一入口 + digest + 断言 |
| solver 超时 | blocked，不降级（除 Legacy adapter 灰度） |
| 清理误删 | grep + clean test + 分片提交 |

回滚：

- J5.5a：纯增量，回退 DTO/mapper；
- J5.5b：关 `review.fix.command.enabled`，review apply 回旧分支（代码保留）；
- J5.5c：关 `review.fix.search.enabled`，Search 回 preview_only；
- 数据不回滚方案，只回退后续路径；验收会话 HEX 恢复。

---

# 11. 已定稿决策（二次复审后）

1. **绝对目标模型**：`targetCount/tierTargetCounts/safetyMinLocalProtect/
   coverageRequirements` 全部绝对值；delta 只做展示/审计。
2. **applyStrategy 归一**：Search proposal 的 `strategy=fill_missing_count`，
   `sourceStrategy` 保留原语义；apply 按 `solverResult` 分派，不看 strategy。
3. **Direct 边界**：只做全显式动作；remove/replace/组内无显式配对时转 Search
   `forcedRemove/forcedAdd`。
4. **previewDigest**：proposalId 先由 evaluationVersion+planContentDigest+
   commandDigest 生成；previewDigest 再覆盖 selected/ordered/actions，
   无循环。
5. **version guard**：review 写不推进 plan version；用
   `evaluationVersion + planContentDigest`，`expectedPlanVersion` 取 prepare
   时的当前值。
6. **首批 executable**：fill/count/coverage + Direct（sort/remove/replace/
   group）；safety/ratio golden 后开；gap/edge 仍 preview_only。
7. **旧 pending**：保留一轮 Legacy adapter（双开关），J5.5d 删除。
8. **命名**：`CompiledActionDTO` 改名 `PlanCommandDTO`；
   `FixProposalDTO` 暂不改名，只加字段。

## 11.1 仍需产品/数据侧确认

- coverage requirement 的 identity 规则（region/major/tag 组合）与
  `CoverageRequirementSupport.persist` 删除语义。
- group-inner 显式 replacementPairs 在卡面上的展示粒度（专业名/组名）。
- 真栈 fixture 会话由谁提供（900058 克隆或新建）。
