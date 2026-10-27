# 方案系统语义权威表（Single Source of Truth）

日期：2026-10-18。配套设计：
`docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`（v6）。
全链路评审：`docs/superpowers/reviews/2026-10-18-plan-conversation-system-review.md`。

状态：整理稿 + 独立审查后的执行边界。目标不是“再抽象一层”，而是把**同一语义的
多套名字/多套规则**收敛成一个权威定义；语义不同的东西明确保留，不硬合并。

## 〇·〇 审查结论与执行边界（2026-10-18）

独立审查结论：**BLOCK**（全文见
`docs/superpowers/reviews/2026-10-18-plan-semantic-authority-review.md`）。
方向正确，但当前文本**不能直接作为 J2a/J5 的实现依据**；关键纠正：

1. **合并是目标态，不是本批动作**：J2a/J2b 直接消费现有 `ReviewStateDTO.checks`；
   J5.0 先定义 `EvaluationContext` + 完整 probe 表 + `PlanEvaluation`，J5.2 再切换。
2. **`StructureVector` 是输出指标，不是 probe 输入**：probe 需要
   `EvaluationContext`（逐条 ratio/tuition/riskFlags、selectionTargetCount/
   requiredCount/requiredTierCounts、生源省、userScore、admissionMode）。
3. **版本只有一个计数器**：`stateVersion = planningState.version =
   workspace.version = snapshotVersion = sourceVersionGuard`；review 自己会 +1。
   内容版本另算 `planContentDigest`；评价版本用 `evaluatedStateVersion +
   planContentDigest`，否则旧 findings 会被认证成新。
4. **不立即删除持久化字段**：`ReviewStateDTO`/`ReviewCheckDTO`/
   `OrderedUnitDTO.admissionRatio`/`PlanGoalTypeValue`/`RepairProposalTaxonomy`
   仍被旧会话、legacy 或执行协议消费；先停写/加读适配，再删。
5. **`$ref` 不存在**：实际是 `candidatePoolRef` 拆分池，`loadPlanningStateReadOnly`
   已回填；不要写 `$ref` 解析器。
6. **ID 口径**：`unitId` 是 `volunteerId` **第一个 `_` 前段**；`volunteerId`
   不保证固定两段。
7. **J1a 事实**：`stale` 不能按 `staleFlags` 非空判断；`pendingStatus` 需要
   `active+applying` 的确定性查询；`hasPlan` 要 items ∪ units。
8. **权威表的“删除/合并”列**：标 `J5.2+` 的项是目标态，不是本批执行项；标
   `deprecated` 的字段先保留读兼容。

**v6 全链路原则（与主设计 §〇·五 一致）**：

> “优化/调整”默认做满足本次完整要求的最小必要变更；“重新做一版”才扩大修改
> 范围；所有写操作先预览确认。

补充：一轮一个待确认变更集 ≠ 一轮只能理解一个意图；最小变更不得丢掉硬要求；
首建不适用最小变更；精确编辑走受限逻辑，生成/补足/重优化才用搜索。

## 〇、原则

1. **一个语义只有一个权威 owner**：其他层只能是它的投影、适配器或传输格式。
2. **同一语义才合并**：名字不同但生命周期/层级不同的，保留并写清边界，不为了
   “看起来统一”硬塞进一个 DTO。
3. **删除优先于兼容层**：能直接删的重复规则先删；必须兼容的只保留**单向适配器**，
   不允许适配器反向定义语义。
4. **用户可见语义与内部指标分离**：内部 `StructureVector`/权重不直接暴露；用户
   只看到“梯度/保底/覆盖/取舍”。
5. **每个合并/删除都要有验收**：同一输入在旧/新路径给出同一结论，或明确记录差异。

## 一、权威表

