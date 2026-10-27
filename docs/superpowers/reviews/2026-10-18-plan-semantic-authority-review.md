# 方案语义权威表与 v4 设计独立审查

日期：2026-10-18
对象：

- `docs/superpowers/specs/2026-10-18-plan-semantic-authority-map.md`（下称“权威表”）
- `docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`（v4，下称“设计”）
- `docs/superpowers/plans/2026-10-18-journey-control-and-admission-interpretation.md`（v4，下称“计划”）

基线：`616464c`（`wip/2026-09-28-p2-write-loop-green`，工作区含 add_units EXPAND 未提交改动）
方式：只读审查；未改代码/文档、未跑测试、未部署。

**审查快照说明**：审查期间这三份文档在 09:29–09:36 之间被连续修订（权威表从 10KB
增至 19KB，设计增至 89KB）。本文按 **09:36 的最终快照**审计；行号以该快照为准。
文档若在本文之后再改，需按本文的“编辑清单”复核，不能只看旧结论。

## 〇、结论

**BLOCK。**

方向是对的：把审查、优化、解读收成同一套 `StructureVector`/`PlanEvaluation` 是
正确的架构方向；权威表新增的“目标/实际/配额”“顺序异常 vs 概率倒挂”“保底指标/
探针/滑档”等分层也确实是语义不同的东西，应该保留。**但当前文本还不能作为 J2a/J5
的实现依据**，原因不是“还需要抽象”，而是：

1. **审查与优化合并的输入模型不成立**：`StructureVector` 只有结果指标，没有
   probe 复算所需的输入（逐条 ratio/tuition/riskFlags、`selectionTargetCount` 与
   `requiredCount`、生源省、userScore、admissionMode）。照当前表把 14 个 check
   改成 7 个 probe，会**静默改变** `ratio_distribution`（unit vs item 计数）、
   `probability_inversion/gap`（`admissionRatio` vs `schoolEnrollRatio`）、
   `count_validation`（双数量 vs 单 target）的现有结论。这不是去重，是改语义。
2. **版本/新鲜度定义与代码相反**：`workspace.version == planningState.version ==
   snapshotVersion == sourceVersionGuard`，且 `runReview` 自己会 +1。所谓
   “planVersion 只随方案变化”“两个版本分开”不成立；按当前
   `evaluationVersion`（不含 review 的 `sourceVersion`）会把旧审查结论认证成新。
3. **J1a 的 `stale`/`pendingStatus` 按文本实现必然错误**：`StaleFlagsDTO` 永远非
   null（`stale` 恒 true）；`getCurrent` 任意取一行且 `fillActiveProposal` 只认
   `active`，`applying` 永远到不了 journey。
4. **`$ref` 是不存在的前提**：Java 侧没有任何 `$ref` 解析；实际机制是
   `candidatePoolRef` 拆分池，`loadPlanningStateReadOnly` 已经回填。J2b 按计划
   去找“既有 `$ref` 解析器”会找一个不存在的东西。
5. **若干“合并/删除”是错的或不安全的**：`category → layer`、`riskCount/warnCount
   → action/notice`、`RepairProposalTaxonomy` 整体删除、`OrderedUnitDTO.admissionRatio`
   删除、`PlanGoalTypeValue` 整体映射、`must_include_scope` 只覆盖已有条目。
6. **评价/动作契约仍不可编译**：`PlanEvaluationDTO` 与设计字段不一致；
   `StructureVectorDTO` 没有字段；Java 侧没有 `ObjectiveDelta`/`PlanCommand`/
   `ConstraintPatch` DTO；`ObjectiveDelta.add_targets` 用必填 `position/pathTier`
   的 `EntryRef` 表示“待加入目标”；`objective_delta` 与 `suggested_command`
   无优先级/一致性约束。
7. **证据与只读边界仍有自相矛盾**：设计 §9.1 仍写“Java 计算证据已签发”，与
   §8.2/计划/J2b 的“不新签 computed”冲突；`resolveEffectiveCandidates(..., true)`
   会刷新并落 overlay，解读服务若复用就不是只读；join 用 raw pool 还是
   effective candidates 未定义。
8. **ID 表写错**：`unitId` 是 `volunteerId` 第一个 `_` 前段（不是“前两段”）；
   `volunteerId` 也不总是 `planSchoolDataId_majorId`。unit 模式的 `EntryRef`/
   join 会因此指错行。

这些都不是“实现时再定”的细节：J2a 的 DTO/真值表、J1a 的旅程事实、J5 的评价
输入，三者都直接依赖上面的定义。建议先把 B1–B8 的设计修订做完，再进入 J2a。
**修订量以文档为主，不需要推翻整体架构。**

---

## 一、权威表逐行审计

图例：

- **OK**：owner、重复项、处置与代码/设计一致。
- **TARGET**：方向正确，但 owner 目前不存在，必须标明“目标态”，不能让执行侧
  去找一个当前类。
- **INCOMPLETE**：方向对，但定义不足以实现（缺字段/缺来源/缺映射）。
- **WRONG**：与代码或设计事实不符。
- **UNSAFE**：按当前处置执行会改变行为或破坏现有消费者。