| 语义 | 权威定义（owner） | 当前重复/歧义 | 处置 | 阶段 |
|---|---|---|---|---|
| 方案生命周期 | `planningStage`（`profile_ready`/`candidate_generated`/`drafting`/`ordered`/`reviewed`） | `JourneyContext.phase` 容易被当成方案阶段 | `planningStage` 唯一权威；journey phase 只做对话派生，不落库 | J1a |
| 方案状态存储 | `orderedPlanState`（最终顺序/落点）、`workingPlanState`（可编辑工作态）、`initialRecommendationState`（推荐源快照） | `draftPlanState` legacy 别名；三处都可能被当“当前方案”；候选池拆分 `candidatePoolRef` 被误写成 `$ref` | 读最终方案用 `orderedPlanState`；编辑/回滚用 `workingPlanState`；`draftPlanState` 只做兼容读；`initialRecommendationState` 只作来源；候选池用 `loadPlanningStateReadOnly` 回填，不写 `$ref` 解析 | J2a/J5 |
| 对话位置 | `JourneyContext`（`statePhase` + `taskIntent`） | `last_action`（已删除）、`allowedCapabilities` 被误当阶段 | `JourneyContext` 唯一；`allowedCapabilities` 只做安全能力 | J1a |
| 用户动作（内部） | `PlanCommand`（generate/**constrain**/add/remove/replace/move/fill/reorder） | `ProposalRequest.goalType`（7 类）、Java `commandType`（5 类）、legacy `PlanGoalTypeValue`（10 类）、repair taxonomy | `PlanCommand` 内部唯一；`proposalRequest.goalType` 是模型唯一词汇；Java `commandType` 是执行适配；`constrain` 承载 scope/学费/requirements/priority；**legacy 只映射 mutation 子集**（only_keep/must_include/exclude/tuition 等）；`query_state/clarify/prefer_scope/rebalance_structure/reduce_risk/mixed_adjustment` 不进 `PlanCommand`，留在 legacy/IntentFrame.goal_family | J5 |
| 加入语义 | `PlanCommand.add` + `addPolicy=expand|replace` | `add_units` vs `replace_units` vs `must_include_scope` | `add_units` 是模型语义；`PlanCommand.add` 是内部语义；REPLACE 显式 `addPolicy=replace`；`must_include_scope` = 已有→no-op、未满→从候选补入、满→最多替换 1 组 | J4a/J5 |
| 候选事实 | `CandidateSnapshot`（J5） | raw pool / effective candidates / agent artifacts 三套 | J5 统一；J2a 只读 ordered plan + join；其他路径逐步改读同一 snapshot | J5.1 |
| 档位 | `tier` = **校级** `schoolEnrollRatio` 派生（`<=50 冲 / <=70 稳 / >70 保`） | `admissionRatio` 在 OrderedUnit 可能是校级也可能是专业级；`tier` 与 ratio 混用；`pathTier` 被当成持久字段 | `tier` 是持久权威；`pathTier` 只是解读内部别名，不落库；`OrderedUnitDTO.admissionRatio` **本批不删**（review 的 inversion/gap、MajorGroupUnitQuality、导出仍在读）；先加显式 `schoolEnrollRatio`/`representativeMajorRatio`，迁移消费者并 golden 后再 deprecate | J2a/J5 |
| 历史位次 | `admission.get_history` / `CandidateItemDTO.*HistoryScores` | `rankInTier` 被误当历史位次 | `rankInTier` 唯一语义=推荐排序名次；历史只能来自 history 字段；不得混用 | J2a |
| 分数字段 | `finalScore`=推荐综合分；`baseScore`=院校分；`intentScore`=专业意向分；`rankInTier`=推荐排序 | 被当成录取分/概率 | 文档写清；用户面不展示；不能拿 `finalScore` 推录取 | J2a |
| 优化目标 | `ObjectiveModel`/`ObjectiveCompiler`（J5） | review checks、solver 约束、fill/scope 各自一套 | 同一目标模型；review probe 与 solver 读同一指标 | J5.2 |
| 方案评价 | `PlanEvaluation`/`EvaluationFinding`（J5） | `ReviewCheckDTO`/`ReviewRuleRegistry`/`ReviewSummaryDTO` | `PlanEvaluation` 权威；`ReviewCheckDTO`/`ReviewRuleRegistry` 合并为 probe/finding；`ReviewSummaryDTO` 只是计数视图 | J5.2 |
| 审查生命周期 | `ReviewState`（status/evaluatedAt/evaluationVersion/summary + 对 `PlanEvaluation` 的引用） | 旧 `ReviewStateDTO` 同时承载规则和生命周期；`checks` 被当第二来源 | 保留一个**薄视图**，不承载独立规则；`ReviewState.checks` 只能是 findings 的投影；长期可改名 `EvaluationState` | J5.2 |
| 方案审查 | `PlanEvaluator`（J5） | `plan-final-review` 技能私有规则 | 技能只做“评价结果的叙述”；J5 前人工审查只作过渡 | J5.2/J5.4 |
| 审查运行 | `ReviewWorkflowRunRes`（一次 workflow 运行结果） | 与 `ReviewState`/`PlanEvaluation` 混用 | 运行结果只是执行/传输；评价语义在 `PlanEvaluation`，持久状态在 `ReviewState`；不另定规则 | J5.4 |
| 审查版本字段 | `ReviewState.sourceVersion` = 旧方案版本（兼容）；`evaluationVersion` = 新评价版本 | 两个版本都被叫“审查版本” | 新代码只读 `evaluationVersion`；`sourceVersion` 仅旧视图/迁移期使用，不参与新缓存/结论 | J5.2 |
| 方案变更回执 | `PlanReceipt` + `StructureVector`（J5） | `actualChanges`/`reviewState`/`PrepareResultDTO`/`PendingPlanningCommandRes` | `PlanReceipt` 权威；传输层字段只做投影；不新增 `system.action`；回执不重复定义评价 | J5.4 |
| 修复预览 | `FixProposalStateDTO`/`FixProposalDTO`（现有） | `EvaluationFinding` + `PlanCommand` 的修复视图 | 过渡期保留；J5 后由 findings 直接生成，删除独立修复 DTO 语义 | J5.5 |
| 预览 vs 执行回执 | `PrepareResultDTO`/pending = 预览/待确认；`PlanReceipt` = 已执行结果 | 两者都叫“结果” | 预览不是回执；pending 确认前不得写“已生效”；回执只在执行后产生 | J4a/J5 |
| 结构指标 | `StructureVector` | review summary counts / ratio checks / coverage / interpretation drivers | 单一指标定义；review/interpretation/receipt 共用；用户面转业务语言 | J5.0 |
| 评价四字段 | `resultStatus(pass/fail/unknown/not_applicable)`、`ruleStrength(hard/soft/policy)`、`displaySeverity(block/action/notice/info)`、`fixability` | 一个 `severity` 同时承担结果/强度/展示/可修复性 | 四字段分开；预算上限/资格/政策上限按用户强度进硬校验；不把所有 warning 自动编译成约束 | C |
| 任务/变更集 | `TaskDraft`（有界任务：taskId/原始回合/IntentDraft/剩余项/关联 pending/operation/status）；`ChangeSet`（本轮唯一待确认业务变更集） | 把“一轮一个写”当成“一轮一个意图”；靠正文记剩余项 | 一次解析完整要求，一个复合 ChangeSet；不支持就阻断/协商分步；剩余项持久化，不只靠模型上下文。**当前 TaskDraft 在 `ConversationWorkingSet` + `RedisTaskLedger`（tenant/session、TTL 7 天、≤16KB）；Redis 不可用降级进程内**；仍不是方案/pending 真值 | A/B |
| 缓存作用域 | 个性化缓存 key = 受信 tenant/session + 候选输入指纹 + overlay/mode + 反事实参数；字节/条目双限 | 只按 planVersion/candidateSourceVersion 做全局 LRU | 个性化数据不得跨会话共享；公共不可变数据才可共享 | C |
| 输入凭据 | 每次评价/预览/解读绑定不可变输入清单（方案摘要、有效目标、画像/政策、候选来源/overlay、数据快照、算法版本） | 旧 findings 与新摘要拼成“新版本”；只存 review 元数据 | 输入清单与结果一起生成/保存；旧结果不能重新认证；写执行继续 CAS，不跨版本套用旧确认 | C |
| 执行后置条件 | `PostconditionReport`（exact targets/count/no-removal/hard） | 与 review/evaluation 的通过/失败混用 | 保留独立：后置条件是“执行闸”，评价是“方案体检”；共享指标定义但用途不同 | J5.4 |
| 覆盖 vs 数据完整度 | `StructureVector.coverage` = 方案方向/地域/层次覆盖；`dataCompleteness` = 评价输入数据完整度 | 旧 `dataCoverage` 与 `coverage` 同名不同义 | `dataCoverage` 改名 `dataCompleteness`；`coverage` 只指方案覆盖；解读里不展示小数 | J2a |
| 覆盖目标 vs 覆盖实际 | `coverageRequirements`（目标，IntentModel）；`StructureVector.coverage`（实际） | 两个 coverage 字段各算一套 | 共享同一组 coverage keys；目标 vs 实际，不是重复定义 | J5 |
| 录取解读 | `LandingScenario`/`AdmissionInterpretation`（结构版，J2a） | `slip_risk`/`likelihood_band` 被当成风险预测；结构覆盖 vs 数据缺口混用 | 只输出 `structureStatus/condition/safetyCoverage/dataCompletenessBand/orderAnomaly`；**删除 likelihood/slipRisk 预测标签**；数据齐全不等于风险低；结构解读不写回 review | A4 |
| 顺序异常 vs 概率倒挂 | `order_anomaly` = 保出现在稳/冲之前（tier 顺序）；`probability_inversion` = 相邻条目 ratio 倒挂 | 两者被当成同一件事 | 保留两个指标：一个看档位顺序，一个看 ratio 顺序；可同时出现，不互相替代 | J2 |
| 保底指标 vs 审查探针 vs 滑档 | `StructureVector.safety_floor`（指标）；`safety_guard` probe（评价）；`slip_risk`（解读场景） | 三个词都叫“安全/滑档” | 指标/探针/场景三层，不得互相替代；`slip_risk` 不写回 review | J2/J5 |
| 证据 | `EvidenceLedger`（上游 authoritative） | computed evidence 被写成可签发；`evidenceRefs` 与 caveats 混用 | MVP 不新签 computed；`evidenceRefs` 只引上游；推演结论走 `caveats/reasonCodes` | J2b |
| 事件 | `conversationAction.result` | `system.action`（已删除）、`proposal.preview` | `conversationAction.result` 是确认/执行唯一回执；`proposal.preview` 是预览；不再有系统动作事件 | J3 |
| 卡片 | `ProposalCard` / `InterpretationCard` | `SystemActionCard`（已删除）、review artifact（未实现） | 写/预览用 ProposalCard；解读用 InterpretationCard；不新增系统动作卡 | J2c |
| 能力 | `allowedCapabilities`（安全策略） | `review_read` 无消费者 | 只保留有消费者的能力；`review_read` 已从快照签发删除（2026-10-18）；J5 若需要读评价，另加 `planning.get_evaluation` | 已删除 |
| 命名空间 | 只读 `planning.*`，写/提案 `plan.*` | `plan.interpret_admission`（已改名） | 只读工具一律 `planning.*`；`plan.*` 只保留写/提案；测试锁定 | J2b |
| 工具身份 | MCP binding | 工具参数里的 `chatSessionId`（已删除） | MCP 工具不收 `chatSessionId/tenantId/sessionId/userId`；身份由 binding 注入 | J2b |
| 版本 | 当前**只有一个计数器** `stateVersion = planningState.version = workspace.version = snapshotVersion = sourceVersionGuard`；它会在 review/偏好/候选生成/补录时 +1，**不是内容版本** | 把它叫 `planVersion`/`workspaceVersion` 并声称“只随方案变化”；四种缓存 key | 保留 `stateVersion` 作为 CAS/guard 版本；新增 `planContentDigest = hash(working/ordered 内容)` 做内容版本；不新增第二个计数器 | J2a/J5 |
| 版本守卫 | `sourceVersionGuard` = `stateVersion`（同一个计数器） | 被说成“不是 planVersion” | 同一计数器、不同消费者；不得在别处新增第二计数器而不迁移；guard 仍与 `snapshot.snapshotVersion` 比 | J2a/J1 |
| 审查/解读版本 | `evaluatedStateVersion = ReviewStateDTO.sourceVersion`（review 计算时的 stateVersion）；`interpretedStateVersion = 工具 planVersion 输入` | 都叫 `planVersion`；review 后 stateVersion 已 +1，旧 findings 被当新 | `PlanEvaluation.plan_version` 用 `evaluatedStateVersion`；`AdmissionInterpretation.plan_version` 用 `interpretedStateVersion`；freshness 必须包含 `evaluatedStateVersion + planContentDigest` | J2a/J5 |
| 动作基准版本 | `PlanCommand.base_plan_version` = 执行所基于的 `stateVersion` | `IntentFrame.source_version`/`sourceVersionGuard` 混用 | 只在 `PlanCommand` 保留一个动作基准版本；IntentFrame 不再放版本字段 | J5 |
| 评价模型版本 | `objectiveModelVersion = hash(probeRegistryVersion, objectiveCompilerVersion, weightsVersion)` | 与 plan/candidate 版本混用 | 任何 probe/权重/目标层级变化都 bump；`evaluationVersion` 组合它 | J5 |
| 目标/约束归属 | `IntentFrame` 持有用户级 targets/scope/strength/riskPosture/priorityOrder；`PlanCommand` 只放 `resolved_targets` 和 `compiled_constraints` | 两处都放 targets/constraints/risk/priority | 用户级 vs 执行级分开；PlanCommand 不重复 IntentFrame 字段 | J5 |
| 模型契约 vs 归一化视图 | `ProposalRequest` 是模型唯一可写契约；`IntentDraft` 是模型可见的**完整意图草稿**（不是确认/不写状态）；`IntentFrame` 是内部归一化视图 | 三者各加字段/各定义强度 | `IntentDraft` 不得被当成有效约束；可执行语义仍要从它映射到 `ProposalRequest`/`PlanCommand`；`IntentFrame` 不新增用户语义 | B/J5 |
| 目标数量 | `selectionTargetCount`（用户确认目标，`HardPlanningObjectivesDTO`）；`requiredCount`（候选池需求；`Draft/Ordered.Summary.targetCount` 与 `targetUnitCount` 实际是它的别名）；`total`（实际条目；group 模式为 unit 数） | 四个名字互相当同义词 | 不合并，但写死：**用户目标=selectionTargetCount，候选需求/摘要 targetCount=requiredCount，实际=total（按模式）**；`targetUnitCount` 是 `requiredCount` 的单元模式别名，不是独立目标 | J4a/J5 |
| 冲稳保配额 | `tierQuotaGoal`（用户确认目标，经 `TierAllocationSupport.persist` 转成 `requiredTierCounts`）；`requiredTierCounts`（候选池/审查实际读的目标，按 `selectionTargetCount/requiredCount` 缩放成 `expectedTierCount`）；`StructureVector.tierCounts`（实际，group 模式按 unit、major 模式按 item） | 三者混用；review 实际读 `expectedTierCount` 不是 `tierQuotaGoal`；solver 另有 `resolvedTierCounts`/`historicalTierAnchor` | 目标/计划/实际分开；review 读 `expectedTierCount`，solver 用 `requiredTierCounts/resolvedTierCounts`，回执写 actual；不一致要诊断，不静默 | J5.4 |
| 意向生命周期 | **目标态** `本次调整 / 本会话后续规划`（不是已有 `persist=once|session` 字段）；当前 `persistTargetCount` 只是“是否把 targetCount 写进 requiredCount”，不是意向生命周期 | `targetScopes`/`negativeScopes` 通过 `apply_constraint_and_regenerate` + `updateConstraintState` 持久化到 hard/soft preferences，并触发重排；`tuitionRange` 持久化到 `userScoreDetail`（直接写不重排，提案命令会重排）；`requirements`/`priorityRules` 应用时持久化；没有统一 owner | 先做行为真值表（已回填 `2026-10-18-constraint-lifecycle-truth-table.md`）；卡面按真实行为写；目标态一个 owner、学费不重复存储、未确认草稿不成为有效约束；不得把 `persistTargetCount` 当生命周期字段 | A/B |