| 语义 | 结论 | 依据与说明 |
|---|---|---|
| 方案生命周期 | OK | `planningStage` 值域与 `PlanningStateService` 的 `setPhase`（618/1759/2592/2906）一致；`ConversationSnapshotService:46` 用 `workspace.phase`。注意偏好/约束 touch 会把 phase 写回 `profile_ready`（2931/2955），这是既有行为，不是新语义。 |
| 方案状态存储 | WRONG | `$ref` 不存在（见 B4）；遗漏 `recommendationOverlayState`（`PlanningStateDTO` 的 overlay）与 `candidateViewState`。`draftPlanState` 兼容别名属实（`PlanningWorkspaceStateRes` 的 `@Deprecated` getter/setter）。 |
| 对话位置 | INCOMPLETE | `taskIntent` 没有生产者：`TurnOutput`（`contracts.py:509-527`）没有 `taskIntent` 字段；设计 251-255 只说“模型动作派生”，没有映射表/落点。`allowedCapabilities` 只做能力门禁属实（`tools_readonly.py:399-405`）。 |
| 用户动作（内部） | WRONG/UNSAFE | `PlanGoalTypeValue` 的 10 类里 `query_state`/`clarify`/`prefer_scope`/`rebalance_structure`/`reduce_risk`/`mixed_adjustment` 不是 plan mutation，不能整体映射成 `PlanCommand`；该枚举仍被 legacy `app/service.py:2068` 使用。Java 5 个 commandType 里 `update_score_detail` 是 profile 写，不属于 plan command（设计 §7.7 自己也这么说）。Java `apply_constraint_and_regenerate`/`apply_plan_change_proposal` 是复合执行适配，不是 1:1 命令。 |
| 加入语义 | WRONG | “`must_include_scope` 只做方案已有条目的覆盖”与代码不符：`UserGoalProposalBuilder.buildMustIncludeProposal`（1705-1730）在方案没有匹配时会从候选补入；满方案时最多替换 1 组。应写“覆盖/补入/最多替换 1 组”，不能简化成“已有条目”。另外模型契约没有 `addPolicy` 字段（`ProposalRequest` 321-405），REPLACE 目前不可表达。 |
| 候选事实 | INCOMPLETE | 三套（raw/effective/agent artifact）属实；但没写 `recommendationOverlayState`（合并进 effective）与 `candidateViewState`（UI 视图）。J2a “ordered plan + join”没有说 join 哪一套；若 join raw pool 与 effective 的资格/学费过滤不同，同一方案会得到不同 majorRatio。 |
| 档位 | WRONG/UNSAFE | Java 生产边界 `<=50/<=70/>70` 属实（`VolunteerIntervalService.java:96-101`）。但 Python `derive_risk_tier` 是 `<50/<70`（`admission/facts.py:53-61`），且被 gateway `AdmissionFact` 校验使用（`contracts.py:144-148`）：恰好 50/70 时模型契约与 Java 候选档位相反。权威表没列这个重复定义。另 `OrderedUnitDTO.admissionRatio` 不是“只影响前端/模型”：review 的 `probability_inversion/gap` 与 `MajorGroupUnitQuality` 都在读它（见 B5）。 |
| 历史位次 | OK | `rankInTier` 是推荐排序名次（`PlanningStateService` 的排序/`rankToScore` 使用）；历史只在 `CandidateItemDTO.*HistoryScores`。 |
| 分数字段 | INCOMPLETE | `finalScore/baseScore/intentScore` 的映射与 `PlanningStateService:9333-9337` 一致；遗漏 `futureDevelopmentScore`（career v1 的另一个分数），且 `finalScore` 在缺 `volunteer_score` 时会用 `rankToScore(rankInTier)` 回退（9337/9367），不能当权威录取分。 |
| 优化目标 | TARGET/INCOMPLETE | `ObjectiveModel`/`ObjectiveCompiler` 目前不存在；设计 §7.1 只给字典序层级，没有 dataclass/字段/权重版本。更关键：已有 `CanonicalPlanningObjectiveSetDTO` + `PlanSolverResultDTO`（含 `objectiveDigest`/`solverVersion`/`inputDigest`/`ObjectiveResultDTO`/`DiagnosticDTO`）就是现成的 canonical objective/solver 模型；权威表完全没提，等于允许第三套目标模型。 |
| 方案评价 | TARGET/INCOMPLETE | `PlanEvaluation` 是目标态。当前 `ReviewCheckDTO` 才是评价载体；计划里的 Java DTO 与设计字段不一致（见 B6）。`metric` 的枚举键、`threshold` schema 都没有定义。 |
| 审查生命周期 | TARGET | `ReviewState` 薄视图（status/evaluatedAt/evaluationVersion/summary + PlanEvaluation 引用）目前不存在；`ReviewStateDTO` 仍同时承载规则/检查/摘要/补偿预览。必须标“J5 目标态”。 |
| 方案审查 | OK（方向）/INCOMPLETE | “技能只叙述”是 J5 目标；但 `plan-final-review` 的私有规则里至少有一条后端没有的检查：**发展方向覆盖核对**（技能 step 3b，`careerTypes` 承接证据）。技能改成纯叙述后这条会消失，除非 `PlanEvaluator` 新增 `direction_coverage` probe。见 M6。 |
| 审查运行 | OK | `ReviewWorkflowRunRes` 确实是运行/传输结果；与 `ReviewState` 分开是对的。 |
| 审查版本字段 | WRONG | `ReviewStateDTO.sourceVersion` 不是在 review 之后写当前版本：`runReviewInternal` 在 2871 先 `setSourceVersion(state.getVersion())`，2905 再 `state.setVersion(+1)`。所以 review 结束后 `sourceVersion = 当前 stateVersion - 1`。权威表说它“不参与新缓存/结论”，但设计 §9.1 的 join 索引缓存又把它放进 key（1140-1142）；`evaluationVersion` 又不含它（857-859）。三种口径同时存在（见 B2）。 |
| 方案变更回执 | TARGET/UNSAFE | `PlanReceipt` 不是当前 producer：实际回执是 `ConversationActionResult`（`conversation_actions.py:59-78`），它**丢掉了** `operationId`/`postconditionReport`；`server.py:_action_result_payload` 只带 proposalRef/actionStatus/newStateVersion/actualChanges/reviewState。若现在把 `actualChanges/reviewState` 说成“PlanReceipt 的投影”，适配器就会反向定义语义（旧字段决定新回执）。 |
| 修复预览 | OK（过渡）/INCOMPLETE | `FixProposalStateDTO/FixProposalDTO` 现存在；但其生成依赖 `ReviewCheckDTO` 的 `scopeKind/defaultFixStrategy/requiresConfirmation/affected*`（`RepairProposalStateBuilder:110-158`）。若 probe/finding 不带这些元数据，修复链无法从 findings 重建。权威表 2.1b 说“留在 probe”，但没定义 `EvaluationProbeRegistry` 的字段。 |
| 预览 vs 执行回执 | OK | `PrepareResultDTO`/pending 与执行回执分开是对的。 |
| 结构指标 | INCOMPLETE/UNSAFE | `StructureVector` 字段（设计 696-706）缺：unknown tier 计数、`coverage` 的 key 集合、`safety_floor` 的 key 集合、`diversity` 的定义、`target_count` 指哪一个目标、`duplicates` 的判据。且 `tier_counts` 与 `unit_tier_counts` 在现有代码里是同一份 item 计数（`WorkingPlanMutationSupport:151-163`），却被定义成两个指标；major_group 的 review 又按 unit 计数（`PlanningStateService:10717-10727`）。 |
| 执行后置条件 | OK（概念） | 与 review 分开是对的；实际 DTO 名为 `PlanChangePostconditionReportDTO`，权威表用泛名 `PostconditionReport`，建议写准。 |
| 覆盖 vs 数据完整度 | OK（概念）/INCOMPLETE | `dataCompleteness` 改名方向对；但 `dataCompletenessBand` 的阈值没定义（设计 1126 只给字段名），J2c 卡片无法确定“完整/有缺口”。 |
| 覆盖目标 vs 覆盖实际 | OK（概念） | `coverageRequirements` 确实存在（`CanonicalPlanningObjectiveSetDTO`）；`StructureVector.coverage` 的 key 集合需与 `CoverageRequirementDTO` 对齐，否则“同一组 keys”只是口号。 |
| 录取解读 | OK | `LandingScenario` 与 `PlanEvaluation` 分开、`slip_risk` 不写回 review 是对的。 |
| 顺序异常 vs 概率倒挂 | OK（概念）/WRONG（probe 口径） | 两个指标确实不同。但设计 probe 表把 `probability_inversion` 写成“有序条目的 `schoolEnrollRatio`”（设计 847），而代码 group 模式用 `unit.getAdmissionRatio()`、major 模式用 `candidate.getAdmissionRatio()`（`PlanningStateService:10889-10890,10897-10898,10957-10958,10997-10998`）。这是行为改变，不是同一指标。 |
| 保底指标 vs 审查探针 vs 滑档 | OK（分层）/INCOMPLETE | 三层分开是对的；`safety_floor` 没有 key/schema。现有 `safety_guard` 还有 `userScore >= 580` 短路与“缺省份时 passed=true、level=warn”的语义（10810-10836），单纯一个 `safetyFloor` 计数无法复现。 |
| 证据 | OK（原则）/WRONG（文本） | 设计 §8.2 的“不新签 computed”正确；但 §9.1 第 1118 行仍写“返回 AdmissionInterpretation + evidenceRefs（Java 计算证据已签发）”，权威表 2.1 又说要删这条验收。三处不能同时成立（见 B7）。 |
| 事件 | OK | `system.action` 全仓无引用；`conversationAction.result` 是唯一动作回执。注意它也是 cancel 的唯一回执，写“确认/执行”略窄。 |
| 卡片 | OK（方向）/INCOMPLETE | `SystemActionCard` 无引用；`InterpretationCard` 未实现。review artifact 的契约冲突未处理：`TurnOutput` 对 `responseType=review` 强制 `artifactRefs`（`contracts.py:534-539`），而 `ArtifactStore` 只接受 candidate/comparison（`artifact_store.py:80-81`），review artifact 无处签发。 |
| 能力 | OK | `review_read` 只在 `ConversationSnapshotService:183-185` 签发，gateway 总是 `skill=None`（`service.py:1389/1640/1731/…`），无消费者；删除安全。注意能力是硬门禁（`tools_readonly.py:399-405`），新工具必须挂 `admission_read`。 |
| 命名空间 | OK（约定） | `READONLY_TOOL_NAMES = frozenset(CAPABILITIES)`（`server.py:43`），测试断言无 `plan.` 前缀（`test_domain_mcp_tools.py:45-46`）。MCP 目前没有写工具，`plan.*` 只是未来约定，建议写清。 |
| 工具身份 | OK | `_trusted_arguments` 丢弃 `chatSessionId/tenantId/sessionId/userId/threadId/handle/stateVersion`（`tools_readonly.py:533-537`）。 |
| 版本 | WRONG | 见 B2。`workspace.version` 就是 `state.version`（`PlanningStateService:265-266`），`snapshotVersion` 也取自它（`ConversationSnapshotService:43`），`sourceVersionGuard` 也跟它比（`output_validation.py:118`）。说“两个版本分开”“不是 workspace.version”与代码相反。`planVersion` 也不是纯内容版本：review/偏好/候选生成都会 +1。 |
| 版本守卫 | WRONG（措辞） | “与 snapshotVersion 比”是对的（`output_validation.py:118`、`service.py:1418/1518`）；但“不是 planVersion、不能互相替代”暗示有两个计数器，而当前是同一个。应改为“同一计数器，不同消费者；不得在别处新增第二个计数器而不迁移”。 |
| 动作基准版本 | INCOMPLETE | `PlanCommand.base_plan_version` 是目标态；当前执行基准是 `expectedPlanVersion`，来自 `activeProposal.sourceVersion`/`sourceVersionGuard`/`snapshotVersion`（`conversation_actions.py:850-857,886-932`），也都是同一个 stateVersion。 |
| 评价模型版本 | TARGET/INCOMPLETE | `hash(probeRegistryVersion, objectiveCompilerVersion, weightsVersion)` 的三个版本都不存在；且与已有 `solverVersion`/`canonicalObjectiveDigest`/`inputDigest` 的关系未定义。 |
| 目标/约束归属 | INCOMPLETE | 设计 `PlanCommand` 仍持有 `intent: IntentFrame`（733-741），而 `IntentFrame` 又含 targets/scope/risk/priority；权威表说“PlanCommand 只放 resolved_targets/compiled_constraints”，与 dataclass 不一致。需明确 `intent` 只是 provenance、solver 只读 resolved/compiled，或从命令里删掉 `intent`。 |
| 模型契约 vs 归一化视图 | WRONG | `IntentFrame.lifecycle`/`risk_posture`/`priority_order`（设计 526-529）在 `ProposalRequest` 里没有对应字段（只有 `persistTargetCount`、`priorityRules`，且语义不同）。因此“IntentFrame 不新增 ProposalRequest 没有的用户语义”不成立；这三项只能标“J6 前为 null/不可路由”。 |
| 目标数量 | WRONG | 2.3 的定义与代码不符：`Draft/Ordered.Summary.targetCount` 实际等于 `candidatePoolState.requiredCount`（`PlanningStateService:13392-13409`、`WorkingPlanMutationSupport:143-163`），不是 `selectionTargetCount`；`total` 在 group 模式是 unit 数（`countOrderedSummaryTotal` 去重 unit），不是条目数；`targetUnitCount` 也是 `requiredCount` 的别名。`selectionTargetCount` 只在 `HardPlanningObjectivesDTO`（review 的 `expectedTierCount` 会用它缩放）里。 |
| 冲稳保配额 | WRONG | 表说“review 读 `tierQuotaGoal`”，实际 `ratio_distribution` 读 `expectedTierCount`（`PlanningStateService:10782-10808`），来源是 `candidatePoolState.requiredTierCounts` 按 `selectionTargetCount/requiredCount` 缩放；`tierQuotaGoal` 只经 `TierAllocationSupport.persist` 转成它。还遗漏 solver 的 `resolvedTierCounts`/`historicalTierAnchor`（`PlanSolverResultDTO`）。 |
| 意向生命周期 | WRONG/INCOMPLETE | `persist=once|session` 不存在。现有字段是 `persistTargetCount`（`contracts.py:344-349`），语义是“是否把 targetCount 落进 `candidatePoolState.requiredCount`”（`PlanningStateService:1104`、`UnifiedPlanPostconditionValidator:66-91`），不是“意向持久化”。`requirements/priorityRules` 已经持久化（`ProjectedHardRequirementSupport.persist`/`PriorityRuleSupport.persist`，`PlanningStateService:1077-1078`）；`targetScopes/negativeScopes` 走 constraintUpdate + userprofile 两处；`tuitionRange` 走 `ChatSessionBizService.updateTuitionRange`。J4a 前必须定唯一 owner。 |

### 1.1 ID 语义权威表审计

| ID | 结论 | 依据 |
|---|---|---|
| `volunteerId`/`entityId` | WRONG | 不是恒等于 `planSchoolDataId_majorId`：`legacyMajorVolunteerId` 用 `planSchoolDataId + (planMajorDataId｜majorId｜majorUnitCode｜major_name)`（`PlanningStateService:10627-10656`），真实测试里出现 `41020261005650_553`（两段）与 `37020261000734_37020262013962_37020262013962`（三段）。 |
| `unitId` | WRONG | 实际取 `volunteerId` **第一个** `_` 前段（`WorkingPlanMutationSupport.resolveWorkingPlanUnitId:236-243`；`UserGoalProposalBuilder.unitIdPrefix:3037-3044`；`CanonicalPlanningRuntime.workingUnitId:505-509`），不是“前两段”。另有一个只用于 legacy 匹配的 `legacyVolunteerPrefix` 取前两段（`WorkingPlanMutationSupport:217-226`），两者不能混。 |
| `planSchoolDataId` | OK | 是单元主键/院校计划行 id；`resolveInitialRecommendationUnitId` 优先返回它（4705-4715）。 |
| `majorId`/`schoolId` | OK | 目录 id；不要与方案行键混。 |
| `admissionUnitId` | OK | 证据/事实口径；不要用 volunteerId/unitId 冒充。 |
| `operationId` | OK | Java prepare 产出；网关不得自铸（`conversation_actions.py:823-839`）。 |
| 身份字段 | OK | binding 注入；`_trusted_arguments` 丢弃。 |

**结论**：ID 表是“看起来最安全、实际最容易写错”的一节。unit 模式的 `EntryRef.id`
直接依赖 `unitId`；按“前两段”实现会把 `planSchoolDataId_majorId` 当成 unit，和
`OrderedUnitDTO.unitId`（=planSchoolDataId）对不上，join/证据都会指错。

---

## 二、Blockers

### B1. “审查 = 优化评价面”目前不可实现，且会静默改变现有审查结论

**证据**

- 设计把 `StructureVector` 定为 review/probe/solver/回执/解读共用的**唯一**结构
  定义（696-709），probe 表只列 7 个 check（839-853）；实际 `runReviewInternal`
  跑 14 个 check（`PlanningStateService:2879-2894`，`ReviewRuleRegistry:53-127`）。
- `StructureVector` 没有复算 probe 所需的输入：
  - `count_validation` 需要 `selectionTargetCount`、`requiredCount`、当前数、模式，
    并按结果动态给 `block/action/info`（`PlanningStateService:11036-11120`）；
    `StructureVector.target_count` 只有一个数。
  - `ratio_distribution` 的期望档位是 `requiredTierCounts` 按
    `selectionTargetCount/requiredCount` 缩放（`PlanningStateService:10782-10808`）；
    `StructureVector` 没有 `requiredTierCounts`/`selectionTargetCount`。
  - `safety_guard` 有 `userScore >= 580` 短路、生源省、本省保底 unit/volunteer 计数
    （10810-10885）；`StructureVector.safety_floor` 没有 key/阈值/生源省。
  - `probability_inversion/gap` 在 group 模式读 `OrderedUnitDTO.admissionRatio`
    （10889-10890、10957-10958），major 模式读 `CandidateItemDTO.admissionRatio`
    （10897-10898、10997-10998）；设计 probe 表写的是 `schoolEnrollRatio`。
  - `group_inner_safety_guard` 读每个 unit 内每个 major 的 `admissionRatio` +
    `schoolEnrollRatio`（11170-11179）；一个 `safetyFloor` 计数不够。
- `ratio_distribution` 在 group 模式按 **unit** 计数（10717-10727），而
  `Draft/OrderedPlanState.Summary.tierCounts` 按 **item** 计数
  （`WorkingPlanMutationSupport:151-163`）。`StructureVector.tier_counts` 若取自
  summary，group 模式审查结论会变；若取自 review，则和回执/方案摘要不一致。
- `group_inner_safety_guard` 的 registry severity 是 `block`
  （`ReviewRuleRegistry:116-121`），probe 表却写 `layer=structure`；设计新规则
  “hard 只能配 block、structure 只能配 action/notice”（设计 828-832）会直接拒绝
  这个组合。`count_validation` 的 `block/action/info` 动态 severity 也无法塞进
  固定 `layer=hard`。
- “probe 表例如”只给 7 个；`admission_limit`/`special_enrollment`/`edge_score`/
  `cooperative_program`/`major_group_safety_intent_alignment`/
  `plan_update_notice`/`adjustment_notice` 没有 layer/metric 映射。

**为什么阻塞**

这不是抽象问题：J5.2 的验收就是“旧 review 结论与新 findings 的 severity/
affected ids 可对照”。按当前表实现，至少 4 个 check 会给出与旧路径不同的
pass/fail 或 severity，且没有 golden 对照报告；同时 J2a 的解读 drivers/caveats
来自这些 findings，用户看到的“滑档/梯度”依据会被改变。

**最小修复**

1. 明确两类东西，不要混：
   - **评价输入快照**（`EvaluationContext`）：entries（EntryRef + admissionRatio/
     schoolEnrollRatio/tuition/riskFlags）、`selectionTargetCount`、`requiredCount`、
     `requiredTierCounts`、`admissionMode`、生源省、userScore、candidateSourceVersion。
   - **结构结果**（`StructureVector`）：只放输出指标，并写清每个指标的 key/口径。
2. 把 14 个 check 全部列成 probe 表：code、layer、允许 severity、metric key、
   threshold、affected refs、修复策略元数据；不许再写“例如”。
3. 每个 probe 明确它读的是 unit 还是 item、admissionRatio 还是 schoolEnrollRatio；
   若要与旧路径不同，必须在 J5.0 golden 里记录差异并得到用户确认。
4. 修正 layer/severity 合法组合：`group_inner_safety_guard` 应为 hard（block）；
   `count_validation` 若保留动态 action/info，则 layer 不能固定为 hard，或规则要
   允许 hard+action（推荐前者：把“数据不足”单独成 probe）。
5. `StructureVector.tier_counts` 明确“major 模式=item 计数、group 模式=unit 计数”，
   或拆成 `entry_tier_counts`/`unit_tier_counts`，并让 `ratio_distribution` 按模式
   选其中一个。

### B2. 版本/新鲜度语义与代码相反，且会把旧审查认证成新

**证据**

- `PlanningWorkspaceStateRes.version = state.version`
  （`PlanningStateService:265-266`）；`ConversationTurnSnapshotDTO.snapshotVersion`
  取自 `workspace.version`（`ConversationSnapshotService:43`）；
  `sourceVersionGuard` 与 `snapshot.snapshot_version` 比（`output_validation.py:118`，
  `service.py:1418/1518`）。**当前只有一个计数器。**
- 它不是“只随方案变化”：`runReviewInternal` 在审查后 `state.setVersion(+1)`
  （2899-2906，方案内容未变）；偏好/约束 touch 也 +1（2929-2932、2953-2956）；
  候选生成（1759-1760）、补录（617）等都 +1。**review 本身就会让 planVersion 变。**
- `ReviewStateDTO.sourceVersion` 在 review 开始时写入，随后 stateVersion +1
  （2871 vs 2905）；review 结束后 `sourceVersion = 当前 stateVersion - 1`。
- 设计 §7.8 的 `evaluationVersion = hash(planVersion, candidateSourceVersion,
  dataFreshnessState.dataVersion, objectiveModelVersion)` 且明确“reviewState.
  sourceVersion 不进入核心评价版本”（857-859）。如果 adapter 在解读时用当前
  `planVersion` 组装 findings，而 findings 来自上一次 review（sourceVersion 更旧），
  `evaluationVersion` 会显示“新”，但结论是旧的。
- 缓存 key 至少有四种写法：
  - 设计 1115：`planVersion + candidateSourceVersion + dataVersion + objectiveModelVersion`
  - 设计 1140-1142：`planVersion + candidateSourceVersion + dataVersion + reviewState.sourceVersion`
  - 设计 1385：`planVersion + candidateSourceVersion + dataVersion + admissionMode`
  - 计划 114：`planVersion + candidateSourceVersion + dataVersion + objectiveModelVersion`
  四个都叫“缓存键”，实现侧只能猜。
- 权威表/设计/计划对 `planVersion` 的声明互相矛盾：
  - 设计 373-375：`planVersion = planningState.version`、
    `workspaceVersion = workspace.version`，“两者不混用”；
  - 设计 1113-1114：`planVersion` “不是 `workspace.version`/`snapshotVersion`”；
  - 计划 176：`planVersion=planningState.version`（不是 workspace.version/
    snapshotVersion）；
  - 代码：workspace.version 就是 planningState.version。
- `PlanEvaluation.plan_version`（设计 808-816）与
  `AdmissionInterpretation.plan_version`（设计 1005-1014）同名但语义不同：前者是
  “评价所基于的版本”，后者是“被解读的当前版本”。当前没有区分。

**最小修复**

1. **拆名字，不拆计数器（除非真加字段）**：
   - `stateVersion`：`planningState.version`，CAS/guard/snapshot 用；明确它会在
     review/偏好/候选生成时变化，不是内容版本。
   - `planContentDigest`：`hash(workingPlanState/orderedPlanState 内容)`；新增字段
     或在服务内计算。缓存/新鲜度用它，不再用 `stateVersion`。
   - `evaluatedStateVersion`：`ReviewStateDTO.sourceVersion`（review 计算时的
     stateVersion）；`PlanEvaluation.plan_version` 用它。
   - `interpretedStateVersion`：工具输入 `planVersion` / `AdmissionInterpretation.plan_version`。
2. `evaluationVersion = hash(evaluatedStateVersion, planContentDigest,
   candidateSourceVersion, dataVersion, objectiveModelVersion)`；freshness 用
   `evaluatedStateVersion + planContentDigest + staleFlags.review` 判定，不只看
   当前 stateVersion。
3. 统一一个 `InterpretationCacheKey`（建议 `stateVersion + planContentDigest +
   candidateSourceVersion + dataVersion + objectiveModelVersion + admissionMode`）；
   如果 review drivers 参与输出，再加 `evaluatedStateVersion`。删除其余三种写法。
4. 修正权威表/设计/计划里“planVersion 只随方案变化”“不是 workspace.version”的
   表述；要么承认同源，要么定义 `planContentDigest` 并迁移。
5. 明确 `dataVersion` 的来源：当前 `DataFreshnessStateDTO.dataVersion` 被写成
   `candidatePoolState.sourceVersion` 的字符串（`PlanningStateService:7465-7466`），
   与 `candidateSourceVersion` 是同一信号；不要把它当独立的新鲜度信号。

### B3. J1a 的 `stale` 恒 true，`pendingStatus` 永远到不了 `applying`

**证据**

- 设计 248：“`stale` 是独立布尔（`staleFlags` 非空）”。`StaleFlagsDTO` 是
  `PlanningStateDTO` 的非空字段（默认 `new StaleFlagsDTO()`，所有布尔默认 false，
  only reasonCode/message/affectedReviewCodes nullable）。因此“非空”恒 true。
- 设计 357-359：`pendingStatus` 来自当前 pending，用于区分 `prepared` 与
  `applying`。代码：
  - `ConversationSnapshotService.fillActiveProposal:142-146` 只接受
    `status == "active"`，`applying` 直接被丢掉；
  - `PendingConfirmationSharedService.getCurrent:14-21` 是
    `eq(tenantId, chatSessionId).last("limit 1")`，**没有 status 过滤/排序**；
    多条 pending 时可能取到 applied/cancelled 的旧行，真正的 active 反而看不到。
- 设计 246：`hasPlan = working/ordered 条目数 > 0`。现有 helper
  `currentOrderedOrDraftUnitCount`（11684-11690）同时看 ordered units 和 working
  units；只看 items 会在 unit-only working plan 上误判 false。
- `admissionMode` 在 `ConversationTurnSnapshotDTO:13` 已有；计划 J1a 又把
  `admissionMode` 放进 `journey` 块（计划 171-173），同一快照两个同义字段。
- `hasProfile` 需要“科类/批次”，`StudentPlanningSummaryDTO` 只有
  `subjects/strengthSubjects`（1-16），没有 subjectType；必须明确用
  `loadScoreDetail` 还是放宽条件。
- `taskIntent` 没有来源：`TurnOutput` 无此字段；计划 J1a-T2（190-192）却要测
  verify/review/interpret/adjust。必须先定义“从 responseType/tool calls/
  conversationAction 的哪个值派生”的映射表。
- `blocked_actions` 的 “stale working plan item” 需要 working plan IDs 与
  effective candidate pool 求差（`UserGoalProposalBuilder:225/263-275` 的
  `add_units_stale_working_plan_item`）；journey 块只有 `staleFlags`/`hasPlan`/
  counts，没有池成员关系。
- `StatePatch._validate_change_paths` 的 allowed 仍不含 `journey`
  （`contracts.py:560-574`）；计划 J1a-T1 的 checklist 只写
  `diff_snapshots`，没写这个白名单。

**最小修复**

1. `stale = any(candidatePool, recommendationOverlay, initialRecommendation,
   orderedPlan, planAdjustment, review) || reasonCode/message non-empty`。