## 二、明确“合并/删除”的清单

### 2.1 现在就删（设计层）

- 删除 `system.action` 事件、`SystemActionCard`、自动生成/重排叙事（当前无生产者）。
- 删除 `review_read` 的“修法/能力承诺”（无消费者）。
- 删除 `plan.interpret_admission` 命名（已改 `planning.interpret_admission`）。
- 删除 MCP 工具参数里的 `chatSessionId` 身份字段。
- 删除“computed evidence 已签发”的验收口径。
- 删除 `scenarioDepth`、`prefer` goalType、`last_action` 等未实现/不存在的语义。

### 2.1b `ReviewCheckDTO` 字段收敛（同一语义只留一个）

| 旧字段 | 新语义 | 处置 |
|---|---|---|
| `category` | 旧 UI 分组（`structure_risk`/`ordering_risk`/`item_risk`/`major_group_risk`/`policy_notice`），**不批量映射成 layer** | 保留为旧分组；`layer` 按 **code 逐条**指定（`item_risk` 里 admission_limit 是硬、high_tuition 是软）；`notice` 只是 severity |
| `severityDefault` | probe 的默认 severity（规则元数据） | 留在 probe 定义，不进 finding |
| `severity` | 本次评价的 severity（实例） | 唯一权威；finding 只保留这个 |
| `code` vs `reasonCode` | `code`=probe/规则 id；`reasonCode`=本次评价的具体原因 | 两个都保留，但不得互相替代 |
| `label` | 静态规则名 | 留在 probe 元数据 |
| `summary`/`detail` | 本次评价的用户语言摘要与细节 | finding 保留 `summary`；`detail` 可放内部诊断 |
| `level`（risk/warn/info） | 旧四态，前端过渡回退 | **deprecated**；前端切到 severity 后删除 |
| `supportedFixStrategies`/`defaultFixStrategy` | probe 的修复能力声明 | 留在 probe 元数据 |
| `suggestedCompensations`/`suggestedAction` | `EvaluationFinding.objectiveDelta`/`suggestedCommand` + `reasonCodes` | 合并；旧字段只做展示适配 |
| `evidenceSchema`/`postApplyValidationRule` | probe 元数据 | 留在 probe；不进 finding |
| `affectedUnitIds`/`affectedVolunteerIds` | `affectedEntryRefs`（level+id） | 合并；旧 id 列表做投影 |
| `targetModes`/`scopeKind`/`fixability` | probe 适用域 | 留在 probe 定义 |
| `ReviewState.compensationPreview` | findings 的 suggested_command 汇总视图 | 不独立定义修复；J5 后由 findings 生成 |
| `ReviewSummaryDTO.riskCount/warnCount` | 旧 `level` 计数（**包含 passed=true 的 check**，如缺生源省 safety_guard） | 不能直接映射成 action/notice；保留 legacy，新增 findings 计数并行；`PlanningWorkflowStatusBuilder`/ProposalCard/WorkspacePanel 迁移且 golden 后再删 |
| `ReviewSummaryDTO.block/action/notice/info/passed` | 新 severity 计数 | 保留为 `ReviewState` 视图的 summary |