2. `pendingStatus`：改 `getCurrent` 为按 status ∈ {active, applying} + revision
   倒序取最新；或新增 `getActiveOrApplying`。`fillActiveProposal` 不再只认
   `active`，`activeProposal` 仍只暴露 active（避免 applying 被当待确认），
   journey 的 `pendingStatus` 单独暴露 applying。
3. `hasPlan` 用 ordered items/units ∪ working items/units 非空；
   `planEntryCount` 按 admissionMode 明确 items 还是 units。
4. `journey` 不再重复 `admissionMode`；用顶层字段，或把顶层字段标为兼容别名。
5. `hasProfile` 明确实现：`loadScoreDetail` 的 province/examYear/batch/subjectType
   + score/rank；或正式放宽为“省份+年份+批次+成绩/位次”。
6. 定义 `taskIntent` 映射：`response_type=fact`→verify、
   `response_type=review`→review、`tool in {planning.interpret_admission}`→interpret、
   解读后用户明确改→adjust；其他→state_phase。写进 J1a-T2 测试。
7. `blocked_actions`：要么在 journey 块加 Java 计算的 `stalePlanItemCount`，要么
   把这一条降级为“agent 只提示，不保证列出”。
8. J1a-T1 Files/checklist 明确 `contracts.py::StatePatch`。

### B4. `$ref` 是不存在的前提；实际是 `poolRef` 拆分池

**证据**

- 设计 1103-1105：“实测 `planningState` 里 `workingPlanState` 可能只是
  `{"$ref": ...}`，`orderedPlanState.units[].majorItems` 也是 JSON 引用；必须用
  既有状态解析器/`orderedPlanState` 展开”。计划 32/105 同样要求“`$ref` 解析复用”。
- 全仓 Java 没有 `$ref` 处理；`grep '"$ref"'` 只命中 agent 的 JSON Schema。
- 实际机制：
  - `PlanningStateDTO.candidatePoolRef` + `serializePlanningStateRowValue`
    （`PlanningStateService:8381-8430`）把候选池拆成瘦池+`candidatePoolRef{len,md5}`；
  - `loadPlanningStateReadOnly`（5861-5873）已经调用
    `backfillCandidatePoolFromSplitRow`（5919-5955）回填 items；
  - `workingPlanState`/`orderedPlanState.units[].majorItems` 是普通内联字段，不是
    `$ref`。
- 权威表 25 又把 `$ref` 写成“方案状态存储的重复/歧义”，把一个不存在的机制
  写进了权威表。

**为什么阻塞**

J2b-T1 的 Files 明确要求“只读加载/`$ref` 解析复用”。执行侧会：
1. 找不到“既有解析器”；2. 自己写一个 `$ref` 展开器（throwaway + 可能误处理
`candidatePoolRef`）；3. 或者把 `candidatePoolRef` 当 `$ref`，读不到 items。

**最小修复**

- 删除设计 1103-1105、计划 32/105、权威表 25 的 `$ref` 表述。
- 改为：“`planningState` 可能因候选池拆分而只有瘦池 + `candidatePoolRef`；
  `loadPlanningStateReadOnly` 已回填；解读服务直接用回填后的
  `candidatePoolState.items`。`workingPlanState`/`majorItems` 是内联字段，无
  `$ref`。”
- 如果真实库确有 `$ref`，先给出一个可复现的会话号/字段样例，再单独设计解析器；
  不要把它写进当前契约。

### B5. 权威表的若干“合并/删除”是错的或不安全的

**(a) `category → layer` 错误**

- `category` 的值是 `structure_risk`/`ordering_risk`/`item_risk`/
  `major_group_risk`/`policy_notice`（`ReviewRuleRegistry:53-127`），不是
  hard/structure/soft。
- `item_risk` 同时包含 `admission_limit`（block，硬资格）与 `high_tuition`
  （action/notice，软成本）；`major_group_risk` 的 `group_inner_safety_guard`
  是 block。直接映射会丢“硬/软”维度。
- 修复：probe 表按 code 逐条指定 layer；`category` 降为 UI 分组/旧字段。

**(b) `ReviewSummaryDTO.riskCount/warnCount → action/notice` 错误**

- `recalculateReviewSummary`（12373-12411）里 `warnCount/riskCount` 按
  `ReviewCheckDTO.level` 统计，**包含 passed=true 的 check**（例如
  `reviewSafetyGuard` 缺生源省时 level=warn、passed 仍 true，10824-10830）；
  `block/action/notice/info` 只统计未通过。
- `risk` 的语义更接近 `block`（safety_guard/admission_limit/count_validation），
  不是 `action/notice`。
- 这些计数还驱动 `PlanningWorkflowStatusBuilder.applyReviewStatus:102-134`
  （riskCount→has_risk、warnCount→has_warning）与前端 `ProposalCard:413-418`、
  `WorkspacePanel:4961-4962`。直接映射会改变“审查通过/有风险”的 UI 状态。
- 修复：把旧计数标 legacy；新增 summary 字段只从 findings 派生；同时改
  `PlanningWorkflowStatusBuilder` + 前端；golden 对照通过后再删旧字段。

**(c) `RepairProposalTaxonomy` 整体删除不安全**

- `RepairProposalTaxonomy` 不只有 review 修复策略，还有
  `Status`（ready/preview_only/blocked/info/empty）、`ProposalSource`
  （review_check/user_goal）、`ActionType`（fill/add/remove/replace/reorder/
  adjust）、`CompensationActionType`、strategy aliases、strategy→actionType
  映射（23-288）。这些是**修复提案执行/应用协议**，`RepairProposalApplyPolicy`/
  `RepairProposalStateBuilder`/`RepairDryRunSimulator` 都在用。
- 权威表说“审查修复策略只在 probe/finding 里定义，不再单独一套 taxonomy”，
  但没给 `EvaluationFinding` 承载 status/source/actionType 的字段；直接删会让
  apply/dry-run 无法判断“可应用/只预览/阻断”。
- 修复：只把 `Strategy` 里的 review 语义迁到 probe/finding；`Status`/
  `ProposalSource`/`ActionType`/`CompensationActionType` 保留到 J5.5 执行协议
  被 `PlanCommand` 完整替代；顺序上先拆 simulator，后删 taxonomy。

**(d) `OrderedUnitDTO.admissionRatio` 不能“前端/模型不再依赖”后直接删**

- 生产端两条路径给出不同语义：`unit.setAdmissionRatio(representative.getAdmissionRatio())`
  （`PlanningStateService:4806`，major 级）与
  `unit.setAdmissionRatio(candidate.getSchoolEnrollRatio())`（12757，校级）。
- 消费者：
  - `MajorGroupUnitQuality.admissionRatio`（3617）用于 unit 排序；
  - `reviewProbabilityInversion`（10889-10890）；
  - `reviewProbabilityGap`（10957-10958）；
  - `PlanningExcelExportBuilder` fallback（153）。
- 删除/改读 `schoolEnrollRatio` 会改变 group 模式的倒挂/断层结论和排序。必须
  先给 unit 增加显式 `schoolEnrollRatio`/`representativeMajorRatio`，迁移上述
  消费者，并跑 golden 对照；旧字段在持久化计划里仍存在，删除还需读兼容。

**(e) `PlanGoalTypeValue` 整体映射到 PlanCommand 不安全**

- 10 个值里只有 `only_keep_scope`/`must_include_scope`/`exclude_scope`/
  `tuition_budget_scope` 是约束写；`query_state`/`clarify` 是只读/澄清，
  `prefer_scope` 是软偏好，`rebalance_structure`/`reduce_risk`/
  `mixed_adjustment` 是复合优化目标，不是单条 `PlanCommand`。
- 该枚举仍被 legacy `app/service.py:2068`（`PlanGoal`）使用；计划不包含删除
  legacy 模块的任务。
- 修复：只映射 mutation 子集；`query/clarify/prefer/...` 映射到
  `IntentFrame.goal_family` 或明确保留在 legacy 模块；写清“新 codex 路径不读
  `app/tools/plan_orchestration_models.py`，但 legacy `app/service.py` 仍读”。

**(f) `must_include_scope` 不是“只做已有条目覆盖”**

- `UserGoalProposalBuilder.buildMustIncludeProposal`（1705-1730）在方案已有
  匹配时 no-op；没有匹配时从候选补入；满方案时最多替换 1 组。权威表 28 的
  “只做‘方案已有条目’的覆盖”会让实现侧删掉“补入/替换 1 组”这条路径。
- 修复：写成“must-have 覆盖：已有→no-op；未满→补入；满→最多替换 1 组；
  未实现 REPLACE 时如实说明”。

**(g) 持久化 DTO 字段删除缺少读兼容**

- `ReviewStateDTO`/`ReviewCheckDTO`/`ReviewSummaryDTO` 是
  `PlanningStateDTO.reviewState` 的一部分，整份 JSON 持久化在
  `chatSessionExtraData.planningState.dataValue`（`PlanningStateDTO:30`）；
  老会话里有旧字段。直接删字段（level/category/supportedFixStrategies/
  compensationPreview）会让老会话反序列化后丢数据，或让新代码读到 null。
- `OrderedUnitDTO.admissionRatio` 同样持久化在 ordered/working plan 里。
- 权威表“删除门槛=golden 会话+一个发布周期”没有覆盖“历史持久化行”。
- 修复：删除前加版本化读适配器（旧字段→新字段），或保留字段一个发布周期并
  只停写；没有 DB migration 的本批不应删除持久化字段。

### B6. 评价/动作契约仍不可编译，且存在两套“同一结论”的表示

**证据**

- 设计 `PlanEvaluation`（808-816）字段：`plan_version, objective_model_version,
  candidate_source_version, structure, findings, hard_feasible, objective_digest`。
  计划 `PlanEvaluationDTO`（59-60）缺 `candidateSourceVersion`；`EvaluationFindingDTO`
  缺 `source`。
- 计划新增 `StructureVectorDTO.java`（55），但没有给字段；设计 `StructureVector`
  的字段（696-706）有 10 个，且 `target_count`/`coverage`/`safety_floor` 语义
  未定。
- Java 侧没有 `ObjectiveDelta`/`PlanCommand`/`ConstraintPatch` DTO；计划
  `EvaluationFindingDTO` 却要求 `objectiveDelta`/`suggestedCommand` 字段。
- `ObjectiveDelta.add_targets: list[EntryRef]`（784-791）用 `EntryRef` 表示
  待加入目标；`EntryRef.position: int` 与 `path_tier` 是必填（1018-1026），
  待加入目标没有 position/pathTier。应先定义 `TargetRef`/`ResolvedTargetRef`，
  或把 add targets 的 position 设为可空并写清含义。
- `EvaluationFinding` 同时有 `objective_delta` 与 `suggested_command`（785-786），
  没有规定哪个权威、是否要求 `suggested_command == compile(objective_delta)`。
  两个字段可以给出不同修复，正是“两套解释”。
- `hardFeasible = 所有 layer=hard finding passed=true`（设计 822-827）；若
  review 没跑/没有 hard probe，findings 为空，hardFeasible **vacuous true**。
  必须加 `probes_run`/`evaluation_status` 或要求 `ReviewState.status=completed`
  且 checks 非空，否则“没审=硬可行”。
- `metric: str` 写“必须是 StructureVector/ObjectiveModel 的枚举键”（799），
  但没有枚举定义；`threshold: dict | None` 没有 schema。两个实现可以各写一套。
- 未定义类型：`TargetRef`（525）、`ScopeSpec`（526）、`RequirementSpec`（727）、
  `PriorityRule`（728）、`MutationBudget`（741）、`PostconditionReport`（684）、
  `ReviewState`（686）、`ObjectiveModel`。只有 `ConstraintPatch`（723-730）定义了。
- `ConstraintPatch` 声称与 `ProposalRequest` 的字段“一一对应”（设计 744-746），
  但 `tier_quota: dict[str,int]` 与 `ProposalTierQuota`（type/updateMode/三个
  count/三个 range/三个 weight，`contracts.py:282-293`）不是一一对应；
  `tuition_range: tuple` 与 `ProposalContext.min/max` 也不是。需要转换表。
- `PlanCommand` 同时有 `intent: IntentFrame` 与 `resolved_targets/
  compiled_constraints`（733-741）；权威表 59 说“PlanCommand 只放
  resolved/compiled”，与 dataclass 不一致。必须规定 solver 只读后两者，
  `intent` 仅 provenance，或删除 `intent`。
- `IntentFrame.lifecycle/risk_posture/priority_order` 在 `ProposalRequest` 没有
  对应字段（见 1.2 行 60）；`ProposalRequest` 只有 `persistTargetCount`/
  `priorityRules`。不能声称“IntentFrame 只是派生视图”。
- 已有 `CanonicalPlanningObjectiveSetDTO`（`schemaVersion/objectiveDigest/
  tierAllocation*/orderingConstraints`）与 `PlanSolverResultDTO`
  （`objectiveResults/diagnostics/solverVersion/inputDigest/resolvedTierCounts`）
  就是现有的 canonical objective + 求解结果；新的 `ObjectiveModel`/
  `PlanEvaluation`/`PlanReceipt` 与它们的关系完全没写。若不建立映射，J5 会
  出现“canonical objective 一套、ObjectiveModel 一套、review checks 一套”
  的三重定义，恰好违背本次目标。

**最小修复**

1. 在 J2a 之前先做一个 `PlanEvaluationDTO` 的**最小稳定子集**：`planVersion,
   evaluatedStateVersion, candidateSourceVersion, findings`；`structure` 在
   MVP 明确为 `null` 或移出 J2a。或者把 J5.0 的 `StructureVector`/
   `EvaluationFinding` 定义前移（见“实施顺序”）。
2. 决定 `objective_delta` 与 `suggested_command` 的唯一权威：建议
   `objective_delta` 是唯一事实，`suggested_command = ActionCompiler.compile(delta)`
   是派生/缓存；构造期校验一致，不一致拒绝。
3. 定义 `TargetRef`（无 position/pathTier）与 `ResolvedTargetRef`（有解析后的
   position）；`add_targets` 用前者，`remove/reorder_targets` 用后者。
4. 补 `ObjectiveModel` 的 schema 与版本，并明确它是
   `CanonicalPlanningObjectiveSetDTO` 的超集/重命名，还是替换；`objectiveDigest`
   与 `canonicalObjectiveDigest` 的关系写死。
5. 给 `metric` 一个封闭枚举（如 `tier_counts`, `unit_tier_counts`,
   `safety_floor.local_protect`, `count.total`, `count.target`,
   `ratio.inversion_pairs`, `tuition.over_budget` …），给 `threshold` 一个
   per-metric schema。
6. 补齐 Java DTO 文件清单（`ObjectiveDeltaDTO`, `PlanCommandDTO`,
   `ConstraintPatchDTO`, `TargetRefDTO`, `StructureVectorDTO` 字段），或在
   MVP 明确 `Map<String,Object>` 并禁止下游按结构读。
7. `hardFeasible` 增加 `probes_run > 0 && review.status == completed` 前提；
   否则 `hardFeasible=false` + caveat。

### B7. 证据与只读边界仍自相矛盾；join 源未定

**证据**

- 设计 1118：“返回 `AdmissionInterpretation` + `evidenceRefs`（Java 计算证据
  已签发）”。设计 894-905 与计划 114-116 明确“MVP 不新签 computed、
  `sourceLevel=computed` 当前 ledger 不支持”。权威表 2.1 还要删这条验收。
- 响应载体未定义：`PlanningStateController` 现有风格是 `BaseResponse<T>`
  （只有 data/code/msg）；agent 的 `_preserve_envelope` 只认顶层 `evidence`
  （`tools_readonly.py:893-920`）。若证据放在 `data` 里，`evidenceRefs` 会是空。
- `resolveEffectiveCandidates(tenantId, chatSessionId, state, true)`
  （`PlanningStateService:9515-9524`）在需要时会 `refreshRecommendationOverlay`，
  后者会写 `recommendationOverlayState`（`PlanningStateService:9453-9478`
  `persistRecommendationOverlay`）。
  解读服务若复用它，就不是只读。计划 J2b 只写“只读加载”，没有禁止这个调用。
- join 源未定：raw `candidatePoolState.items`、effective（overlay + 硬约束/
  学费过滤后的 `resolveEffectiveCandidates`）、agent artifacts 三套
  （设计 §8.2 只写“候选池”）。如果 join 用 effective，可能触发写/网络；如果
  用 raw，可能把已被硬约束排除的候选算进 majorRatio。必须二选一并写理由。
- 默认 `ReadonlyDomainTools` backend timeout 5s、超时整段重试一次
  （`tools_readonly.py:350,453-457`）；首次冷读 4–29MB 候选池可能超时。计划
  J2b-T1 只写 LRU，没有预热/单独超时/慢后端测试。

**最小修复**

1. 删除 §9.1 的“Java 计算证据已签发”，改为：“返回 `AdmissionInterpretation`
   + 顶层 `evidenceRefs`；MVP 只引用本次实际查到的上游证据（候选/历史/审查），
   没有就空数组；不签 computed。”
2. 定义响应载体：`ResponseDTO<AdmissionInterpretationRes>` 或给
   `AdmissionInterpretationRes` 一个 `evidence` 字段；agent 用
   `_preserve_envelope`/显式 lift，测试 `evidenceRefs` 非空（有上游证据时）。
3. J2b 明确禁止 `resolveEffectiveCandidates(..., true)`/`refreshRecommendationOverlay`；
   只读 `loadPlanningStateReadOnly` + `candidatePoolState.items`（或明确选择
   effective 的只读变体，并证明它不写）。
4. 明确 join 源，建议：
   - ratio 是上游候选事实，join **raw** `candidatePoolState.items`；
   - 若候选被硬约束/学费过滤掉，方案条目仍在，则 caveat 标“该条可能不在当前
     有效候选集合”，不要因此把 ratio 判 unknown；
   - 若以后要 join effective，先提供只读 `resolveEffectiveCandidatesReadOnly`。
5. 给 `planning.interpret_admission` 单独 backend timeout（例如 15–20s）或
   预热索引；测试慢响应 + 一次重试不重复冷读。

### B8. ID 表写错，unit 模式会指错行

见 §1.1。最小修复：

- `unitId = volunteerId 第一个 '_' 前段`（fallback 到 unit 主键/schoolName）；
  `legacyVolunteerPrefix`（前两段）只用于 legacy 匹配，不是 unitId。
- `volunteerId` 写成“`planSchoolDataId + '_' + majorIdentity`，majorIdentity
  依次取 `planMajorDataId`/`majorId`/`majorUnitCode`/`major_name`；可能有第三段；
  不得假设恒为 `planSchoolDataId_majorId`”。
- 在 `EntryRef`/`PlanReceipt`/证据里加 `idScheme`（或明确 `level` 已足够），
  否则权威表末尾“回执/证据标注 idScheme”没有载体。
- 增加一个 ID 对照测试：同一候选行按 `volunteerId`、`unitId`、`admissionUnitId`
  三种口径解析，断言不一致时拒绝跨套比较。

---

## 三、Majors（不阻塞“方向”，但必须在对应切片前定）

1. **J2a adapter 映射未定义**：`ReviewStateToPlanEvaluationAdapter` 要从
   `ReviewStateDTO.checks` 产出 `structure`/`hardFeasible`/`objectiveDigest`/
   `metric`/`threshold`；ReviewCheckDTO 没有这些字段。计划只说“MVP 适配”。
   必须给逐 check 映射表，或让 J2a 直接消费 checks（推荐后者）。
2. **J2a DTO 字段与设计不一致**：计划缺 `candidateSourceVersion`/`source`；
   `StructureVectorDTO` 无字段；`objectiveDelta/suggestedCommand` 无 Java 类型
   （见 B6）。
3. **J2a 的 tier 归一化**：`OrderedItemDTO.tier` 若出现 `冲1/稳2/保3`（历史九区间
   残留）当前会被判 `unknown`；需定义 `冲*→冲` 归一化，或在 J2a fixture 里覆盖。
   计划只测 50/70 边界，没有测非三档值。
4. **J2a 的 unit 模式 majorRatio 来源**：unit 模式应读
   `OrderedUnitDTO.majorItems[].admissionRatio`（`PlanningUnitMajorDTO`），不是
   再按 unitId join 候选池；计划只说“unit 模式用 OrderedUnitDTO”，没写
   majorItems。写清，否则 unit 模式 majorRatio 永远空。
5. **J2b 版本/stale 语义**：`planVersion` 是 stateVersion；无方案/版本不符/
   review 过期分别返回 `no_plan`/`stale_interpretation`/caveat 还是同一个
   `stale_interpretation`？review 过期时 drivers 是否输出？必须定。
6. **J2c 发射时机矛盾**：设计 §9.2.5 说“网关校验完 TurnOutput 后、
   `turn.completed` 之前发”（1130-1135）；计划 J2c-T1 说“`service.py` 拦截
   工具结果→有界摘要事件”（227）。若按计划在 tool notification 时发，整轮
   后续被判废/修复时卡片会留在无效回合。改为“工具结果只暂存，收尾时随
   `proposal.preview` 同一条已验证 result 发”；Files 加
   `server.py::_emit_turn_terminal`。
7. **J2c `dataCompletenessBand` 阈值**：`dataCompleteness` 是 float，band 的
   “完整/有缺口”阈值没定义。建议 `>=1.0 complete else gap`，或 `>=0.9`；
   写死一个，测试覆盖。
8. **J2c 冷加载**：`interpretation.preview` 是回合事件；刷新/重连后没有
   `lastProposal` 那样的兜底，卡会消失。设计应明确“卡是临时的，正文摘要
   仍在 assistant message”；若要冷加载，另立切片（不要偷塞 artifact）。
9. **J3 没有生产者**：`origin/actionType/scope/receipt` 在当前
   `ConversationActionResult`（59-78）和 `_action_result_payload`（1083-1105）
   里都没有来源；`operationId`/`postconditionReport` 在
   `_execute_claimed_command` 里被丢掉。计划 J3 只改 `server.py`，不够。
   要么 J3 等 J5.4 的 `PlanReceipt`，要么明确它是 display-only adapter，并从
   `PendingPlanningCommandRes`（operationId/commandType/postconditionReport）+
   pending kind 取值；禁止反向定义 `PlanReceipt`。