### 2.2 J4a/J5 合并（代码层）

- `ReviewStateDTO/ReviewCheckDTO` → `PlanEvaluation/EvaluationFinding`（保留单向适配器）。
- `ReviewRuleRegistry` → `EvaluationProbeRegistry`（severity 跟着 probe/finding 走）。
- `RepairProposalTaxonomy` **只迁 Strategy 的 review 语义**到
  `EvaluationFinding.code/reasonCodes`；`Status`（ready/preview_only/blocked/info/
  empty）、`ProposalSource`、`ActionType`、`CompensationActionType` 是修复提案的
  执行/应用协议，保留到 J5.5 `PlanCommand` 完整替代后再删。不要整体删除。
- `RepairDryRunSimulator` **不要一刀删**：它还承担 add/plan 的 dry-run（inversion/
  gap/数量检查）；先拆成“评价探针”和“plan dry-run 适配器”两部分，后者等 J5
  solver 的 dry-run 接上再删。
- `plan-final-review` 的私有规则 → `PlanEvaluator` 的 probe；技能只做叙述。
- legacy `PlanGoalTypeValue` 的 **mutation 子集** / 旧 atomic actions → `PlanCommand`
  映射；`query_state`/`clarify`/`prefer_scope`/`rebalance_structure`/`reduce_risk`/
  `mixed_adjustment` 留在 legacy/`IntentFrame.goal_family`，不强行变成单条命令。