10. **J4a 持久化 owner 未定**：`requirements/priorityRules` 已持久化；
    `selectionTargetCount` 无条件持久化（`PlanningStateService:1095-1105`）；
    `targetScopes/negativeScopes` 同时进 constraintState（`constraintUpdate`）
    和 userprofile（agent `_confirmed_profile_scopes`）；`tuitionRange` 走
    `ChatSessionBizService.updateTuitionRange`，而 `applyUserGoalTargetToPlanningState`
    不写它。J4a 前必须定：谁是唯一 owner、其余是投影还是兼容、stale 怎么标、
    `persist=once|session` 控制哪几个字段。
11. **`persistTargetCount` 语义/命名**：契约描述是“true=按新总数补齐、
    false=保持当前总数”（`contracts.py:344-349`），Java 用它决定是否把
    `targetCount` 写进 `candidatePoolState.requiredCount`（1104-1105）并作为
    postcondition 的持久目标（`UnifiedPlanPostconditionValidator:66-91`）。
    这不是 lifecycle；不要把它改名成 `persist=once|session` 后复用。
12. **REPLACE 的模型词汇缺失**：`ProposalRequest.goalType` 7 类里没有
    REPLACE/`addPolicy`；`add_units` 又禁止混 count/scope。J4a 要落 REPLACE，
    必须先加模型可表达的字段（如 `addPolicy=expand|replace` 或
    `replace_units` goalType），并定义与 `ExactTargets`/`targetCount` 的组合。
13. **`PlanReceipt` 的字段生产者未定义**：`added/removed/kept_count/
    structure_before/after/postcondition/tradeoffs/reason_codes` 目前没有
    Java 产出；`PendingPlanningCommandRes` 只有 add_units 的
    addedVolunteerIds/addedUnitIds/removedVolunteerCount/targetCountBefore/After
    和 postconditionReport；其他命令没有。J5.4 前不能把 `PlanReceipt` 说成
    当前权威回执（见 B5(d) 的反向定义风险）。
14. **`ReviewStateDTO` 的 Java/前端消费者未列入迁移**：
    `PlanningWorkflowStatusBuilder:102-134`（riskCount/warnCount→has_risk/
    has_warning）、`WorkspacePanel:762-768`（reviewState.checks/
    compensationPreview）、`ProposalCard:413-418`（reviewState.summary）。
    权威表 2.2 只写 Java DTO 合并，没有这些消费者与迁移顺序。
15. **`ReviewSummaryDTO` 的重复别名**：`totalRuleCount/passedRuleCount/
    warnRuleCount/riskRuleCount` 与 `total/passedCount/warnCount/riskCount`
    是同一语义两套名字（`ReviewSummaryDTO:7-14`）；前端用
    `passedRuleCount ?? passedCount`（`WorkspacePanel:4961-4962`）。这是
    “现在就删（设计层）”应该列出的安全重复项，但权威表没列。
16. **`plan-final-review` 的 career 方向覆盖**：技能 step 3b 是后端没有的
    probe；J5 把技能改成纯叙述前，必须把它加进 `PlanEvaluator`（如
    `direction_coverage`，用 `preferences.careerTypes` + `StructureVector.coverage`），
    否则这条检查消失。另有 evidence/identity/跨线程等手工检查，需要一张
    “技能私有规则 → probe 或保留手工”的完整清单。
17. **review artifact 契约冲突**：`TurnOutput` 对 `responseType=review` 强制
    `artifactRefs`（`contracts.py:534-539`），但 `ArtifactStore` 只接受
    candidate/comparison（`artifact_store.py:80-81`），`ArtifactRef` 却声明
    `review` 类型（`contracts.py:156`）。J5 前人工审查仍会走 `responseType=review`；
    要么允许“review findings 可替代 artifact”，要么明确用 candidate artifact，
    不要发一个 store 不可能签发的 `review` artifact。
18. **`reviewState.sourceVersion` 与 `evaluationVersion` 的迁移顺序**：
    `ReviewStateDTO` 是持久化的；新增 `evaluationVersion`/`PlanEvaluation` 引用
    必须对旧行可空/可读。权威表“J5.2 新代码只读 evaluationVersion”需要先有
    backfill/读适配，否则老会话永远 stale。
19. **`dataVersion` 的独立性问题**：`DataFreshnessStateDTO.dataVersion` 当前由
    `candidatePoolState.sourceVersion` 生成（7465-7466），与
    `candidateSourceVersion` 同值；把它放进 evaluationVersion 是重复而非独立
    信号。若确实需要独立 freshness，应使用 `dataHash/latestDataHash/
    latestDataVersion` 并写清。
20. **`objectiveModelVersion` 与 `solverVersion`/`canonicalObjectiveDigest`
    的关系**：已有 canonical 元数据（`conversation_actions.py:267-272`、
    `RepairProposalApplyPolicy.validateCanonicalMetadata`）是 apply 的硬门槛；
    新 `objectiveModelVersion` 不能绕过它。J5 必须说明是替换还是并存，
    以及 apply 时校验哪一个。

## 四、Minors

1. 设计 255-258 有整段重复的“最终 `journeyPhase = taskIntent ?? statePhase`”，
   删一段。
2. 计划头部 `Spec: ...（v2）`、`Review: ...review.md` 过期；应指向设计 v4 与
   v1/v2/v3 三份 review + 本文。
3. `TOOL_KINDS` 在 `tools_readonly.py:99-135`，计划 J2b-T2 写在 `server.py` 的
   改动里（文件列表同时含 tools_readonly.py，执行侧能找到，但建议写准）。
4. `LandingScenario.scenario_id`/`generated_at` 的生成规则未定义。
5. `removeEntryRefs` 删除全部条目/重复 id/不存在 id 的返回未定义。
6. `interpretation.preview` 与 `assistant.completed`/`turn.completed` 的相对顺序
   已写“turn.completed 前”，但 reducer 的终态守卫对未知类型/卡片没有明确
   “终态后拒绝”；加测试。
7. `admissionMode` 的 canonical 值：设计用 `major|major_group|unknown`，Java
   `CandidatePoolStateDTO.volunteerModel` 用 `majorGroup`，agent
   `canonical_admission_mode` 做归一；J2a DTO/测试要统一，不要在校验处再出现
   第三种写法。
8. `PlanEvaluation.objective_model_version="review-adapter-v1"` 是手写常量；
   任何 review probe/severity 变化都要 bump，建议在 adapter 里由 probe 表版本
   生成，避免忘记。
9. `PlanAdmissionInterpretationService` 的 controller 返回
   `BaseResponse<AdmissionInterpretationRes>` 还是带 `evidence` 的
   `ResponseDTO`，计划没写；与 B7 一起定。
10. `PlanAdmissionInterpretationService` 的读只读性：`loadPlanningStateReadOnly`
    已经回填 split pool；不要再调用 `getPlanningWorkspaceState(tenantId, ...)`
    （它会 `touchDataFreshnessSchedule`）。
11. `PlanEvaluation.findings` 包含所有 probe（设计 818-821），J2a 解读的
    drivers/caveats 应只取 `passed=false/null`，否则会把“已通过”写成 caveat；
    明确过滤规则。
12. `ReviewCheckDTO.passed=true` + `level=warn`（safety_guard 缺省份、
    count_validation 缺 requiredCount）在适配器里要映射成 `passed=null`，不能
    当 true；否则 hardFeasible 会 vacuous true。
13. `dataCompleteness` 的面客阈值、`diversity` 的面客措辞都未定义；J2c 前定。
14. `covereage` key 集合要与 `CoverageRequirementDTO`/`CoverageRequirementSupport`
    对齐；否则“同一组 keys”无法验收。
15. `PlanCommand.command_type` 的 `constrain` 与 Java
    `apply_constraint_and_regenerate` 不是 1:1：当前 Java 总是
    `regenerate_ordered_plan=true`（`conversation_actions.py:787-797`）。设计
    “constrain 后是否重排由后续 generate/reorder 决定”是未来行为；在 J5 之前
    必须保留复合执行适配，不能把 constrain 拆成“只改约束不重排”。

---

## 五、合并/删除安全矩阵

### 5.1 现在可以删（设计层/无消费者）

- `system.action` 事件、`SystemActionCard`、自动生成/重排叙事：全仓无引用
  （grep 证实），设计层删除安全。
- `review_read` 的声明/签发：只有 `ConversationSnapshotService:183-185` 签发，
  gateway 恒 `skill=None`；`CAPABILITIES` 无此能力。可以先删这一分支，并加
  一条测试“skill 含 review 也不签发 review_read”。
- MCP 工具参数里的 `chatSessionId/tenantId/sessionId/userId`：当前 schema/
  `_trusted_arguments` 已不接收；保持测试锁定。
- `plan.interpret_admission` 旧名：已改 `planning.interpret_admission`。
- `scenarioDepth`、`last_action`：不存在；无代码可删。
- “computed evidence 已签发”的验收口径：设计 §9.1 的残留句必须删（B7）。
- `ReviewSummaryDTO` 的重复别名（`totalRuleCount/...`）：语义安全，但要先改
  前端 `WorkspacePanel:4961-4962` 的 `??` 回退；可放到 J5.0 的小切片。

### 5.2 只能“加新字段 + 双写/适配”，不能现在删

- `ReviewStateDTO`/`ReviewCheckDTO`：持久化在 planningState JSON；且
  `RepairProposalStateBuilder`、`RepairProposalApplyPolicy`、
  `PlanningWorkflowStatusBuilder`、`WorkspacePanel`、`ProposalCard` 都在读。
  先新增 `PlanEvaluation`/`probeRegistry`/`evaluationVersion`，旧字段只停写不删；
  golden 对照 + 前端迁移后再删。
- `ReviewRuleRegistry`：修复元数据（fixability/strategies/evidenceSchema/
  postApplyValidationRule/targetModes）是修复链的输入；先建
  `EvaluationProbeRegistry`，把字段迁过去，再让 `RepairProposalStateBuilder`
  读 registry。
- `RepairProposalTaxonomy`：先拆 `RepairDryRunSimulator` 的评价/执行两部分，
  再把 Strategy 子集迁 probe；Status/ProposalSource/ActionType 留到 J5.5。
- `OrderedUnitDTO.admissionRatio`：先给 unit 增加显式字段并迁移
  `probability_inversion/gap`/`MajorGroupUnitQuality`，golden 对照后再废弃。
- `actualChanges`/`reviewState` 传输字段：等 Java 产出 `PlanReceipt`
  （operationId/postcondition/structure/tradeoffs/reasonCodes）后再改为投影；
  现在改会反向定义。
- `PlanGoalTypeValue`：保留给 legacy `app/service.py`；新 codex 路径只映射
  mutation 子集。
- `must_include_scope`：保留“补入/替换 1 组”语义；不要按“只覆盖已有”删。
- `tierCounts`/`unitTierCounts`：现有代码里是同一份 item 计数；不要合并成一个
  或拆成两个新语义，先定义“major 模式 item / group 模式 unit”，再迁移 review。
- `PlanningWorkflowStatusDTO`：`reviewStatus` 依赖 old risk/warn counts；先在
  J5.0 增加 severity 计数并迁移，再删旧计数。
- `ReviewState.compensationPreview`：`WorkspacePanel:763` 在用；J5 后由
  findings 生成前不要删。

### 5.3 错误/不安全的合并

见 B5：`category→layer`、`riskCount/warnCount→action/notice`、
`RepairProposalTaxonomy` 整体删除、`OrderedUnitDTO.admissionRatio` 直接删、
`PlanGoalTypeValue` 整体映射、`must_include_scope` 只覆盖已有、
`ReviewStateDTO` 长期删除但无读兼容。

### 5.4 适配器反向定义的风险

权威表原则 3 说“不允许适配器反向定义语义”，但有三处实际会发生：

1. `PlanReceipt` 若从 `actualChanges` 反向拼装，旧传输字段就成了新回执的
   定义源；
2. `PlanEvaluation` MVP 若从 `ReviewStateDTO.checks` 反向拼 `structure`，
   review check 的计算口径就成了 PlanEvaluation 的定义源；
3. `FixProposalDTO` 若继续从 checks 的 `scopeKind/defaultFixStrategy` 反推
   `EvaluationFinding`，旧的修复策略表就成了 probe 的定义源。

修复：为每对“旧→新”写一个单向 mapping table（旧字段只读、新字段只写），
并规定新逻辑不得读取旧字段的独立语义；在 golden 对照报告里列差异。

---

## 六、实施顺序与“throwaway code”

### 6.1 推荐顺序

**Phase 0：设计/契约修订（不改代码）**

1. 修 B2：版本/新鲜度模型（stateVersion vs planContentDigest vs
   evaluatedStateVersion；统一缓存键；review sourceVersion 参与 freshness）。
2. 修 B1：定义 `EvaluationContext`（probe 输入）+ 完整 14-probe 表 +
   layer/severity 合法组合 + `StructureVector` key 集合。
3. 修 B3/B4：J1a 事实（stale/pending/hasPlan/hasProfile/admissionMode）、
   `$ref` 删除、`JourneyAction`/`taskIntent` 定义。
4. 修 B5：安全矩阵、错误合并、持久化读兼容。
5. 修 B6/B7/B8：PlanEvaluation/EvaluationFinding/ObjectiveDelta/PlanCommand/
   TargetRef/ObjectiveModel 与 Java DTO 清单、证据/只读/join、ID 表。
6. 修计划头部/任务文件清单（StatePatch、TOOL_LABELS/CONTRACTS、J2c 发射点、
   J3 来源）。

**Phase 1：J2a（纯函数 + 13 行真值表）**

- 建议 **J2a 不消费 `PlanEvaluation`**：直接消费 `ReviewStateDTO.checks`
  （或一个只含 code/passed/summary/affected 的 `EvaluationFindingView`）；
  `PlanEvaluation`/`StructureVector`/adapter 移到 J5.0。这样 J2a 不被未定义
  的 schema 阻塞，也不会产生 throwaway DTO。
- 保留 13 行真值表、unit/major 各一组、remove-only 反事实；
  补 `冲1/稳2` 归一化与 unit `majorItems` 来源测试。
- `pathTier` 只读 `OrderedItemDTO/OrderedUnitDTO.tier`，不从 ratio 反推。

**Phase 2：J2b（Java inner + MCP + 证据）**

- 只读 `loadPlanningStateReadOnly`；禁止 `resolveEffectiveCandidates(..., true)`；
  join 源写死；证据只引用上游；单独 timeout；缓存键统一。
- 真栈文本先通，再做卡。

**Phase 3：J1a/J1b/J1c**

- J1a：修 Java snapshot 的 stale/pending/hasPlan/hasProfile + agent
  `contracts.py` 三处（含 StatePatch）。
- J1b：先定义 `JourneyAction` 枚举、`taskIntent` 映射、40 条 fixture。
- J1c：硬不变量；`pendingStatus` 修好后再做 applying 拒绝。

**Phase 4：J2c**

- 事件在已验证 turn result 收尾发；payload band 阈值；legacy 映射；卡冷加载
  取舍写明。

**Phase 5：J4a → J4b**

- 先定 scope/学费/requiredCount 的唯一 owner 与 `persist` 语义，再加 REPLACE
  的模型词汇。

**Phase 6：J5.0 → J5.6**

- J5.0 应该**前移到 J2a 之前或与 J2a 并行**（只做定义 + 现有输出采样 + golden），
  否则 J2a 会被迫发明 `StructureVector`/`PlanEvaluation` 的临时形状。
- J5.0 先建立 `CanonicalPlanningObjectiveSetDTO`/`PlanSolverResultDTO` 与新
  `ObjectiveModel`/`PlanEvaluation` 的映射，避免第三套目标模型。
- J5.2 probe registry + evaluator：先 shadow 对照（旧 checks vs 新 findings），
  差异报告后再切解读/审查的 drivers。
- J5.4 PlanReceipt：先让 Java 产出 operationId/postcondition/structure/
  tradeoffs/reasonCodes，再把 `actualChanges/reviewState` 降为投影。
- J5.5 审查→动作：先用现有 `FixProposalApplyReq`/frozen command 跑通一个
  finding（如 `safety_guard`），再推广；`objective_delta` 为唯一权威，
  `suggested_command` 派生校验。
- J5.6 清理：golden 对照 + 前端迁移 + 持久化读适配后再删旧 DTO/字段。
- J3：若仍要在 J5.4 前做，明确“display-only adapter，不是 PlanReceipt 的定义源”；
  否则后移到 J5.4。

### 6.2 会产生 throwaway code 的任务

- **J2a-T1 的 `PlanEvaluationDTO`/`EvaluationFindingDTO`/`StructureVectorDTO`/
  adapter**：在 `StructureVector`/`ObjectiveModel`/probe registry 未定义前创建，
  J5.0 必然重定义。建议移出 J2a 或先做 J5.0。
- **J2a-T2 的“消费 PlanEvaluation.findings”**：如果 J2a 只需要 drivers/caveats，
  直接消费 checks 更稳定。
- **J3 的 `origin/actionType/scope/receipt`**：没有 producer 时只能从旧字段拼，
  会在 J5.4 再拆一次。
- **J1a 的 `reviewSourceVersion`**：如果 B2 改成 `evaluatedStateVersion` +
  `planContentDigest`，这个字段要重命名/迁移；现在先别在 journey 里固化一个
  模糊名字。
- **J2b 的 `$ref` 解析器**：不存在，不要写。

### 6.3 现在删 vs 以后删

**现在删（无消费者/设计层）**：`system.action`/`SystemActionCard`/自动叙事；
`review_read` 签发分支；MCP 身份参数；旧工具名；`scenarioDepth`/`last_action`；
“computed evidence 已签发”文案。

**以后删（有消费者/持久化）**：`ReviewStateDTO`/`ReviewCheckDTO` 字段、
`ReviewRuleRegistry` 元数据、`RepairProposalTaxonomy`、
`OrderedUnitDTO.admissionRatio`、`actualChanges/reviewState` 传输字段、
`PlanGoalTypeValue` legacy、`ReviewSummaryDTO` 旧计数、
`PlanningWorkflowStatusDTO` risk/warn 派生、`ReviewState.compensationPreview`。

---

## 七、具体编辑清单

### 7.1 权威表（`docs/superpowers/specs/2026-10-18-plan-semantic-authority-map.md`）

1. 在每个 owner 后加 **current / target** 标记：`PlanEvaluation`、
   `StructureVector`、`ObjectiveModel`、`PlanReceipt`、`EvaluationProbeRegistry`、
   `CandidateSnapshot` 目前都不存在，不能与 `planningStage`/`ReviewStateDTO`
   混在同一列。
2. 方案状态存储：删 `$ref`；加 `recommendationOverlayState`、`candidateViewState`。
3. 对话位置：加 `taskIntent` 的生产者映射；删重复的 `admissionMode`。
4. 用户动作：把 `PlanGoalTypeValue` 拆成 mutation 子集 vs query/clarify/复合目标；
   把 `update_score_detail` 从 PlanCommand 拆出；注明 legacy 模块路径
   `app/tools/plan_orchestration_models.py`。
5. 加入语义：改 `must_include_scope` 为“已有→no-op；未满→补入；满→最多替换
   1 组”；加 `addPolicy` 模型词汇缺口。
6. 候选事实：写清 raw/effective/overlay/view；J2a join 源。
7. 档位：加 `derive_risk_tier`（`<50/<70`）vs Java（`<=50/<=70`）的重复定义；
   把 `OrderedUnitDTO.admissionRatio` 的内部消费者列出。
8. 分数字段：加 `futureDevelopmentScore` 与 `rankToScore` fallback。
9. 优化目标：把已有 `CanonicalPlanningObjectiveSetDTO`/`PlanSolverResultDTO`/
   `objectiveDigest`/`solverVersion` 纳入 owner 或明确映射；否则不许新造
   `ObjectiveModel`。
10. 方案评价：`PlanEvaluation` 标 target；补 Java DTO 字段清单。
11. 审查版本字段：改为 `evaluatedStateVersion`（review source，=当前
    stateVersion-1 的既有语义）与 `evaluationVersion`；删“sourceVersion 不进
    cache”的矛盾表述。
12. 方案变更回执：`PlanReceipt` 标 target；列当前 `ConversationActionResult`
    丢失的 operationId/postcondition；写明禁止从 actualChanges 反向拼装。
13. 修复预览：加 `EvaluationProbeRegistry` 需要承载的字段（fixability/
    strategies/evidenceSchema/postApplyValidationRule/targetModes/scopeKind/
    requiresConfirmation）。
14. 结构指标：补 `StructureVector` 的 key/口径：unknown tier、coverage keys、
    safety_floor keys、diversity、duplicates、target_count 指谁、
    tier_counts vs unit_tier_counts 的模式。
15. 覆盖 vs 数据完整度：加 `dataCompletenessBand` 阈值。
16. 顺序异常 vs 概率倒挂：注明现有 `probability_inversion/gap` 用
    `admissionRatio`，改 `schoolEnrollRatio` 是行为变更。
17. 保底指标：写 `safety_guard` 的 userScore>=580 短路/生源省/本省计数与
    `safety_floor` 的 key。
18. 版本：重写为“一个 stateVersion + 可选 planContentDigest”；删“两个版本分开”
   和“不是 workspace.version”。
19. 版本守卫：改为“同一 stateVersion，guard 与 snapshotVersion 比；不得新增
    第二计数器”。
20. 动作基准版本：写 `base_plan_version = prepare 时的 stateVersion`。
21. 评价模型版本：加 `probeRegistryVersion`/`objectiveCompilerVersion`/
    `weightsVersion` 的实际字段/来源；与 `solverVersion` 的关系。
22. 目标/约束归属：规定 solver 只读 resolved/compiled，`intent` 仅 provenance；
    或删 `intent`。