- `add_units` / `replace_units` → `PlanCommand.add` + `addPolicy`（Java 执行适配可保留
  两条，但语义只有一条）。
- `OrderedUnitDTO.admissionRatio` 的模糊语义 → 显式 `schoolEnrollRatio` /
  `majorAdmissionRatio`；旧字段标 deprecated，前端/模型不再依赖。
- `actualChanges`/`reviewState` 传输字段 → 从 `PlanReceipt`/`PlanEvaluation` 投影，
  不再有独立定义。

### 2.3 明确保留、不合并（语义不同）

- `planningStage`（方案生命周期）≠ `JourneyContext.phase`（对话位置）。
- `allowedCapabilities`（安全策略）≠ 旅程阶段。
- `proposalRequest.goalType`（模型词汇）≠ `PlanCommand`（内部命令）。
- `PlanEvaluation`（评价）≠ `LandingScenario`（录取推演）。
- `targetCount` / `selectedCount` / `unitCount` / `requiredCount` 语义不同，保留但命名写清：
  - `targetCount`：用户/系统确认的目标条目数（`selectionTargetCount`）；
  - `selectedCount`/`total`：方案实际条目数；
  - `unitCount`/`targetUnitCount`：专业组模式下单元数；
  - `requiredCount`：候选池为满足目标需要的候选数，不是方案目标。
- `schoolEnrollRatio`（校级）≠ `majorAdmissionRatio`（专业级）。
- `rankInTier`（推荐排序）≠ 历史位次。

## 二·五、ID 语义权威表

| ID | 权威定义 | 用途 | 禁止 |
|---|---|---|---|
| `volunteerId` / `entityId` | 方案行键，不保证固定两段：`planSchoolDataId_<planMajorDataId|majorId|majorUnitCode|majorName>`，真实可出现 2 段或 3 段 | 候选/预览/方案条目 join；major 模式 `EntryRef` | 假设恒为 `planSchoolDataId_majorId`；当作 `admissionUnitId`；把两个单元拼成一条 |
| `unitId` | 专业组单元键：`volunteerId` **第一个 `_` 前段**（`resolveWorkingPlanUnitId`）；legacy 匹配另有 `legacyVolunteerPrefix` 取前两段，二者不能混 | unit 模式 `EntryRef`；方案单元 | 取“前两段”；当作专业级 id |
| `planSchoolDataId` | 院校计划行 id | 单元/条目构建、方案行 | 当作招生单元号 |
| `majorId` / `schoolId` | 专业/院校目录 id | 实体解析、资格/计划查询 | 与方案行键混用 |
| `admissionUnitId` | 招生单元号（证据/事实口径） | `admissionFacts`/证据绑定 | 用 `volunteerId`/`unitId` 冒充 |
| `operationId` | 一次 pending/prepare 的幂等键（Java 产出） | 确认链、去重 | 网关自行生成/替换 |
| `chatSessionId`/`tenantId`/`userId` | 会话身份 | 由票据/binding 注入 | 作为 MCP 工具参数或模型可改字段 |