23. 模型契约 vs 归一化视图：把 `lifecycle/risk_posture/priority_order` 标
    “J6 前不可从 ProposalRequest 派生/为 null”；不要声称完全派生。
24. 目标数量：按代码重写（plan summary `targetCount = requiredCount`；
    `total` 在 group 模式是 unit 数；`targetUnitCount` 是 requiredCount 别名；
    `selectionTargetCount` 在 HardPlanningObjectivesDTO）。
25. 冲稳保配额：改“review 读 expectedTierCount（requiredTierCounts 缩放）”，
    补 solver `resolvedTierCounts`/`historicalTierAnchor`。
26. 意向生命周期：把 `persist=once|session` 标 target；列出 `persistTargetCount`
    的真实语义；列 requirements/targetScopes/negativeScopes/tuitionRange 的
    当前落点。
27. ID 表：按 §1.1 重写；加 `idScheme` 载体。
28. 2.1b：删 `category→layer`；改 risk/warn 计数映射；补 summary 重复别名；
    `affectedUnitIds/VolunteerIds` 映射要保留 level/父子关系。
29. 2.2：把 `RepairProposalTaxonomy` 拆成 Strategy（迁 probe）与
    Status/ProposalSource/ActionType（保留到 J5.5）；`OrderedUnitDTO.admissionRatio`
    标“迁移完成前不可删”；`actualChanges/reviewState` 标“有 producer 后才投影”。
30. 2.3：按代码重写 targetCount/total/targetUnitCount；`futureDevelopmentScore`。
31. 加一节“持久化字段删除规则”：先读兼容/双写，再删；没有 DB migration 的本批
    不删持久化字段。

### 7.2 设计（`docs/superpowers/specs/2026-10-18-journey-control-and-admission-interpretation-design.md`）

1. §3.4：`stale` 改为“任一 flag true 或 reasonCode/message 非空”；`hasPlan`
   同时看 items/units；`hasProfile` 用 loadScoreDetail 或放宽；补 `taskIntent`
   映射表。
2. §4.4：删 journey 里的 `admissionMode` 重复；`pendingStatus` 写 active/applying
   状态值与来源；`planVersion` 改为 stateVersion 语义；补 `JourneyAction`/
   `available_actions` 派生规则。
3. §7.6：补 `StructureVector` 的 key/口径；`target_count` 指谁；unknown tier；
   `coverage`/`safety_floor` key；`tier_counts` vs `unit_tier_counts` 模式。
4. §7.7：定义 `TargetRef`/`ResolvedTargetRef`/`ScopeSpec`/`RequirementSpec`/
   `PriorityRule`/`MutationBudget`；`ConstraintPatch` 与 ProposalRequest 的
   转换表；`PlanCommand.intent` 的 provenance 规则；REPLACE 的模型词汇。
5. §7.8：完整 14-probe 表；layer/severity 合法组合按实际 check 修正
   （group_inner_safety_guard=hard/block；count_validation 的数据不足单列）；
   `hardFeasible` 加 probes_run/status 前提；`evaluationVersion` 用
   evaluatedStateVersion + planContentDigest；`PlanEvaluation.plan_version`
   与 `AdmissionInterpretation.plan_version` 分开命名。
6. §8.2：join 源写死（建议 raw pool + caveat）；unit 模式 majorRatio 来自
   `majorItems`；`$ref` 删除，改 poolRef；只读禁止 overlay refresh。
7. §8.3/8.4：`dataCompletenessBand` 阈值；`EntryRef` 与 `TargetRef` 的区分；
   `pathTier` 的九区间归一化（冲1/稳2→冲/稳）。
8. §9.1：删“Java 计算证据已签发”；定义响应载体；统一缓存键；单工具 timeout；
   join 源；review 过期时的行为。
9. §9.2：`interpretation.preview` 在已验证 turn result 收尾发；legacy 映射；
   payload band/threshold；冷加载取舍；16KB 预截断。
10. §12.2/12.3：加 unit 模式 majorItems、非三档 tier、adapter passed=null、
    cache key、legacy 映射、band 阈值测试。
11. §13：把“状态规模缓存”统一到 B2 的 key；加“review 陈旧不认证为新鲜”。

### 7.3 计划（`docs/superpowers/plans/2026-10-18-journey-control-and-admission-interpretation.md`）

1. 头部 Spec 改 v4；Review 列 v1/v2/v3 + 本文；Baseline 更新。
2. J2a-T1：删除 `PlanEvaluationDTO`/`EvaluationFindingDTO`/`StructureVectorDTO`/
   adapter，或把 J5.0 前移；若保留，列全字段/类型与 adapter 逐 check 映射；
   `candidateSourceVersion`/`source` 补齐；Java DTO 文件清单补齐。
3. J2a-T2：删除“消费 PlanEvaluation.findings”或改成“消费 checks 的
   drivers/caveats”；加 unit majorItems、九区间 tier、ratio-only-with-tier-null
   （不得反推 tier）测试。
4. J2b-T1：删 `$ref`；加“禁止 resolveEffectiveCandidates(..., true)”；定 join
   源；cache key 统一；证据 carrier；timeout/慢后端测试。
5. J1a-T1：`planVersion` 改 stateVersion 语义；`hasPlan` items/units；
   `stale`/`pendingStatus` 来源；`hasProfile`；删 journey admissionMode；
   Files 加 `contracts.py::StatePatch`；加 `PendingConfirmationSharedService`
   （getCurrent/active+applying）。
6. J1a-T2：创建 `JourneyAction` 枚举；`taskIntent` 映射；`available_actions`/
   `blocked_actions` 派生；stalePlanItemCount 或降级。
7. J1b-T1：fixture 引用 `JourneyAction`；补 `must_include_scope`/`addPolicy`/
   interpret_admission 状态更新。
8. J1c-T1：明确 applying 依赖 J1a 的 pendingStatus；固定文案列表。
9. J2c-T1：发射点改到 `server.py::_emit_turn_terminal`；Files 加
   `ui_events.EVENT_TYPES`/`event_store`/`server.py::_LEGACY_FRAME_TYPE` 的
   具体条目；band 阈值；冷加载取舍；legacy 映射测试。
10. J3：Files 加 `conversation_actions.py`（operationId/postcondition）与
    `PendingPlanningCommandRes` 读取；定义 origin/actionType/scope/receipt 来源；
    或后移到 J5.4。
11. J4a：先定 scope/学费/requiredCount 的唯一 owner、persist 语义、
    `persistTargetCount` 命名；REPLACE 的模型词汇；测试。
12. J5.0：前移为“定义 + 现有输出采样 + golden”，不要等 J4b；明确
    `CanonicalPlanningObjectiveSetDTO`/`PlanSolverResultDTO` 与新模型的映射。
13. J5.2：完整 probe 表、registry 字段、layer/severity、adapter 对照；
    前端/WorkflowStatus 消费者迁移。
14. J5.4/J5.5：PlanReceipt producer、objective_delta/suggested_command 唯一
    权威、TargetRef、fix metadata、golden/rollback。
15. 验收口径：加 cache key/version、review stale、unit majorItems、九区间、
    band 阈值、legacy 映射、ID 对照。

---

## 八、对审查目标 A–F 的直接回答

**A. Authority map correctness**

方向正确，但当前有 1 个 unsafe 的 ID 表、1 个不存在的 `$ref`、至少 6 处错误
合并/删除、2 个错误的数量/配额定义、1 个错误的版本模型。逐行见 §1。

**B. Definition detail**

`PlanEvaluation`/`EvaluationFinding` 的字段已比 v3 完整，但仍缺 Java DTO、
`metric`/`threshold` schema、`ObjectiveModel`/`CandidateSnapshot`/`TargetRef`；
`objective_delta → PlanCommand` 有 `ObjectiveDelta` 形状，但没有 ActionCompiler
接口、per-code delta 约束、`suggested_command` 一致性规则；review→action 不能
仅凭 findings 重建现有修复链（probe metadata 缺失）；interpretation 消费
findings 的过滤规则未写；`StructureVector` 不足以复算 probe；freshness/version
与代码相反；review vs optimizer dual 目前只是目标，不是可执行模型。

**C. Merge/delete safety**

现在可安全删的只有设计层无消费者项（system.action/review_read/旧名/身份参数）。
运行时 DTO/规则/字段（ReviewStateDTO、ReviewRuleRegistry、
RepairProposalTaxonomy、OrderedUnit.admissionRatio、actualChanges/reviewState、
PlanGoalTypeValue、summary 旧计数）必须“先建新 + 双写/对照 + 前端/持久化迁移”，
否则会改行为或反向定义语义。错误合并见 §5.3。

**D. Sequencing**

当前顺序（J2a/J2b → J1 → J2c → J4 → J5）在**代码依赖**上大致成立，但在
**语义依赖**上不成立：J2a 消费的 `PlanEvaluation`/`StructureVector` 是 J5.0
的定义；J1a 依赖的 stale/pending/taskIntent/JourneyAction 还没定义；J2c 的
发射点与设计矛盾；J3 没有 producer。建议把 J5.0 的“定义 + golden”前移，或
让 J2a 只消费 checks；否则会产生 throwaway DTO/适配器。

**E. Java/Python/frontend consistency**

`tier` 边界 Python `<50/<70` vs Java `<=50/<=70`；`planVersion`/stateVersion
三处说法不一致；`admissionMode` 的 `majorGroup` vs `major_group`（有归一，但
DTO 值要统一）；`OrderedUnitDTO.admissionRatio` 语义三处不同；
`reviewState.summary` 的旧计数在 Java `PlanningWorkflowStatusBuilder` 与前端
`ProposalCard/WorkspacePanel` 都在读；`PlanEvaluationDTO` 与设计字段不一致；
`Unit/volunteer ID` 两套前缀规则。详见 B2/B5/B8/M14-16。

**F. Missing from user ask**

“审查与优化合并”已写进 v4，但缺 `ObjectiveModel`/`EvaluationContext`/
probe registry 的可执行定义；“统一权威语义”还缺 current/target 标注和持久化
读兼容；“删除/合并决策”缺安全矩阵（本文补了）；“详细设计”缺 Java DTO、
ActionCompiler、per-probe 映射、缓存/版本、前端迁移。本文的 §7 是具体编辑清单。

---

## 九、审查边界

- 只读代码与文档；未运行测试、未调用模型、未部署。
- 文档在审查期间被多次修订；本文按 09:36 快照。行号可能随修订漂移，以引用的
  类/方法/字段名为准。
- 未验证真实库中是否存在 `$ref`；只确认 Java 代码没有 `$ref` 处理，且实际
  机制是 `candidatePoolRef`。如果真实数据确有 `$ref`，需要提供样例后另立切片。
- 未实测 4–29MB 候选池/1–4MB planningState 的解析耗时；5s 超时判断基于
  `ReadonlyDomainTools` 默认值。
- 未验证 `loadScoreDetail` 是否总能提供 subjectType；`hasProfile` 的科类判定
  以可见 DTO 为准。
- 未逐行核对 `PlanningStateService` 13k 行的所有调用点；review/ratio/count/
  safety/group-inner 五条主路径与 `RunReviewInternal` 已核对。