规则：**同一结论里只能出现同一套 ID**；跨套比较要先显式映射，并在回执/证据里
标注 `idScheme`（`volunteer`/`unit`/`admissionUnit`）。

## 三、迁移与兼容规则

1. **单向适配**：旧 DTO → 新 DTO 只允许单向；禁止新逻辑读旧 DTO 的独立语义。
2. **双写期**：J4a/J5 迁移期允许旧字段继续存在，但新路径只写新字段；回执标
   `legacy_view=true`，便于排查。
3. **删除门槛**：旧字段/旧规则在“新路径连续 N 个 golden 会话无差异 + 一个发布周期”
   后删除；删除前必须有一份对照报告。
4. **回滚**：每个合并/删除都要能通过 feature flag 回到旧路径；不能回滚的不做。
5. **测试**：同一输入下，旧 review 结论与新 `PlanEvaluation.findings` 的
   severity/affected ids 必须可对照；差异要解释（例如旧规则缺失）。

## 四、审查问题清单（独立审查用）

1. 是否还有两个 DTO 各自定义同一个语义（例：review severity vs evaluation severity）？
2. 是否有“适配器反向定义语义”（旧字段决定新字段）？
3. 是否有同一指标在 review/interpretation/receipt 三处各算一遍？
4. 是否有未实现/无消费者的能力/事件/字段仍在规范性文本里？
5. J4a/J5 的删除清单是否遗漏 legacy 路径（add/remove/move/sort/pin）？
6. `tier`/`schoolEnrollRatio`/`majorAdmissionRatio` 的语义是否在 Java/Python/前端
   三处一致？
7. `PlanCommand` 与 `proposalRequest.goalType` 的映射是否穷尽、是否有未映射动作？
8. 删除后回滚路径是否存在？
