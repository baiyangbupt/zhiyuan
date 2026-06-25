# Release 3.2.0 Execution Roadmap

本文是 3.2.0 的执行总路线。当前实现和路线对齐情况见 [release-3.2.0-current-framework-review.md](./release-3.2.0-current-framework-review.md)。已有两个文档分别记录结构性问题和模型能力 profile 计划：

- [release-3.2.0-structural-plan-framework-analysis.md](./release-3.2.0-structural-plan-framework-analysis.md)
- [release-3.2.0-model-capability-profile-plan.md](./release-3.2.0-model-capability-profile-plan.md)

本文件负责把它们落成工程推进顺序、验证门禁、旧路径删除口径和 explorer 迭代体系。3.2.0 可以使用受控只读 shadow 做硬切前对比，但不做长期 shadow、双写、兼容桥接或新旧多主路径并存。

## 1. 版本定位

3.2.0 不是继续给 3.1.1 的 bad case 加补丁，而是收敛以下长期问题：

- 一轮对话里存在多个局部裁决点：`intentSideEffectDecision`、intent preview、plan preview、review/fix proposal、directToolReturn、formatter、service recovery、pending guard。
- 工具取证、proposal 生成、pending 保存、回复渲染和回归断言之间缺少单一协议。
- 模型理解能力、结构化计划能力和回复生成能力没有独立 profile，导致架构设计缺少量化依据。
- 回归集混用了真实业务缺陷、fixture 不成立、旧断言契约和模型供应商不可用，影响系统收敛判断。
- 对话 explorer 能发现问题，但还没有稳定形成“发现 -> 分型 -> 晋级 golden -> 修复 -> 删除旧路径”的闭环。

3.2.0 的核心目标是建立：

```text
TurnDecision
  -> EvidencePlan
  -> ProposalCandidate
  -> ProposalCompiler
  -> Pending / Reply
  -> Apply
  -> Validate / Review
```

所有高副作用动作只能从 `ProposalCompiler` 产出唯一 pending 或 clarification。工具和 formatter 不能绕过 compiler 自行创建确认卡。

## 2. 根因定性

### 2.1 不是单点 bug

3.1.1 三轮回归显示，大多数基础链路可用；失败集中在混合回合、局部范围、pending 上下文、fixture 契约、模型 sideEffect 判断和 reply focus 保真。问题根源不是某个 case 没写规则，而是系统缺少统一裁决层。

典型表现：

- plan preview 已生成，但 intent empty preview 或后处理分支压掉 pending。
- 用户只问风险，系统生成 mutation card。
- pending 存在时，只读查询被 pending 边界话术抢占。
- 用户表达普通偏好，历史 state merge 后被升级成 `only_keep/must_have`。
- `review_plan` 作为 evidence step 后没有绑定用户 focus，回复泛化成通用审查。
- 无正式方案 fixture 下，case 仍期待删除、替换、刷新成功。

### 2.2 模型能力需要先量化

3.2.0 不能假设模型稳定理解：

- Policy / Explore / Intent / Plan 的任务层。
- readonly / intent_pending / plan_preview / apply_existing_pending 的副作用边界。
- current_plan / current_major_group / candidate_pool / future_reference 的对象范围。
- primary / acceptable / must_have / only_keep / exclude_hard 的偏好强度。
- review evidence 与用户 focus 的关系。
- 缺少分数、位次、正式方案、候选池时的 missingInfo。

所以主路径实现前必须先做离线 profile。profile 本身不进入 runtime，不作为 shadow router；后续若引入 shadow，只能是只读观测，不参与裁决、不创建 pending、不写业务状态。

## 3. 工作流总览

### Phase 0: 基线冻结和资产整理

目标：

- 保留 3.1.1 冻结提交作为基线。
- 不再向 3.1.1 添加结构性兼容路径。
- 将 3.1.1 已知问题、三轮回归、small regression、golden 候选和 fixture 噪声分开记录。

交付物：

- 3.2.0 roadmap。
- 3.2.0 profile case schema，见 [release-3.2.0-profile-case-schema.md](./release-3.2.0-profile-case-schema.md)。
- 回归资产索引和 fixture 契约。

验收：

- 每条 3.2.0 golden 候选都有来源、期望、禁止行为、归因标签。
- raw `assets/` 和 runtime `data/` 不进入代码提交。

### Phase 1: 模型能力 Profile 和 Benchmark 基座

目标：

- 对模型理解、结构化计划、回复生成和性能长尾进行独立评估。
- 先区分 provider 不可用、模型能力不足、schema 表达不足、compiler 缺失和 fixture 噪声。
- 搭建区别于 WebSocket e2e runner 的 model node benchmark，直接评估关键模型节点输入、结构化输出、稳定性和错误类型。

Profile case 必须包含：

```text
caseId
prompt
historyContext
fixtureContract
planningStateProfile
expectedTurnDecision
forbiddenDecisions
expectedEvidencePlan
expectedProposal
expectedPending
replyQualityAssertions
metricsTags
```

Provider precheck 必须记录：

- model id 是否存在。
- API key 是否可用。
- 余额/额度是否可用。
- direct smoke 是否成功。
- agent 是否真实用该 provider/model 启动。
- provider 不可用时不得计入模型质量矩阵。

Model node benchmark 必须记录：

- `node`、`actualSource`、`provider/model`、`latencyMs`。
- `rawActual` 与 `profileActual`：前者保留节点原始输出，后者是 3.2.0 profile 视图。
- 字段级 exact/contains/notContains 断言结果。
- `byNode`、`byTag`、`fieldFailures`、`schemaGaps`。
- `legacyOnlyFields`：旧字段存在但无法满足 3.2.0 新字段断言时单独统计。
- `rawTotal` 与进入质量矩阵的 `total` 分离。
- provider 环境失败按 `providerEnvExcludedByReason` 统计，不计入模型质量。
- 重复运行时输出 `stability.caseGroups`、`stablePassedGroups`、`stablePassRate`。
- legacy 字段不得被桥接成新字段通过；例如 live-node 只输出 `constraintIntentType` 时，应对缺失 `preferenceStrength/preferenceScope/entityPolaritySpans/admissionPath` 记失败和 `schemaGaps`。

指标：

- `taskLayer_accuracy`
- `sideEffect_accuracy`
- `scopeAnchor_accuracy`
- `preference_strength_accuracy`
- `schema_valid_rate`
- `compiler_accept_rate`
- `unsafe_side_effect_rate`
- `readonly_to_pending_false_positive_rate`
- `mutation_to_readonly_false_negative_rate`
- `focus_preservation_rate`
- `missingInfo_accuracy`
- `internal_terms_rate`
- `grounded_reply_rate`
- `model_request_count`
- `tool_count`
- `first_message_latency`
- `final_latency`
- `planning_latency`
- `tool_latency`
- `final_generation_latency`

验收：

- 至少覆盖 3.1.1 profile 文档中的 G1-G32 候选。
- 每个关键 case 至少三轮，输出平均值、p95、max 和稳定性标记。
- 产出能力边界结论：哪些交给模型，哪些必须由 compiler/guard/Java proposal 接管。
- 首批 live-node adapter 覆盖 `turn_side_effect`、`intent_side_effect`、`intent_entity_extraction`、`candidate_filter_extraction`、`plan_query_profile`、`plan_semantic_action`、`local_plan_action_dsl`、`proposal_selection`、`reply_focus_binding`、`reply_generation_grounding`；未接节点必须显式报告 `unsupported_live_node`。旧 `plan_recovery_action` 和 `composite_goal` 节点已删除，不再作为 benchmark-only 桥接维护。active pending 业务语义不再有独立模型 adapter，统一走 `TurnDecision -> PendingTurn compiler`。

### Phase 2: Fixture 化固定回归

目标：

- 修复“隐含 session id 等于场景状态”的测试问题。
- 让 full journey、special、science、score tier、open quality 等集合能明确声明前置状态。

Fixture 类型：

```text
empty_plan
formal_plan_present
candidate_pool_present
accepted_intent_present
pending_exists
generated_plan_preview_only
special_path_profile
score_profile_ready
missing_score_or_rank
```

Runner 要求：

- 每个 case 显式声明 fixture。
- runner 可 clone 或构造 backend state。
- 清理历史、pending、planning intent 时不能破坏 fixture。
- 空方案下期待 no-op/clarification；有正式方案时才期待 mutation pending/apply/refresh。

验收：

- fixture 不成立的失败不归类为产品缺陷。
- 每个失败都有 `defect/model/schema/compiler/fixture/env/assertion_noise` 归因。

### Phase 3: TurnDecision 和 ProposalCompiler 离线实现

目标：

- 先离线跑 compiler，不接 runtime mutation。
- 用 profile golden 验证唯一 sideEffect、proposal 编译和 reply plan。

核心结构：

```text
TurnDecision:
  taskLayer
  sideEffect
  scopeAnchor
  scenario
  targetIssue
  replyMode
  missingInfo
  applyExistingPending
  pendingConflictPolicy

EvidencePlan:
  requiredInputs
  steps
  toolBudget
  batchableQueries
  noResultReason

ProposalCandidate:
  type
  source
  payload
  evidenceRefs
  sideEffect
  confidence
  targetLayer
  executionAuthority

CompiledProposal:
  outputType
  pendingType
  executionPayload
  intentPayload
  displayPayload
  replyPlan
  blockingReasons
```

统一提议/动作空间：

- Goal space：表达用户目标、偏好强度、目标层、范围和冲突策略。
- Proposal space：承接 `intent_update_candidate`、`java_user_goal_request_candidate`、`java_fix_proposal_reference`、`plan_action_dsl_candidate`、`readonly_evidence_candidate`。
- Execution space：只消费 active pending 或 compiler output，由 intent apply、Java fix proposal apply、受控 plan action apply 和 workspace refresh 执行。

修复类动作必须进入 Proposal space 参与统一编排，但 Java `FixProposal` / dry-run / replacementPairs / candidate shortage / apply policy 仍是 Execution space 权威。Agent 不复制 Java repair candidate selection，也不在 service recovery 中把 unmatched fix proposal 改写成普通原子动作。

必须由 compiler 保证：

- 每轮只有一个 active sideEffect。
- `review_plan` 只能作为 evidence step，不能直接变成 mutation endpoint。
- empty intent preview 不能覆盖已可执行 plan preview。
- readonly 明确表达时，不生成高副作用 card。
- negative-only constraint 不要求 positive scope。
- soft preference 不升级 hard constraint。
- 当前方案 mutation 必须有 formal plan evidence 和可操作对象。
- pending 存在时允许 readonly query，但 mutation 必须先解决 pending 冲突。
- 多个高副作用候选必须澄清或形成一个 composite proposal。
- `java_fix_proposal_reference` 只有在 ready、有 action、有 sourceVersionGuard、dry-run observation 可解释时才能生成 pending；否则只能输出 readonly/diagnostic gap。

验收：

- Goldens 不依赖旧 recovery 也能得到正确 compiled output。
- 编译失败必须有结构化 blocking reason，而不是自然语言兜底。
- 多个 proposal candidates 只能生成一个 compiled output；可合并则 composite pending，不可合并则 clarification/diagnostic。

### Phase 4: Runtime 主路径硬切

目标：

- 把当前多处创建 pending/card 的路径收敛到 compiler 输出。
- 不保留新旧并行路径。
- 可在硬切前增加短期只读 shadow，对比旧路径观测与 `CompiledProposal`，但 shadow 输出不得影响用户响应、pending、apply 或 workspace refresh。

切换原则：

- Java `FixProposal`、dry-run、apply policy、version/status guard 继续作为方案变更权威。
- Python Agent 负责 `TurnDecision / EvidencePlan / ProposalCandidate`，不自行生成最终 replacementPairs 或绕过 Java apply policy。
- directToolReturn 只能返回 evidence 或 proposal candidate，不直接保存 pending。
- formatter 只渲染 compiler output，不升级 sideEffect。
- service recovery 只保留异常兜底和协议保护，不再补生成业务 pending。
- review/fix proposal 结果只能成为 `java_fix_proposal_reference` 或 evidence；不能由 promised preview recovery、unmatched proposal fallback、atomic recovery 独立创建 pending。

验收：

- 所有 `pendingConfirmationCard` 都能追溯到一个 `CompiledProposal`。
- 每条高副作用回复都能解释 `executionPayload`、`displayPayload`、`workspaceRefreshTargets` 和确认后 apply policy。
- 每条只读回复都能解释 evidence、missingInfo 或 noResultReason。
- shadow diff 只作为观测报告；上线主路径后删除 shadow 或默认关闭，不能作为兼容桥接长期存在。

### Phase 5: 删除旧路径和兼容逻辑

删除或降级：

- intent formatter 中独立保存 pending 的分支。
- plan action recovery 中不经过 compiler 的 pending 保存。
- review 后 promised preview recovery 中绕过 proposal endpoint 的逻辑。
- pending guard 中覆盖所有非确认文本的全局拦截。
- 基于最终自然语言“像确认文案”恢复执行的桥接。
- 只为旧 fixture 或旧文案断言服务的 keyword 兼容。
- 基于 raw prompt keyword 裁决业务语义的旧入口，例如 pending 影响查询、pending 后只读方案查询、apply-then-query、apply-then-generate、active pending 冲突和 query tool 内部的动作诉求拦截。这些语义必须来自 `TurnDecision`、`PlanQueryProfile`、action DSL 或 compiler 输出。
- 旧 compensation preview/apply 的用户侧入口。

保留：

- Java proposal/dry-run/apply policy。
- pending version/status 校验。
- 无 evidence 不生成执行卡。
- provider 不可用、工具异常、schema invalid 的安全兜底。
- 协议级短确认/取消、卡片 actionFamily 匹配、回复无依据承诺清理和模型中断兜底；这些只能保护协议或清理输出，不能作为业务意图识别来源。
- 输出保护类文本 guard，但只能清理无依据承诺，不能参与意图识别。

验收：

- 旧路径删除后，golden/current gate 不回退。
- 代码里没有两套可创建相同 pending 的入口。

### Phase 6: Explorer 迭代闭环

目标：

- 将对话模拟从“发现一堆 issue”变成稳定的产品演进系统。
- 每个 explorer 问题必须能进入归因、晋级、修复或降噪流程。

闭环：

```text
seed scenarios / production abstractions
  -> simulated user follow/diverge
  -> heuristic + LLM judge
  -> issue normalization
  -> fixture validation
  -> triage label
  -> golden promotion or discard
  -> implementation
  -> three-round regression
  -> dashboard trend
```

Issue 归因：

- `product_defect`
- `model_capability`
- `schema_gap`
- `compiler_gap`
- `reply_generation_gap`
- `fixture_mismatch`
- `assertion_noise`
- `provider_env`
- `latency_longtail`

晋级 golden 条件：

- 能复现。
- fixture 明确。
- 有业务期望和禁止行为。
- 能写成结构化断言。
- 不是 provider 不可用、judge 超时或旧断言噪声。

验收：

- explorer 每轮输出 issue 分布、Top N root cause、晋级 golden 列表和被丢弃噪声原因。
- 修复后的 golden 自动进入固定回归，不只留在临时报告。

## 4. Benchmark 体系

3.2.0 的 benchmark 分为五层：

| 层级 | 名称 | 目的 | 工具方向 |
| --- | --- | --- | --- |
| B0 | Provider Precheck | 确认模型接入可用 | direct `/models`、direct smoke、agent env smoke |
| B1 | Model Profile | 测理解、结构化计划、回复生成 | 离线 profile runner |
| B2 | Compiler Golden | 测 TurnDecision/Compiler 是否稳定 | 不启动 runtime mutation |
| B3 | Dialog Regression | 测 WebSocket、pending、apply、workspace refresh | fixture-aware runner |
| B4 | Explorer Discovery | 找表达长尾和多轮分叉 | autoexplorer + judge + promotion |
| B5 | Readonly Shadow Diff | 硬切前观测旧路径和 compiler output 差异 | 不写状态、不改响应、限期删除 |

当前已有工具可复用，但职责要收敛：

- `examples/model_provider_benchmark.py`：继续做 provider direct/agent 维度，但增加 precheck 状态，禁止把 provider error 当模型质量。
- `examples/dialog_regression_runner.py`：继续做固定回归，但补 fixture contract 和 root cause label。
- `examples/dialog_auto_explorer.py`：继续做探索，但输出 issue normalization 和 golden promotion 候选。
- 新增 profile runner：离线评估 `TurnDecision / EvidencePlan / replyPlan`。如需接 runtime shadow，只能接只读 diff 通道，不能参与业务裁决。
- `examples/downstream_policy_replay.py`：离线验证 `downstreamPolicy` 对 candidate selection、replacement、mustCover、softAvoid、tuition cap、capacity/no-result 的策略影响。它不替代真实 Java/rank/replacement，只作为 adapter 接入前后的契约门禁。
- `examples/downstream_adapter_dry_run.py`：离线消费 Java `FixProposalDTO` / `dryRunResult` / `candidateShortages` / `actions` fixture，归一成 3.2.0 下游观测字段。它只做协议评估，不调用 backend、不创建 pending、不 apply。

## 5. 关键场景覆盖

3.2.0 必须覆盖以下类别：

- Intent+Plan 混合回合：如“不要英语相关专业，当前方案里有的话也删掉”。
- review evidence 与 mutation endpoint 分离：如“把太贵的去掉看看”。
- focused readonly review：如“中外合作是不是多，预算一般，先别动”。
- pending + readonly query：如“先不确认，当前方案里有没有护理或者中医学”。
- soft preference / acceptable fallback：如“网络与新媒体优先，跨境电商也可以考虑”。
- negative-only constraint：如“东北西北都不要，必须避开”。
- missingInfo grounding：如缺分数/位次时查询候选。
- current major group local scope：如“专业组里只保留最稳的专业行不行”。
- confirm without pending。
- apply pending then new request：如“现在基于这些出方案”。
- plan local action：锁定、保留位置、tier-local ordinal。
- no formal plan reference：如“刚那个方案民办能少点不”。
- special path：强基、艺术类、批次、本科/专科路径。
- longtail performance：重复工具、工具预算、batch query。

## 6. 实施优先级

P0:

- Profile case schema 和 runner。
- Fixture contract 和 runner 清理/clone 策略。
- Provider precheck。
- TurnDecision / ProposalCompiler 离线原型。
- `pending + readonly query`、`intent+plan mixed`、`review focus`、`preference strength`、`missingInfo` golden。

P1:

- Runtime compiler 接入 pending/card 创建。
- Java proposal 统一 endpoint 和 display payload 补齐。
- Reply plan grounding 和 focus binding。
- Explorer issue normalization。

P2:

- Tool budget、batch query、latency dashboard。
- plan local action DSL 扩展。
- selectableProposal/suggestedTransition。
- 特殊批次/路径一等字段。

## 7. 合并门槛

3.2.0 合并前必须满足：

- Profile 已跑完并产出能力边界。
- 每个高副作用 golden 都有唯一 sideEffect 和唯一 pending/apply 协议。
- 每个只读 golden 都有 evidence/missingInfo/noResultReason。
- Fixture 噪声不计入产品缺陷。
- Runtime 不保留双路径 pending 创建。
- 删除清单已执行或有明确一次性迁移说明。
- current gate 三轮和 3.1.1 P0 small regression 不回退。
- explorer 新发现 issue 可以被归因、晋级或降噪。

## 8. 最近行动项

已完成：

- 定义 profile case JSON schema：[release-3.2.0-profile-case-schema.md](./release-3.2.0-profile-case-schema.md)。
- 落地 G1-G32 profile golden 样例：[dialog_profile_320_golden_cases.json](../zhiyuan-agent/examples/dialog_profile_320_golden_cases.json)。
- `model_provider_benchmark.py` 增加 provider precheck，能把缺 key、模型不存在、余额/权限等问题隔离为 `provider_env`，并支持 `--skip-unavailable-providers`。
- `dialog_regression_runner.py` 增加 `fixtureContract` 和 `expectedRootCause` metrics 占位，先把 fixture 噪声、环境问题、旧断言噪声和产品缺陷分开统计。
- 定义并落地独立模型节点 benchmark：[release-3.2.0-model-node-benchmark.md](./release-3.2.0-model-node-benchmark.md)，首版脚本为 [model_node_benchmark.py](../zhiyuan-agent/examples/model_node_benchmark.py)，G1-G32 节点样例为 [model_node_benchmark_320_cases.json](../zhiyuan-agent/examples/model_node_benchmark_320_cases.json)。
- `model_node_benchmark.py` 支持离线 actual 对比、`--actual-source live-node`、`--nodes` 筛选和 `--repeat` 稳定性统计。
- 2026-06-21 已接 adapter 子集完成 live-node 三轮基线：33 次调用，9 通过、24 失败，passRate `0.2727`，providerEnvExcluded `0`，stablePassRate `0.1818`。失败集中在 `constraintIntentType`、`replyFocus/targetIssueCodes`、无 pending 确认、tier-local reorder 和 unsupported local action。
- 2026-06-21 model node profile schema 已更新：报告保留 `rawActual/profileActual/schemaGaps`，G4/G13/G18/G23/G25/G29/G30 断言改为 `preferenceStrength/preferenceScope/entityPolaritySpans/admissionPath`。离线目标基线 `/private/tmp/model_node_320_profile_schema_latest.json` 为 33 通过、0 失败、`schemaGaps={}`；live-node 若仍只产 legacy 字段必须继续失败。
- 2026-06-21 schema 更新后已接 adapter live-node 单轮基线 `/private/tmp/model_node_320_live_schema_r1.json`：11 case，2 通过、9 失败，passRate `0.1818`，providerEnvExcluded `0`。`schemaGaps` 集中在 `preferenceStrength.primary/acceptable/preferred/exclude_hard`、`preferenceScope` 和 `unsupportedAction`，说明下一步应先补节点输出协议，而不是在 runtime 用 legacy 字段桥接。
- 2026-06-22 model-node benchmark 增加 `legacyOnlyFields`：`constraintIntentType` 会保留到 `profileActual.legacy` 供诊断，但不会填充 `preferenceStrength/preferenceScope/entityPolaritySpans/admissionPath`。当 case 断言新字段而 live-node 只给旧字段时，报告同时出现 `schemaGaps` 和 `legacyOnlyFields`，作为 schema hard-cut 阻塞信号。
- 2026-06-22 网络恢复后重跑 3.2.0 schema 相关 live-node adapter。修前 `/private/tmp/model_node_320_live_intent_schema_r3_before_prompt_fix.json` 为 24 case、6 通过、18 失败，主要问题是 `intent_side_effect` 把 `preferenceStrength` 输出成“实体 -> 强度列表”的反向结构，G18 丢失 `structuredIntents` 正向院校，G25 span 未规范化 `口腔医学`。修后 `/private/tmp/model_node_320_live_intent_schema_after_optional_path_fix_r3.json` 为 24/24 通过、`schemaGaps={}`、`legacyOnlyFields={}`、stablePassRate `1.0`。离线门禁同步通过：`/private/tmp/model_node_320_after_live_schema_fix_offline.json` 为 33/33，`/private/tmp/proposal_compiler_320_after_g23_primary.json` 为 32/32。G23 期望已从 `preferred` 修正为 `primary`，因为“城市优先长三角”里的“优先”按 3.2.0 strength 定义属于最高优先级。
- 2026-06-22 接入 `turn_side_effect` live-node adapter，使用 `turn_decision_tool` 直接输出 3.2.0 TurnDecision schema，不接 runtime service、不创建 pending。首次单轮 `/private/tmp/model_node_320_live_turn_decision_r1.json` 为 13 case、1 通过、12 失败，集中在 `scenario` 自造/自然语言输出、`pendingExists/formalPlanPresent` 被用户话术覆盖、候选池/专业组 taskLayer 边界不清和 JSON extra data。收紧 allowedValues、状态权威规则、G1/G3/G6/G9/G14/G19/G22/G24/G27/G31/G32 边界例子和单 JSON object 后，三轮 `/private/tmp/model_node_320_live_turn_decision_after_prompt_fix3_r3.json` 为 39/39 通过、stablePassRate `1.0`、`fieldFailures={}`、`schemaGaps={}`、`legacyOnlyFields={}`，latency median `4392ms`、p95 `9567ms`、max `9993ms`。
- 2026-06-22 接入 `reply_focus_binding` 和 `reply_generation_grounding` live-node adapter，使用 `reply_profile_tool` 输出回复 profile 字段，不生成最终用户回复、不接 runtime service。单轮 `/private/tmp/model_node_320_live_reply_profile_r1.json` 为 2/2 通过；三轮 `/private/tmp/model_node_320_live_reply_profile_r3.json` 为 6/6 通过、stablePassRate `1.0`、`fieldFailures={}`、`schemaGaps={}`、`legacyOnlyFields={}`，latency median `4274ms`、p95/max `9811ms`。G7 稳定保留中外合作与预算风险 focus，G20 稳定要求省份和艺术类综合分公式，不允许编造精确分数。
- 2026-06-22 继续收敛已接 live-node adapter：旧 pending 模型节点当时补了 no-active-pending 硬门禁，但 2026-06-24 已删除；`plan_semantic_action` 在 `none` 结果中保留 reply focus 和 target issue；`plan_recovery_action` 增加 `unsupportedAction=pin_or_lock_unit` 和 tier-local ordered move；`intent_side_effect` 明确 `primary/preferred/acceptable` 边界，并强制保留 `structuredIntents.school.positiveSchools`；G25 fixture 将“加意向”正向 strength 从 `primary` 修正为 `preferred`。修后单轮全量 `/private/tmp/model_node_320_live_supported_all_after_g24_fix_r1.json` 为 30/30 通过，`fieldFailures={}`、`schemaGaps={}`、`legacyOnlyFields={}`。全量三轮 `/private/tmp/model_node_320_live_supported_all_after_g18_fix_r3.json` 为 89/90，唯一失败是 G8 r2 的 `taskLayer plan` 漂移；随后补 G8 规则后 `turn_side_effect` 三轮 `/private/tmp/model_node_320_live_turn_decision_after_g8_intent_layer_fix_r3.json` 为 39/39。其余节点在全量三轮均为 3/3。
- 2026-06-22 最终复跑已接 live-node adapter 全量三轮。中间复跑 `/private/tmp/model_node_320_live_supported_all_final_r3.json` 暴露 G18 r2 将“保底要公办不要民办”降级为 `mixed_answer_then_ask`；修正为 `intent_preview` 后 `intent_side_effect` 三轮 `/private/tmp/model_node_320_live_intent_side_effect_after_g18_decision_prompt_r3.json` 为 12/12。随后全量 `/private/tmp/model_node_320_live_supported_all_after_g18_decision_prompt_final_r3.json` 暴露 G16 r2 的 optional list/bool 字段 `null` 解析失败；在 `PlanRecoveryActionDecision` schema 边界规范化 `null -> []/false` 后，`plan_recovery_action` 三轮 `/private/tmp/model_node_320_live_plan_recovery_after_null_coerce_r3.json` 为 6/6。最终全量 `/private/tmp/model_node_320_live_supported_all_after_plan_recovery_null_coerce_final_r3.json` 为 90/90，stablePassRate `1.0`，`fieldFailures={}`、`schemaGaps={}`、`legacyOnlyFields={}`，providerEnvExcluded `0`，latency median `4394ms`、p95 `12387ms`、max `21405ms`。
- 落地离线 `TurnDecision -> ProposalCompiler` golden 原型：[proposal_compiler_golden.py](../zhiyuan-agent/examples/proposal_compiler_golden.py)。该脚本只跑 JSON 输入输出，不接 WebSocket、不创建 pending、不调用模型。
- 2026-06-21 compiler golden 跑 G1-G32：32 通过、0 失败，passRate `1.0`。说明当前 profile case 的协议硬约束可由 deterministic compiler 承接，和 live-node 失败形成对照。
- `proposal_compiler_golden.py` 已扩展到完整 `CompiledProposal` 离线 schema，输出 `executionPayload`、`intentPayload`、`displayPayload`、`replyPlan`、`workspaceRefreshTargets` 和 `blockingReasons`。
- 2026-06-21 compiler full schema 基线：32 通过、0 失败，passRate `1.0`，报告为 `/private/tmp/proposal_compiler_320_g1_g32_full_schema.json`。其中 `apply_then_readonly` 已从泛化 composite 中拆出，pending conflict 不创建双 pending，readonly/needs-plan-first 不产生 execution payload。
- 2026-06-21 compiler full schema 增量：新增 `evidenceContract`、`planActionDsl`、`entityPolaritySpans`、`preferenceScope` 透传和基础校验。G16/G17 可表达 pin-lock、tier-local ordinal；G25 可表达 span 级 polarity；G30 可表达 `admissionPath=strongbase`；报告 `/private/tmp/proposal_compiler_320_g1_g32_full_schema_latest.json` 为 32 通过、0 失败、`blockingReasons={}`。
- 2026-06-21 compiler downstream policy 增量：新增 `downstreamPolicy`，将 `exclude_hard/only_keep/must_have/primary/preferred/acceptable` 编译为候选硬过滤、rank boost、补位优先级、替换优先级和保护策略。最新报告 `/private/tmp/proposal_compiler_320_g1_g32_downstream_policy_latest.json` 为 32 通过、0 失败、`blockingReasons={}`。
- 2026-06-21 compiler repair arbitration 增量：`proposal_compiler_golden.py` 支持 `proposalCandidates`、`executionAuthority` 和 `candidateArbitration`，新增样例 [proposal_compiler_repair_arbitration_320_cases.json](../zhiyuan-agent/examples/proposal_compiler_repair_arbitration_320_cases.json)。当前报告 `/private/tmp/proposal_compiler_320_repair_arbitration_latest.json` 为 4 通过、0 失败，覆盖 ready Java fix proposal、ready-without-actions contract gap、intent update + Java fix 合并、rank-only 不可生成 repair mutation。
- 2026-06-21 落地 compiled pending sink contract：[compiled_pending_sink_contract.py](../zhiyuan-agent/examples/compiled_pending_sink_contract.py)，样例为 [compiled_pending_sink_contract_320_cases.json](../zhiyuan-agent/examples/compiled_pending_sink_contract_320_cases.json)。当前本地门禁为 7 通过、0 失败，覆盖 intent/plan/fix 三类 compiler-only sink request，以及 readonly、缺 compiled id、plan 缺 `plan_confirmation_candidate`、fix 缺 actions 的阻断。普通 plan sink 不再接受“只有 compiled id + actionFamilies”的旧形状。
- 2026-06-21 落地 `handle_intent_select` 离线 adapter：[intent_select_compiler_adapter.py](../zhiyuan-agent/examples/intent_select_compiler_adapter.py)，样例为 [intent_select_compiler_adapter_320_cases.json](../zhiyuan-agent/examples/intent_select_compiler_adapter_320_cases.json)。当前报告 `/private/tmp/intent_select_compiler_adapter_320_latest.json` 为 4 通过、0 失败；runtime direct selectedData 分支已硬切到 compiled intent proposal + intent sink contract，删除默认关闭开关和旧直连路径。
- 2026-06-21 落地显式 intent preview follow-up adapter：[intent_preview_compiler_adapter.py](../zhiyuan-agent/examples/intent_preview_compiler_adapter.py)，样例为 [intent_preview_compiler_adapter_320_cases.json](../zhiyuan-agent/examples/intent_preview_compiler_adapter_320_cases.json)。当前离线门禁为 5 通过、0 失败，覆盖 prefer preview、only_keep preview、未 confirmed、无 selected、only_keep 无 scope 的阻断。
- 2026-06-21 runtime intent 输入校验已收口到 `proposal_compiler.resolve_intent_select_input` / `resolve_intent_preview_input`：service 只负责 parse/merge/展示文案，selected 非空、merged 非空、constraint scope 是否完整、constraintIntentType 归一由 compiler 规则统一裁决。structured goal intent fallback 也已改为同一 resolution；展示层仍保留 preview `items[].value` 扫描，用于生成“适当靠后/优先”等文案，不参与 pending 输入裁决。`only_keep/must_have` 的原始意图如果没有正向 scope 必须阻断，不能降级成 exclude/default intent card；该边界已由主流程回归固定。
- 2026-06-21 `_create_pending_intent_confirmation_result_from_preview_payload` 已收紧为 compiled-contract-first：先构造 `_IntentPreviewCandidate` 和 `CompiledProposal(intent_change)`，通过 intent sink contract 后才调用底层 intent sink，并统一返回 `card/workspace_refresh_targets/blocked_reasons`；constraint 命中 Java user-goal ready proposal 时转 compiled fix proposal，ready-without-actions/dry-run/version guard gap 直接阻断。无结构化候选的自然语言承诺恢复已删除；结构化 composite/interest fallback 和主流程后处理仍按调用源 legacy risk 计入，下一步继续删除这些调用源。
- 2026-06-21 constraint preview -> Java user-goal fix 已拆成 `_UserGoalFixCandidate` 构造和 `_create_pending_fix_confirmation_result_from_user_goal_candidate` sink 适配，并删除 `_maybe_create_plan_confirmation_from_constraint_preview` 旧包装入口。当前该 candidate sink 已经 hard cut 到 compiled-contract-first：必须构造 `CompiledProposal(java_fix_proposal_reference)` 并通过 fix sink contract 后才落 pending，且返回 result metadata；ready 但缺 actions/dry-run/version guard 会直接阻断，不再由 Agent 补动作或降级成 intent card。
- 2026-06-21 structured/composite goal 已拆成 `_structured_user_goal_fix_candidate_from_source`、`_structured_goal_intent_candidate_from_source` 和 `_create_pending_intent_confirmation_from_structured_goal_candidate`，并删除 `_maybe_create_plan_confirmation_from_structured_goal` / `_maybe_create_intent_confirmation_from_structured_goal` 旧混合 helper。structured fix 复用通用 compiled user-goal candidate sink；structured intent fallback 也必须先构造 compiled intent proposal 并通过 intent sink contract。
- 2026-06-21 user-goal Java proposal ready 选择已收口到 `proposal_compiler.select_user_goal_fix_proposal`：constraint preview 和 structured goal 不再各自按 goalType 展开 `select_ready_fix_proposal`，缺 goalType 会阻断并保留 fallback proposal 用于解释/intent fallback，不会退化成第一条 ready。Java `FixProposal` 仍是执行权威，Agent 不复制 replacement pairs 或 apply policy。
- 2026-06-21 落地并扩展 downstream policy fixture replay：[downstream_policy_replay.py](../zhiyuan-agent/examples/downstream_policy_replay.py)，样例为 [downstream_policy_replay_320_cases.json](../zhiyuan-agent/examples/downstream_policy_replay_320_cases.json)。当前报告 `/private/tmp/downstream_policy_replay_320_latest.json` 为 9 通过、0 失败，覆盖 primary/acceptable、scope hard exclude、mixed polarity、admissionPath filter、onlyKeep、mustCover、avoidSoft、tuition cap、capacity/no-result。
- `downstream_policy_replay.py` 已支持 inline policy case，用于补齐 G1-G32 compiler report 里暂未出现的下游边界；报告新增 `policySource`、`capacityStatus`、`noResultReason`、`shortageCount`、`missingMustCover` 和 `mustCoverSatisfied`。这些字段是 3.2.0 adapter/dry-run 的观测契约，不是运行时推荐逻辑。
- 2026-06-21 落地 downstream adapter dry-run：[downstream_adapter_dry_run.py](../zhiyuan-agent/examples/downstream_adapter_dry_run.py)，样例为 [downstream_adapter_dry_run_320_cases.json](../zhiyuan-agent/examples/downstream_adapter_dry_run_320_cases.json)。当前报告 `/private/tmp/downstream_adapter_dry_run_320_latest.json` 为 5 通过、0 失败，覆盖 Java ready replacement、blocked candidate shortage、mustInclude ready/blocked 和 ready-without-actions contract gap。
- adapter 当前可从 Java proposal 归一：`replacementCandidateIds`、`candidateVolunteerIds`、`replacementPairs`、`capacityStatus`、`noResultReason`、`shortageCount`、`availableCount`、`missingMustCover`、`contractGaps`。这说明 Java `FixProposalDTO` 已具备 3.2.0 dry-run 观测基础，下一步不是在 Agent 复制候选选择，而是把真实 dry-run 响应接到这个归一层。
- 2026-06-21 落地 downstreamPolicy -> Java user-goal request mapper：[downstream_policy_java_request.py](../zhiyuan-agent/examples/downstream_policy_java_request.py)，样例为 [downstream_policy_java_request_320_cases.json](../zhiyuan-agent/examples/downstream_policy_java_request_320_cases.json)。当前报告 `/private/tmp/downstream_policy_java_request_320_latest.json` 为 7 通过、0 失败，其中 `requestReady=5`、`requestNotReady=2`。
- Java request mapper 当前固定 taxonomy 对齐：`only_keep -> only_keep_scope`、`must_have/mustCover -> must_include_scope`、`exclude_hard -> exclude_scope`、`tuition_cap/maxTuitionPerYear -> tuition_budget_scope`。`primary/preferred/acceptable` 和纯 `avoid_soft` 不生成 Java 方案变更 request，只记录 rank-only gap；`admissionPath` 暂映射为 `program_type`，并记录 `program_type_text_match_only` 风险。
- 2026-06-21 落地 downstream contract gate：[downstream_contract_gate.py](../zhiyuan-agent/examples/downstream_contract_gate.py)，汇总 policy replay、Java request mapper 和 adapter dry-run 三层报告。当前报告 `/private/tmp/downstream_contract_gate_320_latest.json`：`gatePassed=true`、三组件 9/9 + 7/7 + 5/5 全通过，`expectedGapCount=4`。
- 当前 downstream gate 预期 gap：`rank_only_policy:primary,acceptable`、`soft_avoid_rank_only`、`program_type_text_match_only`、`ready_without_actions`。这些不是当前离线门禁失败，但都是 runtime 接入前必须显式处理或继续阻断的契约点，不能用 service/formatter 桥接。
- 2026-06-21 落地 runtime pending/card 静态入口审计：[runtime_pending_entrypoint_audit.py](../zhiyuan-agent/examples/runtime_pending_entrypoint_audit.py)，fixture 为 [runtime_pending_entrypoints_320.json](../zhiyuan-agent/examples/runtime_pending_entrypoints_320.json)，期望为 [runtime_pending_entrypoints_320_expectations.json](../zhiyuan-agent/examples/runtime_pending_entrypoints_320_expectations.json)。当前报告 `/private/tmp/runtime_pending_entrypoint_audit_320_latest.json`：`passed=true`、`total=8`、`missing=0`、`legacyRiskCount=0`、`deleteAfterCutCount=0`。
- runtime entrypoint 审计口径：`compiler_sink_after_cut=4` 只能消费 compiler output，`compiler_entry_after_cut=2` 是 plan/fix 主流程统一 runtime compiled pending 入口，`delete_after_cut=0` 表示无独立待删变量入口，`execution_keep=1` 保留 pending apply guard。`legacyRiskCount` 只统计直接创建/恢复 pending/card 的路径；主流程 plan candidate 和 review/fix proposal card 选择权已从分散后处理迁到统一 compiled entry。
- 2026-06-21 落地 runtime pending sink 调用点审计：[runtime_pending_sink_call_audit.py](../zhiyuan-agent/examples/runtime_pending_sink_call_audit.py)，fixture 为 [runtime_pending_sink_calls_320.json](../zhiyuan-agent/examples/runtime_pending_sink_calls_320.json)，期望为 [runtime_pending_sink_calls_320_expectations.json](../zhiyuan-agent/examples/runtime_pending_sink_calls_320_expectations.json)。当前报告 `/private/tmp/runtime_pending_sink_call_audit_320_latest.json`：`passed=true`、`actual=15`、`legacyDirectCreateCount=0`、`compilerOnlySinkCallCount=9`、`compilerEntryCallCount=0`、`statusUpdateKeepCount=6`。
- sink 调用点迁移分组：底层 sink 层已无 `legacy_direct_create`。direct intent select、intent preview result helper、constraint/structured user-goal candidate、runtime plan entry 和 runtime review/fix entry 均已归入 compiled sink contract；旧的 plan/fix card-only wrapper 已删除，不再作为中间桥。runtime compiled proposal/contract、deterministic fix proposal arbitration、target-scope 归一/过滤和 blocking reason 已从 `service.py` 抽到 [proposal_compiler.py](../zhiyuan-agent/app/domain/proposal_compiler.py)，`service.py` 只保留模型调用、上下文组装和落 sink。agent 中断后的 plan pending recovery、无结构化候选的自然语言承诺恢复、只读误路由恢复、composite goal recovery、预算/学费误路由 recovery、主流程 `recovered_pending_intent_card` 变量路径和 full-agent 后处理 no-tool explicit intent fallback 已删除。剩余工作是把模型 target-scope 调用本身、runtime_intent_hard_cut 的实体 profile 输入和 TurnDecision 输入替换为正式 ProposalCompiler 输出，不能把 runtime entry 当长期兼容桥。
- runtime fix proposal 选择现在统一输出 `FixProposalSelectionResult`，包含 `proposal/selectedProposalId/targetScope/targetMatchEmpty/blockingReasons`；主流程不再重复展开 selected id、target scope 唯一命中和 target empty 的分支。`FixProposalTargetScopeResolution` 进一步把显式 result scope、selected id、无 ready proposal、是否需要 semantic decision 和 decision scope 归一收到 [proposal_compiler.py](../zhiyuan-agent/app/domain/proposal_compiler.py)，`service.py` 只负责在 domain 判定需要时调用模型。`runtime_fix_proposal_confirmation_source_from_result` 又把 `execute_plan_action(preview_fix_proposal)` tool call payload 与 result 是否可作为确认源的判断收口到 domain 层，service 只遍历工具消息。`compile_runtime_review_fix_source` 将 selection、sourceVersionGuard、proposalSource 和 compiled review/fix proposal 统一产出，service 不再直接调用 `select_fix_proposal_candidate_for_runtime` 或自行拼装 compiled proposal。`select_user_goal_fix_proposal` 将 user-goal Java proposal 按 goalType 选择 ready、fallback proposal 和 sourceVersionGuard 统一产出。`resolve_intent_select_input` / `resolve_intent_preview_input` 将 intent pending 输入校验和 constraint type 归一收口到 compiler，覆盖 direct select、preview 和 structured intent fallback。`resolve_plan_confirmation_candidate` / `compile_runtime_plan_confirmation_source` 将普通 plan candidate 的 action family、plan payload JSON、apply stage、requiresConfirmation、sourceVersionGuard 和 blocking reason 收口到 compiler；`PENDING_PLAN_ACTION_FAMILIES` 由 compiler 统一定义，service 只复用。新增直接单测固定 selected id 命中/缺失、显式空 target、target 无 ready、target 歧义、唯一 ready、多 ready 无目标、semantic decision precheck、decision scope、confirmation source 过滤、target_match_empty、compiled source 成功、缺 version guard 阻断、user-goal goalType 命中/fallback/缺 goalType 阻断、intent selected/preview 输入阻断、only_keep/must_have 正向 scope 缺失阻断、plan candidate 成功编译、fix proposal 误入 plan sink 阻断、action family mismatch 阻断、非 apply stage 阻断等边界；`selectedProposalId` 过期或不可 ready 时不会 fallback 到其他 proposal。
- 2026-06-22 active pending turn 的确定性解析开始收口到 `proposal_compiler.resolve_pending_turn_action`。当前已固定：`reject_pending` 只取消已有 pending；`ask_pending_impact` 保持 pending active，只返回待确认内容对当前方案/后续参考的影响说明，并且不调用 pending classifier 或模型；缺 active pending 时直接阻断为 `missing_active_pending`。`apply_pending_then_readonly` 现在由 compiler 产出结构化 `postApplyEvidencePlan`，runtime 先按已有 pending 校验执行 apply；apply 成功后保存 EvidencePlan，按其 `workspaceRefreshTargets` 组织 refresh。普通 `plan_mutation -> execute_plan_action` 成功后会二次读取最新 planning workspace，并按 `remaining_count/tier_distribution/risk_review` 输出当前志愿数量、冲稳保分布和审查风险；刷新失败或缺字段时才保留证据边界，不调用模型或 pending classifier，也不回答未经证据支持的数量、梯度或风险结论。apply 失败时只返回失败/失效结果，不追加只读结论。`intent_change` 采纳后的“对当前方案影响”仍保持保守边界，后续应进入独立影响评估节点，不能从偏好写入直接推断方案变化。G14 `apply_pending_then_new_request` 已从“只保留诉求”推进到 compiled plan pending：active intent pending 下“现在基于这些出方案”会先采纳已有 pending，再由 `proposal_compiler.compile_apply_then_generate_plan_source` 产出 `generate_plan` plan confirmation candidate，通过 `_create_runtime_compiled_plan_pending` 创建新的“确认生成方案”卡；不直接生成正式方案、不调用模型、不绕过 plan sink。`postApplyEvidencePlan` 已写入 route observability，`dialog_regression_runner.py --runtime-shadow-output` 和 `runtime_shadow_diff.py` 可以对比 compiler `evidenceContract` 与 runtime observation。新增否定执行保护，`先不确认/不确认/先不执行` 这类文本不会因为包含裸 `确认/执行` 被误判成 apply。
- 2026-06-22 active pending 新诉求冲突已先落 deterministic guard。已有 active pending 时，用户又提出删除、加入、替换、只保留、排除、补齐、生成、重排等新高副作用诉求，runtime 在模型前返回 `conflict_with_existing_pending` 说明，保持原 pending active，不创建第二张卡、不覆盖 pending、不调用模型或 recovery。只读影响查询、取消、短确认、apply-then-readonly 仍按各自确定性分支优先处理。完整 merge/replace/放弃后重建策略后续进入 TurnDecision，不在 service 里临时桥接。
- 2026-06-22 runtime 增量：`needs_plan_first` 已接入确定性前置 guard。用户显式引用“刚那个/当前/方案里”的方案对象，但后端 planning summary 明确为无正式方案、无工作方案时，runtime 直接返回“需要先生成方案”的防御回复，不调用模型、不创建 intent pending、不写入偏好、不改动方案。状态未知时不触发该 guard，避免把后端读取失败误判成无方案。
- 2026-06-22 hard-cut 增量：runtime 已删除旧 pending classifier 调用。active pending 的 apply/cancel 只允许短文本确定性协议或卡片确认触发；长文本重复目标、细化目标或新诉求不再由模型 pending classifier 直接采纳/取消。新高副作用诉求已先由 compiler resolver 阻断为 `conflict_with_existing_pending`，后续的 pending merge/replace/放弃后重建策略仍需要进入 TurnDecision。2026-06-24 已进一步删除该工具函数和 benchmark adapter。
- 2026-06-22 hard-cut 增量：active pending 短文本确认也已从 `service.py` 本地 token 函数迁入 `proposal_compiler.resolve_pending_turn_action`，统一输出 `confirm_pending/apply_existing_pending`。service 不再维护第二套 active pending direct-confirm 白名单，只负责按 compiler resolution 调用 `handle_pending_confirmation`。
- 2026-06-22 hard-cut 增量：无 active pending 时的短文本确认 guard 也已迁入 `proposal_compiler.pending_turn_looks_no_active_pending_confirmation`。service 不再维护 no-pending 确认白名单，只负责在没有 active pending 且不属于计划 follow-up confirmation 时返回 no-pending guard。
- 2026-06-23 action-scoped 短确认继续收口：`确认生成/确认删除/确认移动/确认加入` 不再作为全局短句白名单。`proposal_compiler.resolve_pending_turn_action` 只在 active pending 为 `plan_mutation` 时读取 `actionFamily` 或 `executionPayload.planPayload.action_family`，并要求短确认中的动作语义与当前 pending action family 匹配；错配时不走 `apply_existing_pending`。新增单测覆盖 `generate_plan/add_units/remove_units/move_ordered_unit/regenerate_order` 的匹配确认、从 plan payload 回读 action family、以及 `remove_units` pending 下 `确认生成方案` 不执行。chat service focused 子集也覆盖 action-scoped confirm 不进模型。该设计保留短确认的确定性前置能力，但确认副作用由 active pending 元数据决定，不由单个用户短句独立决定。
- 2026-06-24 active pending 业务语义从 compiler/service prompt keyword hard-cut：`resolve_pending_turn_action` 只保留 active pending 的协议级取消/确认，`ask_pending_impact`、`apply_pending_then_readonly`、`apply_pending_then_new_request`、`conflict_with_existing_pending` 改由 `TurnDecision -> compile_runtime_pending_turn_decision_source` 结构化输出驱动；`compile_post_apply_readonly_evidence_plan` 只消费 `TurnDecision.targetIssue`，不从用户原话推断查询范围；`compile_apply_then_generate_plan_source` 只在调用方已给出结构化 apply-then-generate 语义后编译。同步删除空 shim、旧 pending classifier 和 benchmark adapter。
- 2026-06-24 runtime intent hard cut 不再依赖 `prompt_looks_explicit_intent_update`。入口先消费 `TurnDecision`，再用 `intent_entity_profile` 的结构化实体和 confidence 创建 intent pending；`profile_change_replan/profile_replan_adhoc/profile_replan_ambiguous`、pending readonly/apply/conflict 等结构化场景会阻断 intent hard cut，且 profile replan 复用同一个 TurnDecision，避免重复分类和误抽意向。
- 2026-06-24 删除 `query_volunteer_plan` 内部 `_looks_like_plan_action_query` 词表拦截。query tool 不再根据“补几个/还差/加入方案”等用户措辞拒绝查询；动作诉求必须由上游 `TurnDecision/PlanSemanticAction/action DSL` 路由到 plan preview。若上游误调 query tool，工具只按普通局部查询返回 evidence/no-result，不创建 pending、不输出动作边界。
- 2026-06-24 删除一个确认卡提取中的调整诉求词表：非可执行 `analyze_adjustment/adjustment_analysis` 后阻断 `generate_plan` 预览改为结构化状态判断，不再比较 `user_goal` 里是否出现“更稳/优化/弄一版”等词。
- 2026-06-22 runtime targeted 增量：针对 G4/G23/G25 和生产“文本要求确认但无卡”问题，补了显式意向写入的 no-tool 兜底入口，但门禁收紧为“无本轮工具调用、无 active pending、非只读、非 plan chain、非已有 preview”，并且只能走 `analyze_volunteer_intent_change -> _create_pending_intent_confirmation_result_from_preview_payload -> compiled intent sink`，不直接写状态。只读 compare misroute 已用单测固定：有 `compare_major_options` 等只读工具时不得触发该兜底。
- 2026-06-22 runtime targeted 增量：G25 的根因不是模型 profile 判断错误，而是 `intent_state_tool` 的本地极性补偿把“加意向 排除...”同句四个专业全部补成 negative，随后冲突清理删掉正向项。现已把“加意向/加入意向/记到意向”识别为正向 marker，并按 `加意向 排除` 动作边界拆分 clause；新增单测固定“生物医学工程、智能医学工程”为正向，“临床医学、口腔医学”为负向。
- 2026-06-22 targeted shadow clean run：带 `--clear-history-per-case --clear-backend-pending-per-case --clear-backend-planning-intent-per-case` 重跑 G4/G23/G25，报告 `/private/tmp/runtime_shadow_320_blocking_probe_after_polarity_fix_clean.json` 为 `intent_pending=3`、`pendingType intent_change=3`；diff `/private/tmp/runtime_shadow_diff_320_blocking_probe_after_polarity_fix_clean.json` 在 3 个 observed case 上 `clean=3`、`blocking=0`、`major=0`。注意：不清 `pendingConfirmation` 会让后续 case 带入脏 active pending，产生 `conflict_with_existing_pending` 假失败。
- 2026-06-22 回归断言收紧：G4/G25 shadow case 已要求关键实体与极性标签同时出现，避免“只弹卡但漏 acceptable 专业”或“正向加意向被写成排除”继续被算作通过。G4 clean run 仍暴露严重性能长尾：单步 `elapsedMs=173176`，原因集中在 intent preview 工具内部耗时，后续必须进入 tool budget/latency decomposition，不应被功能通过掩盖。
- 2026-06-22 post-targeted full clean shadow R1：同样带 `--clear-history-per-case --clear-backend-pending-per-case --clear-backend-planning-intent-per-case` 重跑完整 G1-G32 e2e shadow 子集，报告 `/private/tmp/dialog_regression_320_g1_g32_clean_full_r1_metrics.json` 为 52 step、47 successful、5 content failure；runtime observation 21 条，sideEffect 分布为 `plan_preview=2`、`readonly=9`、`readonly_while_pending=4`、`intent_pending=5`、`multiple_pending=1`。diff `/private/tmp/runtime_shadow_diff_320_g1_g32_clean_full_r1.json` 为 32 total、21 observed、8 clean、3 blocking、10 major、11 info，`cleanRate=0.25`。这说明 targeted clean 只能证明局部补丁在小集合里成立，不能外推为 runtime 平均态已收敛。
- full clean R1 的 5 个硬失败：G4 漏掉“跨境电商也可以考虑”；G19 无正式方案引用“刚那个方案民办能少点不”仍误出 intent pending；G25 “加意向 A/B，排除 C/D”仍在本轮把 A/B 写成 negative；G27 “删完了再帮我看看...”没有先 apply active pending；G30 “清北复旦强基加进意向”同轮生成 plan mutation 与 intent change 两张 pending card。额外非断言问题：G7 focus 从中外合作/预算漂到泛化审查，G8 软偏好+排除升级成 plan mutation，G23 “城市优先长三角”误抽“城市管理”且把优先升级为 only_keep，G31 出现“文本让用户确认院校意向但无 pending/card”。
- full clean R1 的性能长尾：median `19411ms`、p95 `61532ms`、max `68847ms`；最慢集中在 G30 强基路径、G21 强基+普通批审查和 G12 学费替换分析。G30 第二轮出现 17 次工具调用、7 次模型请求；G30 第三轮同轮 7 次工具调用且双 pending。后续必须用 `EvidencePlan/toolBudget/batch query/replyPlan` 收敛自由工具循环，不能继续靠 service 后处理补桥。
- 2026-06-22 after G27 refresh fix full clean shadow：带同样 clean 参数重跑完整 G1-G32 e2e shadow 子集，报告 `/private/tmp/dialog_regression_320_g1_g32_after_g27_refresh_fix_metrics.json` 为 52 step、52 successful、0 content failure；runtime observation 21 条，sideEffect 分布为 `plan_preview=2`、`readonly=9`、`readonly_while_pending=4`、`intent_pending=6`，pendingType 为 `plan_mutation=2`、`none=9`、`unchanged_existing_pending=4`、`intent_change=6`。这说明 G4/G19/G25/G30 等断言层问题已收敛，但不能把断言全绿等同于协议收敛。
- after G27 refresh fix 的 diff `/private/tmp/runtime_shadow_diff_320_g1_g32_after_g27_refresh_fix.json` 仍为 32 total、21 observed、9 clean、0 blocking、12 major、11 info，`cleanRate=0.2812`。主要差异包括 `missing_workspace_refresh=6`、`presentation_mismatch=3`、`outputType_mismatch=3`、`sideEffect_mismatch=4`、`missing_post_apply_evidence_plan=1`。这说明 runtime 仍在旧 full-agent/tool observation 和 compiler contract 之间存在结构差异，3.2.0 不能只追 e2e 绿灯，必须继续按 `CompiledProposal/EvidencePlan/displayPayload/workspaceRefreshTargets` 硬切。
- after G27 refresh fix 的关键残留：G27 “两万以上且跟我意向不沾边的先删掉”仍不能形成结构化删除集合，后续“删完了再看”实际表现为 `readonly_while_pending`，diff 期望为 `apply_pending_then_readonly`，且缺 `postApplyEvidencePlan`；根因是费用阈值 + 意向贴合度这种复合选择器还没有进入 plan action DSL/action space。G2 “能怎么处理，别直接动”仍缺 conditional options presentation；G17 tier-local reorder 能出 pending，但缺 ordered workspace refresh；G21 strongbase 合理性查询不应刷新普通 review；G31 保底学校只读查询能回答且保持 pending，但缺 ordered workspace refresh；G32 no-plan 方案引用回复内容正确，但 sideEffect 仍未归一为 `needs_plan_first`。
- after G27 refresh fix 的性能长尾比 R1 更严重：median `16109ms`、p95 `97361ms`、max `144494ms`。6 条超过 60s：G17 `144494ms`、G2 `130564ms`、G21 第二步 `127891ms`、G1 `97361ms`、G7 `96413ms`、G21 第一步 `81865ms`。G17 的 agentRun 显示 3 次模型请求、3 次工具调用，首个模型请求 `62686ms`；G21 特殊路径仍有多轮模型/工具调用和重复检索风险。后续必须用 node benchmark、tool budget、batch query 和 replyPlan 限制自由工具循环，不能靠换模型或 service 后处理掩盖。
- 2026-06-22 focused G31/G32 修复验证：在当前代码服务 `8041` 上只跑 G31/G32 相关回归，报告 `/private/tmp/dialog_regression_320_g31_g32_after_needs_plan_observability_8041_metrics.json` 为 10 step、10 successful、0 failed；runtime shadow observation 为 2 条，`sideEffect={readonly_while_pending:1, needs_plan_first:1}`，`pendingType={unchanged_existing_pending:1, none:1}`。diff `/private/tmp/runtime_shadow_diff_320_g31_g32_after_needs_plan_observability_8041.json` 在 observed case 上 G31/G32 均 clean、0 blocking、0 major；其余 30 条是聚焦 run 未观测的 `missing_observation` info，不能按 `cleanRate=0.0625` 解读为全量质量。
- G31 最新定性：active pending 下的只读 ordered 查询现在能保持 pending unchanged，同时返回 `workspaceRefreshTargets=["ordered"]`，修复点是 pending readonly query 在拿到 `ordered_snapshot` 时必须显式发 `planningWorkspaceAction targetView=ordered`。这不是新 shadow 路径，只是把只读证据和 workspace contract 对齐。
- G32 最新定性：无正式方案下引用“当前/刚那个方案”的场景现在由 `needs_plan_first_guard` 在模型前归一为 `sideEffect=needs_plan_first`，不创建 intent pending、不写偏好、不调用模型。上一轮 G32 diff 的一部分来自 fixture 与 golden 不一致，另一部分来自 guard observability 未写入历史；现在已补齐 step fixture 和 route observability。
- 2026-06-22 after G31/G32 contract full clean shadow：在当前代码服务 `8042` 上重跑完整 G1-G32 e2e shadow 子集，报告 `/private/tmp/dialog_regression_320_g1_g32_after_g31_g32_contract_8042_metrics.json` 为 52 step、51 successful、1 content failure，唯一失败是 G27 最后一轮缺 `planningWorkspaceAction`；runtime observation 21 条，`sideEffect={plan_preview:2, readonly:7, readonly_while_pending:4, intent_pending:6, needs_plan_first:2}`，`pendingType={plan_mutation:2, none:9, unchanged_existing_pending:4, intent_change:6}`。diff `/private/tmp/runtime_shadow_diff_320_g1_g32_after_g31_g32_contract_8042.json` 为 32 total、21 observed、12 clean、0 blocking、9 major、11 info，`cleanRate=0.375`。相对 after G27 refresh fix，clean 从 9 提到 12，major 从 12 降到 9；G19/G21/G23/G25/G29/G30/G31/G32 均 clean。
- 这轮 full diff 进一步修正 G27 定性：问题不是“apply 后没有刷新”单点失败，而是前一轮“把两万以上且跟我意向不沾边的先删掉”仍只走 blocked `preview_fix_proposal`，没有形成可执行 `plan_mutation` pending；因此后一轮“删完了再看”只能被观测成 `readonly_while_pending`，缺 `postApplyEvidencePlan`、ordered refresh 和 apply 后证据。根因仍是复合 selector/action DSL 缺失，需要表达 `tuition >= 20000`、`preferenceFit=unrelated`、delete scope、capacity/shortage policy 和 post-apply evidence，而不是在 pending apply 分支继续补桥。
- 2026-06-22 focused G27 structured remove hard-cut：已把 `min_tuition_per_year`、`max_tuition_per_year`、`preference_fit` 纳入 `plan_next_action` filters，并让 `execute_plan_action(remove_units)` preview/apply 共用同一 selector；semantic `preview_fix_proposal` 快捷路由遇到明确删除当前方案范围时放回 full Agent，不从文本承诺补卡。验证报告 `/private/tmp/zhiyuan_320_g27_after_structured_remove_metrics.json` 为 4/4 successful；runtime shadow `/private/tmp/zhiyuan_320_g27_after_structured_remove_shadow.json` 观测到 `apply_pending_then_readonly=1`。第三轮链路为 `plan_next_action(remove_units preview) -> execute_plan_action(remove_units preview_only) -> pendingConfirmationCard`，第四轮为 `pending_plan_short_text_confirm -> remove_units apply -> postApplyEvidencePlan`，并刷新 `ordered/review`。这次修复不是 shadow/bridge，而是补齐 action DSL 和执行 selector。
- 2026-06-23 after G27 structured remove full clean shadow：在当前代码服务 `8037` 上重跑完整 G1-G32 e2e shadow 子集，报告 `/private/tmp/dialog_regression_320_g1_g32_after_g27_structured_remove_8037_metrics.json` 为 52 step、51 successful、1 content failure；唯一 runner 失败是 G26 “保底最后几个是什么学校 录取率多少”被错误解析成“专业:保”，回复没有命中“保底/学校/录取率/概率”。runtime observation 21 条，`sideEffect={plan_preview:2, readonly:7, readonly_while_pending:3, intent_pending:6, needs_plan_first:2, apply_pending_then_readonly:1}`，`pendingType={plan_mutation:2, none:10, unchanged_existing_pending:3, intent_change:6}`。规范化 diff `/private/tmp/runtime_shadow_diff_320_g1_g32_after_g27_structured_remove_8037.json` 为 32 total、21 observed、16 clean、0 blocking、5 major、11 info，`cleanRate=0.5`。相对 `8042` 轮次，clean 从 12 提到 16，major 从 9 降到 5；G27 已从 full diff major 中移除。
- 2026-06-23 focused G26 plan slice query 修复验证：新增无 pending、已有正式方案下的确定性 readonly plan slice route，把“保底最后几个是什么学校 录取率多少”编译为 `query_ordered`，filters 为 `tier=保 / slice=tail / limit=5 / include_fields=[school,major,admission_probability]`，由 handler 直接从 ordered plan 格式化末尾条目和录取率。focused e2e 报告 `/private/tmp/dialog_regression_320_g26_after_plan_slice_fix_metrics.json` 为 1/1 successful，耗时 `2583ms`，`routingPath=direct_readonly_plan_slice_query`，`toolCallCount=1`，不调用模型、不创建 pending，并刷新 `ordered`。这次修复是 PlanQuery DSL 的最小落地，不是 service 文本修补或 shadow bridge。
- 截至 `/private/tmp/runtime_shadow_diff_320_g1_g32_after_g27_structured_remove_8037.json` 的 5 个 major：G3/G31 为 runtime 已刷新 ordered 但 golden 未要求，需要把 `readonly_while_pending` 的 workspace contract 期望升级或明确为可选；G12 仍未形成 latency diagnostic profile，且额外刷新 review；G16 unsupported pin/lock 被误走 `move_ordered_unit` no-change，缺 `unsupportedAction=pin_or_lock_unit` 或可执行 pin/lock DSL；G27 当时仅剩 profile/golden 刷新集合未表达 `ordered/review`，业务链路已闭环。内容层的 G26 plan projection/slice query 已做 focused 修复，下一轮全量需要确认 content failure 消失。
- 2026-06-23 focused G27 current-code 复核：旧端口 `8000` 仍跑 stale agent，导致一度把已修代码误判为 runtime 失败；在当前代码服务 `8039` 上用 `sessionId=9903235`、`cloneBackendStateFromSessionId=35` 重跑 G27，报告 `/private/tmp/dialog_regression_320_g27_clone_current_agent_metrics.json` 为 4/4 successful，runtime shadow `/private/tmp/runtime_shadow_320_g27_clone_current_agent.json` 观测到 `apply_pending_then_readonly=1`，最后一轮返回 `planningWorkspaceAction` 的 `ordered` 与 `review` 两个 followup。profile 已新增 `expectedPending.workspaceRefreshTargets=["ordered","review"]`，保持 `targetView="ordered"` 作为主面板；重新生成 diff `/private/tmp/runtime_shadow_diff_320_g27_clone_after_profile_fix.json` 后，G27 为 `maxSeverity=none`，剩余 31 条仅因 focused run 未观测而记 `missing_observation` info。后续全量必须使用 fresh current-code agent，不再用 stale `8000` 结果定性；`session 35` 已被历史运行污染，破坏性 case 必须通过 clone session 跑。当前 clone 仍有 MySQL chat session row 权限警告（`root@localhost using password: NO`），但 extra-data 和 volunteer files clone 已足够支撑该 G27 case；若后续 case 依赖 chat row，应补 `ZHIYUAN_REGRESSION_DB_PASSWORD`/`MYSQL_PWD` 后再跑。
- 本轮仍需跟进的结构性问题：G22/G31 中用户明确“基于620湖北物化生重来”后的语义/编译边界已收口到 `profileScenario/proposedProfile`，但还没有进入可执行 profile update/replan 状态机，旧方案仍只能作为未重算状态保留；G17 tier-local reorder 能出 pending，但工具链为 `plan_next_action -> execute_plan_action -> query_volunteer_plan -> plan_next_action -> execute_plan_action`，耗时 `23451ms`，说明 tier-local selector 和 ordered refresh 仍未由单一 EvidencePlan/Compiler 产出；G29 卡片文案仍压扁“优先/也可以考虑”，需要确认 pending payload 是否保留 `preferenceStrength.primary/acceptable`，不能只看用户可见 summary。
- 性能本轮有改善但仍有长尾：median `13100ms`、p95 `28116ms`、max `31959ms`；最慢为 G7 focused review `31959ms`、G26 slice query `30956ms`、G27 structured remove preview `29194ms`、G30 strongbase/basic science analysis `28116ms`、G17 tier-local reorder `23451ms`。G26/G17/G30 继续证明 3.2.0 需要 EvidencePlan、tool budget、batch query 和 replyPlan 限制自由工具循环。
- 2026-06-23 fresh current-code full shadow：在新起服务 `8044` 上重跑完整 G1-G32 e2e shadow 子集，报告 `/private/tmp/dialog_regression_320_g1_g32_fresh_8044_metrics.json` 为 52 step、52 successful、0 failed；runtime shadow `/private/tmp/runtime_shadow_320_g1_g32_fresh_8044.json` 观测 21 条，`sideEffect={plan_preview:2, readonly:7, readonly_while_pending:4, intent_pending:6, needs_plan_first:2}`，`pendingType={plan_mutation:2, none:9, unchanged_existing_pending:4, intent_change:6}`。原始 diff `/private/tmp/runtime_shadow_diff_320_g1_g32_fresh_8044.json` 为 32 total、21 observed、13 clean、0 blocking、8 major、11 info。G26 在 fresh 端口已走 `direct_readonly_plan_slice_query`，耗时 `2651ms`，内容命中保档末尾学校和录取率，说明 8037/8039 上的 G26 误判已收敛。
- 2026-06-23 G3 profile 口径修正：`readonly_while_pending` 读取 ordered plan 后刷新 `ordered` 和 G31 的 contract 一致，因此 G3 `expectedPending` 新增 `workspaceRefreshTargets=["ordered"]`，`targetView` 仍保持 `null`。compiler report `/private/tmp/proposal_compiler_320_after_g3_refresh_targets.json` 为 32/32 通过；用同一份 8044 observation 重算 diff `/private/tmp/runtime_shadow_diff_320_g1_g32_fresh_8044_after_g3_profile.json` 后为 32 total、21 observed、14 clean、0 blocking、7 major、11 info，`cleanRate=0.4375`。这次变更是 profile/golden 合理化，不是 runtime shadow bridge。
- 2026-06-23 8044 fresh 后剩余 7 个 major：G1 plan mutation pending/card 已有但缺 `ordered` workspace refresh；G2 费用/中外合作“先看看怎么处理”仍降为 readonly answer，缺 conditional options 和 review refresh；G7 focused review 实际调用 `review_plan` 但未发 review refresh；G12 latency diagnostic profile 仍只是普通 readonly review，没有诊断 output/presentation；G16 pin/lock 局部动作误走 `move_ordered_unit` error，缺 `unsupportedAction=pin_or_lock_unit` 或真实 pin/lock DSL；G17 tier-local reorder 能出 pending，但工具链仍为 6 次工具/模型混合且缺 ordered refresh；G27 apply+readonly 在全量 fresh 中仍未稳定，最后一轮被观测成 `readonly_while_pending`，缺 apply、postApplyEvidencePlan 和 ordered/review 双刷新。
- G27 最新定性需要比 focused clean 更保守：`/private/tmp/dialog_regression_320_g27_clone_current_agent_metrics.json` 证明执行链在形成 `remove_units` pending 后可以 `pending_plan_short_text_confirm -> remove_units apply -> postApplyEvidencePlan -> ordered/review refresh`；但 8044 full 中第三轮“把两万以上且跟我意向不沾边的先删掉”走成 `remove_units/no_change`，没有 pending，第四轮只能 `query_state`。同一轮还出现回复把 `19800` 元列入“两万以上”的阈值解释错误。根因是复合 selector 仍未稳定归一到 evidence/action DSL：需要由同一 EvidencePlan 明确 `tuition >= 20000`、`preferenceFit=unrelated`、是否存在已确认意向/待确认意向、删除粒度、capacity/no-result policy 和 post-apply readback，不能只依赖 full Agent 文本和局部 handler。
- 8044 性能基线：median `12838ms`、p95 `25055ms`、max `30706ms`，比 8037 的 G26/G17/G30 长尾改善，但仍有 5 个高耗时点：G32 初始兴趣分析 `30706ms`、G7 focused review `28731ms`、G12 latency profile `28072ms`、G21 强基基础学科分析 `25055ms`、G27 学费处理入口 `24090ms`。长尾集中在多轮模型分析、review/reply 生成和复合计划动作入口，继续支持 3.2.0 用 EvidencePlan、tool budget、batch query 和 replyPlan 限制自由工具循环。
- 2026-06-23 workspace refresh 小修：`review_plan/review_result` 即使来自显式“先别动/别直接动”的只读提示，也保留 `review` refresh；成功的 mutation `preview_only` 允许透传工具返回的 workspace refresh targets，用于确认卡旁边打开 ordered/review 证据面板，error 仍不发 refresh。单测新增 `test_execute_plan_action_preview_can_refresh_workspace_for_confirmation_context` 和 `test_current_turn_explicit_readonly_review_preserves_review_workspace_refresh`，相关 workspace/profile/shadow 单测 42 通过。
- 2026-06-23 focused G1/G7/G17 验证：在当前代码服务 `8045` 跑 `/private/tmp/dialog_regression_320_g1_g7_g17_cases.json`，报告 `/private/tmp/dialog_regression_320_g1_g7_g17_after_workspace_refresh_8045_metrics.json` 为 3 step、2 successful、1 performance failure；runtime shadow `/private/tmp/runtime_shadow_320_g1_g7_g17_after_workspace_refresh_8045.json`，diff `/private/tmp/runtime_shadow_diff_320_g1_g7_g17_after_workspace_refresh_8045.json`。G7 已 clean，观测为 `readonly/readonly_answer` 且 `workspaceRefreshTargets=["review"]`；G1 仍为 major，原因是模型走 `preview_current_major_intent_confirmation` 产出 user-goal fix pending，缺 `ordered` refresh，根因仍是 intent+plan 混合 TurnDecision/Compiler 没硬切；G17 这轮变成 blocking，180s 后返回超时边界，未形成 pending，说明 tier-local reorder 不能继续依赖 full Agent 自由工具循环，必须接 `planActionDsl`/deterministic route。
- 2026-06-24 回归端口规则更新：本机已有长期测试环境占用 `3001/8080/18090/18091/18092/8091/5000` 等端口，3.2.0 本地调试不再复用这些端口，也不再把 `8000` 作为默认 fresh agent。后续统一使用隔离端口：Backend `18290`、Agent `18291`、Rank `18292`、Web `3201`。`dialog_regression_runner.py` 和 `dialog_auto_explorer.py` 的默认 Agent/Backend 已切换到 `18291/18290`，并保留 `ZHIYUAN_REGRESSION_AGENT_URL`、`AGENT_DIALOG_E2E_URL`、`ZHIYUAN_REGRESSION_BACKEND_URL`、`INTERNAL_SERVICE_URL` 覆盖。Agent 启动环境中的 `INTERNAL_SERVICE_URL` 必须与 runner 的 `--internal-service-url` 指向同一个 Backend；否则 runner 可以 clone/clear 成功，但 Agent 内部仍会读到空方案，产生伪业务失败。
- 2026-06-23 G17 runtime hard-cut 重做：删除 G17 专用 `_tier_local_reorder_plan_payload` / `_maybe_handle_direct_tier_local_reorder_plan_action` 形态，改为通用 `direct_local_plan_action`。runtime 只调用 `LocalPlanActionDslDecision` 模型节点抽取结构化 DSL，再交给 `proposal_compiler.compile_runtime_local_plan_action_source` 校验闭集字段并生成 `execute_plan_action(move_ordered_unit)` preview；执行层按 `planActionDsl.selector/targetPosition` 处理档内局部移动。当前支持 `admissionRatio/schoolRank/finalScore`、`highest/lowest/best/worst`、档内序位和档内首尾；不支持的 lock/pin 只允许作为 `unsupportedAction=pin_or_lock_unit` 进入能力评估或后续 DSL 设计，runtime 不靠字符串硬接。
- 2026-06-23 关于字符串匹配的定性：用户表达存在大量同义、指代、省略和反讽式边界，不能在 `service.py` 按“录取率/推荐系数/最高/第一位”这类中文片段抽结构。3.2.0 的边界是：模型节点负责理解自然语言并产出 DSL；compiler/runtime 只做闭集枚举归一、必填字段校验、版本 guard、执行前证据检查和 pending/workspace contract。允许存在 `稳 -> 稳档`、`final_score -> finalScore` 这种模型输出别名归一，但不得从用户原话重新推断业务语义；这类规则若扩大为 raw text parser，就会回到 3.1.x 多路径、易误判、不可 profile 的老问题。
- 2026-06-23 local action 模型节点 profile 扩充：`model_node_benchmark_320_cases.json` 中 `local_plan_action_dsl` 从 G17 单一表达扩展为 6 条，覆盖录取率最高到保底第一、推荐系数最高到稳档第一、录取率最低到保底最后、同义表达“最有把握/最前面”、院校层次“学校档次最好/冲档第二个”和 lock/pin 负例。离线 benchmark `/private/tmp/model_node_320_local_plan_dsl_paraphrase_offline.json` 为 6/6；live-node 曾记录一次失败 `/private/tmp/model_node_320_live_local_plan_action_dsl_r1.json` 为 2/3，问题是“推荐系数”误映射成 `admissionRatio`，prompt/schema 修正后 `/private/tmp/model_node_320_live_local_plan_action_dsl_after_prompt_r1.json` 为 3/3，median `3350ms`、p95/max `5853ms`。扩展 paraphrase 后 live-node `/private/tmp/model_node_320_live_local_plan_action_dsl_paraphrase_r1.json` 为 6/6，median `3730ms`、p95/max `5237ms`。后续所有新增 local action 不能只加 e2e case，必须先补 node profile。
- 2026-06-23 direct local action current-code 验证：G17 focused 报告 `/private/tmp/dialog_regression_320_g17_local_dsl_8000_metrics.json`，shadow `/private/tmp/runtime_shadow_320_g17_local_dsl_8000.json`，diff `/private/tmp/runtime_shadow_diff_320_g17_local_dsl_8000.json`。结果为 `routingPath=direct_local_plan_action`、`route=local_plan_action`、模型 DSL confidence `0.95`、1 次 execute tool、生成 ordered refresh + pending card，耗时约 `5.5s`。G1/G7/G17 focused 报告 `/private/tmp/dialog_regression_320_g1_g7_g17_local_dsl_8000_metrics.json` 和 diff `/private/tmp/runtime_shadow_diff_320_g1_g7_g17_local_dsl_8000.json` 为 3/3 clean；G1 仍走 full_agent 链，不代表已 hard-cut，G7 clean 但回复焦点仍偏泛化，需 reply focus profile。
- 2026-06-23 fresh 8000 复核：重启 current-code agent 后跑 `/private/tmp/dialog_regression_320_g1_g7_g17_cases.json`，报告 `/private/tmp/dialog_regression_320_g1_g7_g17_local_dsl_paraphrase_8000_metrics.json` 为 3/3 successful；shadow `/private/tmp/runtime_shadow_320_g1_g7_g17_local_dsl_paraphrase_8000.json`，diff `/private/tmp/runtime_shadow_diff_320_g1_g7_g17_local_dsl_paraphrase_8000.json` 为 3 observed、3 clean、0 blocking、0 major。G17 耗时 `6049ms`，`routingPath=direct_local_plan_action`，1 次 `execute_plan_action(move_ordered_unit)`，输出 ordered refresh + pending card；G1/G7 仍是 full_agent，G7 耗时 `37491ms` 且回复焦点偏泛化，继续归入 reply focus/tool budget 后续问题。
- 2026-06-23 G1-G32 current-code full run：报告 `/private/tmp/dialog_regression_320_g1_g32_local_dsl_8000_metrics.json` 为 52 step、51 successful、1 content failure；runtime shadow `/private/tmp/runtime_shadow_320_g1_g32_local_dsl_8000.json`，diff `/private/tmp/runtime_shadow_diff_320_g1_g32_local_dsl_8000.json` 为 32 total、21 observed、16 clean、0 blocking、5 major、11 info，cleanRate `0.5`。唯一 runner 内容失败是 G32 “有什么专业是比较好就业的吗 最好工资高点”遇到 provider interruption fallback，回复未命中“就业/专业”。G17 在 full run 已 clean，耗时约 `6241ms`。
- 2026-06-23 full run 剩余 5 个 major：G2 费用/中外合作“能怎么处理，别直接动”仍只有 readonly answer，缺 conditional options + review refresh；G12 latency diagnostic 仍降为普通 readonly/review，没有诊断输出协议；G16 pin/lock unsupported/local action 边界未落，不能误走移动 no-change，需要进入 unsupportedAction 或真实 pin/lock DSL；G21 强基基础学科查询不应刷新普通 review，且工具/模型循环过长；G27 在 full run 中 composite selector + active pending apply/readback 仍不稳定，缺 `apply_pending_then_readonly`、`postApplyEvidencePlan` 和 ordered/review 双刷新。额外观察：G22 “基于620湖北物化生重来”需要继续从当前结构化 `ProfileChangeReplan` 状态推进到可确认资料更新、候选重算和方案重生成；G30/G32 provider interruption 需要在 benchmark/report 里和模型能力错误区分。
- 2026-06-23 G16 unsupported local action 收口：`LocalPlanActionDslDecision` 高置信输出 `actionFamily=none, unsupportedAction=pin_or_lock_unit` 时，runtime 直接走 `direct_local_plan_action_unsupported`，返回锁定/固定当前方案位置暂不可执行的边界说明，刷新 `ordered`，不创建 pending、不调用 `execute_plan_action`、不落 full agent。runner 的 runtime shadow 映射同步读取 routeDecision，保留 `plan_preview_or_clarification / plan_mutation_or_unsupported / conditional_options`，避免把“无卡 unsupported”误归成 readonly。focused 报告 `/private/tmp/dialog_regression_320_g16_pin_lock_unsupported_8000_metrics.json` 为 1/1 successful，耗时 `6486ms`；shadow `/private/tmp/runtime_shadow_320_g16_pin_lock_unsupported_8000.json`，diff `/private/tmp/runtime_shadow_diff_320_g16_pin_lock_unsupported_8000.json` 为 1 observed、1 clean、0 blocking、0 major。注意这不是实现锁定能力，只是把 unsupported action boundary 从自由工具链中硬切出来。
- 2026-06-23 after G16 unsupported full clean shadow：在 fresh current-code `8000` 上重跑完整 G1-G32 e2e shadow，报告 `/private/tmp/dialog_regression_320_g1_g32_after_g16_unsupported_8000_metrics.json` 为 52 step、52 successful、0 failed；runtime shadow `/private/tmp/runtime_shadow_320_g1_g32_after_g16_unsupported_8000.json`，diff `/private/tmp/runtime_shadow_diff_320_g1_g32_after_g16_unsupported_8000.json` 为 32 total、21 observed、16 clean、0 blocking、5 major、11 info，cleanRate `0.5`。sideEffect 分布为 `plan_preview=2`、`readonly=7`、`readonly_while_pending=4`、`intent_pending=6`、`plan_preview_or_clarification=1`、`needs_plan_first=1`；runner 性能为 median `18423ms`、p95 `39572ms`、max `47286ms`，最慢集中在 G2 费用/中外合作处理、G22/G31 profile change replan、G7 focused review 和 G21 strongbase。
- 本轮 5 个 major 的更准确口径：G1 已有 `plan_mutation` confirmation card，但缺 `ordered` workspace refresh，属于 pending sink/display contract 缺口，不是“无卡”；G2 已刷新 review 且文本提到处理方向，但 presentation 仍是 `readonly_answer`，缺 `conditional_options` 结构；G12 仍被当成普通 plan review/preview，未形成 `latency_profile/diagnostic` 输出；G19 的 e2e step 实际先创建了 `generate_plan` pending，再问“刚那个方案民办能少点不”，因此根因不是简单 no-plan，而是 pending preview reference 不能当正式方案、也不能只泛化成 pending impact，需要 `pending_plan_preview_reference/no_formal_plan` 边界；G27 仍是复合 selector/action DSL 不稳定，费用阈值 + 意向不相关删除未稳定形成 `remove_units` pending，后续 readback 只能走 readonly。
- 本轮 clean 的关键正向结论：G16 不再误走 `move_ordered_unit/no_change`，已落入 `direct_local_plan_action_unsupported`；G17 保持 `direct_local_plan_action`，1 次 `execute_plan_action(move_ordered_unit)` 形成 ordered refresh + pending；G25 混合正负极性、G23 地域维度、G26 保底 slice query、G31 pending 下只读 ordered query、G32 no-plan 当前方案引用防御均未出 major。G29 还需单独检查 pending payload 是否保留 `primary/acceptable`，因为可见 summary 仍把“优先/也可以考虑”压扁成并列偏好。
- 下一步优先级：先处理不依赖 raw text parser 的协议收敛项：1) pending sink 根据 compiled/display/evidence contract 透传 workspace refresh，先覆盖 G1；2) 给 `pending generate_plan preview` 与 `no formal plan` 的引用解析补结构化 sideEffect，修正 G19 的真实边界；3) G2/G12 进入 replyPlan/displayPayload 层，不在 service 后处理字符串；4) G27 继续补 action DSL 的 selector evidence、capacity/no-result policy 和 post-apply readback，不能再靠 full-agent 文本承诺。
- 2026-06-23 G1 pending sink refresh 修复：`compile_user_goal_fix_proposal` 显式输出 `workspaceRefreshTargets=["ordered"]`，`compile_review_fix_proposal` 保持 `["review"]`；service 的 compiled pending result 统一携带 refresh targets，并在 full-agent/semantic plan route 组装 followups 前合并，不从用户原话或模型回复中推断。focused G1 报告 `/private/tmp/dialog_regression_320_g1_after_compiled_refresh2_8000_metrics.json` 为 1/1 successful，followups 为 `planningWorkspaceAction(ordered)` + `pendingConfirmationCard(plan_mutation)`；diff `/private/tmp/runtime_shadow_diff_320_g1_after_compiled_refresh2_8000.json` 为 1 observed、1 clean、0 blocking、0 major。相关单测：`test_proposal_compiler_runtime_selection.py` 62 通过，`test_dialog_regression_runner.py` 64 通过，`test_chat_service_history_persistence.py` 相关子集 62 通过。
- 2026-06-23 G21 no-formal-plan special path boundary 修复：补齐 `proposal_compiler.resolve_no_formal_plan_review_boundary`，在无正式方案且用户问“这版强基+普通批方案合理不”这类特殊路径方案审查时，runtime 在 full agent 前返回 readonly 边界，`replyFocus=["strongbase","regular_batch"]`，不触发 `generate_plan`、不创建 pending、不刷新普通 `review/ordered`。这属于 TurnDecision/状态权威 guard，不是回复模板补丁；service active/no-active pending 两条入口复用同一 compiler resolver。验证：`test_proposal_compiler_runtime_selection.py` 63 通过，`test_chat_service_history_persistence.py -k "no_formal_plan or strongbase or needs_plan_first or runtime_intent_hard_cut"` 8 通过，`test_runtime_hard_cut_audit.py` 2 通过，`proposal_compiler_golden.py` G1-G32 32/32。
- 2026-06-23 G2 conditional options contract 修复：`semantic_plan_action` 在 `analyze_adjustment/preview_fix_proposal` 返回修复建议选项但本轮不创建 pending 时，将 `displayPayload.presentation="conditional_options"` 写入 routeDecision。该路径不生成待确认卡、不 apply，也不从中文回复推断 followup。早期验证曾为该只读 evidence 追加 silent `planningWorkspaceAction(review)`；2026-06-24 live G1-G32 回归后收敛为只读 evidence 不触发 workspace refresh，避免用户看到“已刷新审查/排序”这类误导动作。真实 mutation apply、确认卡相关 preview 和 post-apply evidence 仍按结构化 `workspaceRefreshTargets` 刷新。
- 2026-06-23 G12 latency profile observability contract 修复：`dialog_regression_runner.py` 支持显式 `runtimeObservationProfile={"type":"latency_profile"}`，只在 profile/shadow case 标注时把真实 WebSocket 回归中的 `elapsedMs/firstMessageMs/finalMessageMs/toolCallCount/toolDurationMs/llmDurationMs/agentRun.nodeTimings` 汇总为 `runtime.outputType="latency_profile"`、`displayPayload.presentation="diagnostic"` 和 `diagnosticPayload`。正式对话不因为“高收费能不能换便宜”这类业务话术暴露内部耗时诊断，也不创建 pending、不 apply；G12 的用户可见回复仍回答费用和替换边界，诊断只进入 regression shadow/diff 协议。`dialog_regression_320_g1_g32_shadow_cases.json` 已给 G12 标注该 profile，新增单测固定 diagnostic observation 与 compiler `latency_profile` 对齐。focused G12 e2e `/private/tmp/dialog_regression_320_g12_latency_profile_8000_metrics.json` 为 1/1 successful，shadow `/private/tmp/runtime_shadow_320_g12_latency_profile_8000.json`，diff `/private/tmp/runtime_shadow_diff_320_g12_latency_profile_8000.json` 为 1 observed、1 clean、0 blocking、0 major；未观测的其它 31 个 case 仅保留 `missing_observation` info。
- 2026-06-23 after G1 compiled refresh full clean shadow：在 fresh current-code `8000` 上重跑完整 G1-G32 e2e shadow，报告 `/private/tmp/dialog_regression_320_g1_g32_after_g1_compiled_refresh_8000_metrics.json` 为 52 step、52 successful、0 failed；runtime shadow `/private/tmp/runtime_shadow_320_g1_g32_after_g1_compiled_refresh_8000.json`，diff `/private/tmp/runtime_shadow_diff_320_g1_g32_after_g1_compiled_refresh_8000.json` 为 32 total、21 observed、17 clean、0 blocking、4 major、11 info，cleanRate `0.5312`。相对 G16 unsupported 后 full run，G1 已 clean；sideEffect 分布为 `plan_preview=2`、`readonly=6`、`readonly_while_pending=4`、`intent_pending=6`、`plan_preview_or_clarification=1`、`needs_plan_first=2`；性能 median `18657ms`、p95 `40486ms`、max `56667ms`。
- after G1 compiled refresh 复跑时的 4 个 major 定性：G2 “能怎么处理，别直接动”被判为 `analyze_adjustment/readonly_answer`，缺 `conditional_options` presentation 和 `review` refresh，根因是费用/中外合作处理还没有进入 replyPlan/displayPayload 的条件选项协议；G12 仍是普通 review 回答，未形成 `latency_profile/diagnostic`，说明性能诊断需要独立 profile/evidence，而不是复用 plan review；G21 “现在这版强基+普通批方案合理不”在无正式普通批方案时触发 `generate_plan` preview/error 并刷新 `ordered`，违背只读 review 边界，根因是 special path 合理性查询和正式方案审查未区分；G27 “删完了再帮我看看...”没有先 apply active pending，仍是 `readonly_while_pending`，根因是复合 selector/action DSL 与 active pending apply/readback 仍未稳定闭环。G21 已由上一条 no-formal-plan special path boundary guard 处理，待下一轮 full shadow 用 fresh current-code agent 复核。
- 本轮正向收敛点：G1 ordered refresh + plan mutation card 已在全量 clean；G16 unsupported pin/lock、G17 direct local reorder、G23 地域实体、G25 正负极性、G26 保底 slice query、G31 pending 下只读 ordered query、G32 no-plan 当前方案防御均未出 major。G22/G31 的 profile-change replan 仍只是防误改话术，没有生成可确认的资料变更/重规划提议，暂未被本轮 golden 计为 major，但应进入后续 3.2.0 动作空间补齐；G29 已定位为 display gap，pending payload 保留 `preferenceStrength.primary/acceptable`，当前展示摘要已改为消费结构化 strength。
- 2026-06-23 PlanQuery runtime compiler 增量后继续收口：只读查询意图从 service 层分支上移到 `TurnDecision -> plan_query_profile_tool`，再由 [proposal_compiler.py](../zhiyuan-agent/app/domain/proposal_compiler.py) 的 `compile_runtime_plan_query_profile_source` 校验结构化 profile 并输出 `PlanQuery` DSL。`TurnDecision` 必须先判定为 `taskLayer=plan`、`scopeAnchor=current_plan`、`sideEffect=readonly/readonly_while_pending`、`scenario=plan_query/plan_query_while_pending`，才能调用 query profile；方案调整、修复预览、profile change/replan 和长期意向更新不得进入 query profile。service 只消费 `matched/plan_payload/planQueryDsl`，不再按单句学费查询或保底切片做本地字符串分支；旧 `compile_runtime_plan_query_source(content=...)` 只保留为过渡/单测兼容入口，不作为 runtime 主路径。G26 “保底最后几个是什么学校 录取率多少” 的 profile 为 `readonly_plan_slice_query`，filters 为 `tier=保, slice=tail, limit=5, include_fields=[school, major, admission_probability]`，观测仍保留 `routingPath=direct_readonly_plan_slice_query`。G27 “两万以上的都算贵 帮我看看有几个” 的 profile 为 `readonly_plan_query`，dimensions 为 `["tuition"]`，filters 为 `min_tuition_per_year=20000`，走 `query_ordered` 只读 count/examples，不创建 pending、不触发 pending impact。pending 下“相关专业/相关学校”只读查询使用 `readonly_pending_reference_query`，实体从 active pending 的结构化 `selectedData/entityProfile` 读取。
- 费用相关两条路径已明确拆开：只读查询是 `TurnDecision(readonly plan_query) -> PlanQueryProfile -> PlanQuery -> query_ordered(current_plan filters/projection)`；方案变更仍是 `tuition range + preference_fit -> remove_units/replace_units preview`，由 action DSL 和执行层 selector 解析 volunteerIds。二者互斥，query profile 对删除、替换、移动、调整等 mutation intent 输出 `none`，compiler 拒绝 `none/mutation` profile，避免“问几个”被做成确认卡，也避免“先删掉”被降级成只读回答。验证基线需同步增加 `turn_side_effect + plan_query_profile` model-node case，覆盖学费阈值、tier tail slice 和 pending reference。
- 2026-06-23 PlanQuery gate 复核：G26 “保底最后几个是什么学校 录取率多少”曾因 TurnDecision 将 `pendingExists=false` 错判成 while-pending 而落入 `semantic_plan_action/query_state`。已在 `turn_decision_tool` 用结构化 `planningStateProfile.pendingExists` 做状态一致性归一，runtime 不再被错误拦在 PlanQueryProfile 前。focused `/private/tmp/zhiyuan_320_plan_query_gate_metrics_after_fix.json` 为 5/5 successful：G26 为 `direct_readonly_plan_slice_query`，G27 费用阈值查询为 `direct_readonly_plan_query`，删除预览形成 `remove_units` pending，后续“删完再看”走 `apply_pending_then_readonly`。
- 2026-06-23 full-agent preview 边界补强：当本轮出现不可执行 mutation preview，随后又出现只读查询覆盖回复，且最终没有 pending card 时，service 基于工具结构化结果应用 `non_actionable_plan_preview_boundary` 并清掉 workspace refresh/view；单一 preview-only 的缺候选、缺范围、复合目标澄清仍保留各自更具体边界。这是为了防止“无卡 preview + 方案概览”混合输出，不新增字符串 recovery。
- 2026-06-23 after PlanQuery gate full clean shadow：fresh current-code `8000` 上完整 G1-G32 回归 `/private/tmp/zhiyuan_320_g1_g32_after_plan_query_gate_metrics.json` 为 52 step、52 successful、0 failed；shadow diff `/private/tmp/zhiyuan_320_g1_g32_after_plan_query_gate_diff.json` 为 32 total、21 observed、21 clean、0 blocking、0 major、11 info，cleanRate `0.6562`。性能仍有长尾：median `19785ms`、p95 `36553ms`、max `88926ms`，最慢为 G7 中外合作/预算只读审查。
- 暂缓 Java 查询下推：Java 侧当前没有 ordered-plan query endpoint，候选池 query DTO 也没有完整覆盖 tuition/preference-fit。后续单列任务定义 `PlanQueryCondition`，字段与 Java `CandidatePoolQueryReq.Filters` 对齐并补齐 ordered scope、tuition range、preference-fit；在 Java 具备执行能力前，不在 Python service 中扩一套完整筛选查询实现。
- 2026-06-23 profile-change replan 语义契约收口：`plan_semantic_action` 新增并固定 `profileScenario=none/adhoc_scenario/current_student_update/ambiguous` 与 `proposedProfile`；`proposal_compiler.compile_profile_change_replan_source` 只消费这些结构化字段，不再从 prompt 原文推断“基于/重新/临时/帮别人”等语义。`current_student_update` 编译为 `ProfileChangeReplan`，保留旧方案但标记“未按新资料重算”；`adhoc_scenario` 编译为 `ProfileReplanAdhoc`，不更新 profile、不让当前方案失效；`ambiguous` 编译为 `ProfileReplanAmbiguous`，只要求澄清范围。状态追问已上移到 TurnDecision `profile_change_state_query` 主路径，compiler 结合历史 `ProfileChangeReplan` DSL 回答当前正式方案尚未按新 profile 重算；旧 `plan_semantic_action.replyFocus=["profile_change_state_query"]` 仅作为过渡 fallback。验证：`py_compile app/domain/proposal_compiler.py app/service.py app/tools/plan_semantic_action_tool.py app/domain/region_entity_resolver.py` 通过；`test_proposal_compiler_runtime_selection.py` 72 通过；`test_plan_semantic_action_tool.py` 7 通过；`test_chat_service_history_persistence.py -k "profile_change_replan or profile_replan_adhoc or profile_change_state_query"` 5 通过。后续仍需补一等可执行 profile update/replan 状态机，不能退回 service 字符串匹配。
- 2026-06-23 profile-change focused e2e 复核：重启 fresh current-code `8000` 后跑 `/private/tmp/zhiyuan_320_profile_replan_focus_cases.json`，报告 `/private/tmp/zhiyuan_320_profile_replan_focus_after_prompt_metrics.json` 为 12/12 successful；runtime shadow `/private/tmp/zhiyuan_320_profile_replan_focus_after_prompt_shadow.json` 观测 G22/G31 均为 `readonly_while_pending + unchanged_existing_pending`。G22/G31 的“那基于620湖北物化生重来”均走 `semantic_profile_change_replan`，`ProfileChangeReplan.proposedProfileSummary=620分、湖北、物化生`，`missingProfileFields=[]`；后续“现在方案是按620湖北算的吧”走 `profile_change_replan_state_query`，明确当前正式方案仍按旧 profile 保留，且提示华中科技大学 pending 未采纳。剩余设计缺口：省份/分数单字段纠错轮仍可能被 full-agent 泛咨询吸走，说明 profile update/replan 不应长期寄存在 `plan_semantic_action` 里；3.2.0 后续应把 `profile_update/profile_replan/profile_state_query` 纳入 TurnDecision 或独立 profile node，service 继续只消费结构化枚举和 `proposedProfile`，不得回退到原文字符串匹配。
- 2026-06-23 G29 preference strength display gap 修复：`intent_entity_profile` 输出与 pending `selectedData.entityProfile` 已保留 `preferenceStrength.primary/acceptable`，问题在 `displaySummary` 过去由扁平 `major_intents` 汇总，压成普通“偏好专业”。当前 service 展示层新增结构化 strength summary，按 `primary/preferred/acceptable/must_have/only_keep/exclude_*` 生成卡片和主回复摘要；例如 `网络与新媒体优先，跨境电商也可以考虑` 展示为 `优先专业：网络与新媒体；可以考虑专业：跨境电子商务`。该逻辑只消费 profile schema 和专业规范化结果，不从用户原文匹配强度词，执行 payload 与后端 apply 格式不变。
- G29 focused WS 复核：`/private/tmp/zhiyuan_320_g29_strength_display_metrics.json` 为 1/1 successful，runtime shadow `/private/tmp/zhiyuan_320_g29_strength_display_shadow.json` 观测 `intent_pending + intent_change`。用户可见回复为 `已列出这次报考想法预览：优先专业：网络与新媒体；可以考虑专业：跨境电子商务。`，pending card `summary/content` 同样保留强度分层；pending `executionPayload.selectedData.entityProfile.preferenceStrength` 保留 `primary=["网络与新媒体"]`、`acceptable=["跨境电子商务"]`。本轮验证后已停止 8000/8080/5001 服务。
- 2026-06-23 profile replan 主路径前移：`current_student_update / adhoc_scenario / ambiguous` 三类资料重规划现在都先走 `TurnDecision -> proposal_compiler.compile_profile_change_replan_source`，并且在 `PlanQueryProfile`、local action 和 `plan_semantic_action` 之前截获。`adhoc_scenario` 返回 `turn_decision_profile_replan_adhoc`，只说明临时测算边界，不写 profile、不使旧方案失效；`ambiguous` 返回 `turn_decision_profile_replan_ambiguous`，只澄清“临时测算还是更新当前学生资料”。旧 `semantic_profile_*` 只作为 TurnDecision 未命中时的兼容兜底。新增 model-node case 覆盖 adhoc/ambiguous 后，离线 `/private/tmp/model_node_320_after_profile_replan_scope.json` 为 44/44 通过，`turn_side_effect=15/15`；service profile-change 子集为 6 通过。
- 2026-06-23 review/repair structured reroute 与 action confirm 回归补充：G1-G32 两轮 review/repair reroute 回归分别为 52 step、51 successful、1 style failure，以及 52 step、51 successful、1 performance failure；两轮 shadow 均为 21 observed、21 clean、0 blocking/major/minor。历史报告文件名仍带 `review_repair_bridge`，但运行时观测已统一改为 `structured_plan_reroute` / `turn_decision_review_repair_preview_reroute`，不再使用 bridge/recovery 术语。mainline extended regression `/private/tmp/zhiyuan_320_mainline_after_review_repair_bridge.json` 为 123/123 successful，median `9671ms`、p95 `22180ms`、max `34744ms`。action-scoped `确认生成` focused WS 初版 `/private/tmp/zhiyuan_320_confirm_generate_after_fix.json` 为 10/10 successful；actionFamily 绑定改造后 `/private/tmp/zhiyuan_320_confirm_generate_after_actionfamily_fix.json` 仍为 10/10 successful，median `6648ms`、p95/max `10772ms`。最新结果明确区分两类状态：无 active plan pending 时 `确认生成` 返回 no-pending guard；存在 active `generate_plan` pending 时才进入 pending apply，执行层因基础信息不足返回补全信息要求，不重新进入 full-agent 生成预览。
- 2026-06-24 G27 runtime 候选优先级修复：本轮定位到 `plan_next_action(remove_units)` 已给出结构化可执行删除 scope，但同一 turn 后续只读 `query_ordered` 与 `composite_proposal.needs_clarification=true` 会压掉 pending candidate。当前 [service.py](../zhiyuan-agent/app/service.py) 已改为：复合目标 `needs_clarification/feasibility=needs_clarification` 默认阻断普通 mutation pending；只有结构化 selector 已足够定位当前方案对象或明确组合过滤条件时才允许覆盖澄清，例如显式 `volunteer_ids/source_major_names/review_issue_target`，或 G27 风格 `min_tuition_per_year + preference_fit=unrelated` 删除条件。普通 `add_units + major_keyword` 不再绕过澄清。同一 turn 后续只读 `query_state/query_ordered/query_candidates` 不覆盖最近可执行 `plan_next_action` preview；候选构造继续消费结构化 payload，不从用户原文做字符串恢复，不重启 `classify_plan_recovery_action` 或 service recovery classifier。新增/更新单测覆盖复合澄清阻断 generic add preview、G27 风格删除 preview 保留、plan_next-only 不补卡、execute error 清空 preview。验证：`test_chat_service_history_persistence.py` 446/446、runtime hard-cut/entrypoint/sink audit 6/6、compiler runtime selection 79/79、runner/shadow 79/79、`proposal_compiler_golden.py` 32/32、`model_node_benchmark.py` 44/44。
- 2026-06-24 pending wrapper / no-tool fallback hard-cut 复核：删除 `_create_pending_intent_confirmation_from_preview_payload` 和 `_create_pending_fix_confirmation_from_user_goal_candidate` 两个 card-only wrapper，运行时调用点统一迁移到 result-style entry，防止丢失 `workspace_refresh_targets` 和 `blocked_reasons`。同时删除 full-agent 后处理 no-tool explicit intent fallback，显式 intent 更新只能在模型前经 `runtime_intent_hard_cut -> TurnDecision -> intent_entity_profile -> compiler sink` 创建 pending；旧 `_recover_explicit_intent_pending_from_prompt` 和 `explicitIntentRecovery` observability 已移除。`runtime_pending_entrypoints_320.json` 与 `runtime_pending_sink_calls_320.json` 已同步为 result entry；hard-cut 审计固定旧 wrapper、旧 no-tool fallback、旧 plan action recovery 命名不得回到 service。
- 2026-06-24 runtime intent hard-cut soft candidate 修复：G31/G21 暴露 `TurnDecision` 可能把显式未来参考诉求误锚到 `plan_preview/current_plan`，导致“把华中科技大学加到意向”落回 full agent 或被 active pending 冲突规则挡住。当前处理不是按用户原句补关键词，而是只把 `sideEffect=plan_preview/readonly_or_plan_preview` 且 `scenario=intent_update/region_preference_update` 的结果作为 soft candidate：它们不再硬阻断 runtime intent hard-cut，但必须继续通过 `intent_entity_profile` 抽取、`intent_preview` side-effect arbitration 和 compiler sink contract，才允许生成 `intent_change` pending；高置信 `atomic_mutation/current_plan`、`readonly`、`readonly_while_pending`、`needs_plan_first`、profile replan、pending apply/readonly/conflict 等结构化场景仍硬阻断。`turn_decision_tool` prompt 同步固定 active `intent_change` pending 下的新未来偏好/排除/特殊路径更新应输出 `intent_pending/future_reference/intent_update`，不能误判为 `pending_conflict_new_mutation` 或 `atomic_mutation/current_plan`。
- 2026-06-24 runtime intent hard-cut observability 修复：`runtime_intent_hard_cut` 的 `conversation_turn_event` 现在与直接 guard history 一起持久化，runner metrics 可以看到 `routingPath=runtime_intent_hard_cut`，避免“实际走了结构化 hard-cut，但回归报告像 full-agent”的诊断盲区。
- 2026-06-24 G19/G21/G31 isolated live 复核：隔离端口 Backend `18290`、Agent `18291`、Rank `18292` 下，focused G31 为 6/6 successful；组合 G19/G21/G31 为 16/16 successful。G31 第 5 步 `把华中科技大学加到意向` 生成 `intent_change` pending，summary 为 `偏好院校：华中科技大学`；第 6 步保底查询保持 `readonly_while_pending`，pending 不变。G21 普通兴趣分析不创建 pending，学校+强基路径诉求创建 school/path intent pending，最终无正式普通批方案 review 进入 readonly boundary，不自动生成方案。G19 无正式方案引用继续走 `needs_plan_first`，不误创建 intent pending。验证还包括 focused/unit 7 通过、intent/hard-cut 相关 644 通过、 broader agent suite 880 通过、`git diff --check` 通过。
- 2026-06-24 边界记录：本轮没有实现 Java 侧统一查询下推。当前 `PlanQueryProfile -> Python query_ordered` 仍是最小 runtime 路径；Java 侧已有候选池查询 DTO，但缺 ordered-plan query endpoint 和 tuition/preference-fit 完整条件。后续工作是先定义 `PlanQueryCondition`，统一 current-plan/query 与 candidate-pool/query 的条件字段、scope、projection 和 no-result reason，再交 Java 侧执行；在此之前不继续在 Python service 中扩一套完整筛选查询实现。
- 2026-06-24 live 回归环境修正：曾用 `8000 + 18090` 做 G27 探针，但 Agent 进程未显式设置 `INTERNAL_SERVICE_URL`，内部仍按默认后端读取，日志表现为 `phase=profile_ready/ordered_total=0`；该轮结果只能作为环境问题，不作为 G27 业务结论。`dialog_regression_runner.py` 已把后端 fixture clone/clear 失败从 warning 升级为 case-level `environment` failure，并跳过 WebSocket 步骤；runner/explorer 默认端口同步切到 `18291/18290`，避免错端口/错后端继续产出“空方案”伪回归。
- 2026-06-21 落地 runtime hard-cut forbidden symbol 单测：[test_runtime_hard_cut_audit.py](../zhiyuan-agent/tests/unit/test_runtime_hard_cut_audit.py)。该测试直接扫描 [service.py](../zhiyuan-agent/app/service.py)，固定 runtime 不得重新引用 `classify_plan_recovery_action`、`classify_composite_goal_action`、旧 plan/fix pending wrapper、旧 card-only intent/fix wrapper、旧 no-tool intent fallback、`recovered_pending_intent_card` / `recovered_intent_card`、旧 plan recovery 死代码、旧 `select_fix_proposal_candidate`、旧 `plan_action_recovery` 观测名，以及 `apply_pending_then_readonly` 的旧边界-only 路径；同时要求 service 走 `compile_runtime_review_fix_source` 这类 compiled source 入口，而不是直接展开旧 selector。2026-06-24 已进一步删除这两个旧 classifier 工具函数、benchmark adapter 和 case，不再以 profile 节点名义保留。
- 2026-06-21 hard-cut 增量：删除无当前结构化工具结果的 plan action recovery 和 composite goal recovery 调用源；删除预算/学费 runtime classifier 覆盖路径。无工具文本、空 intent preview、错误专业 intent preview、模型回复中的“确认加入方案吗/确认执行/是否确认”不再触发 `classify_plan_recovery_action`、`classify_composite_goal_action`、Java user-goal proposal 或 pending/card 创建。
- 同步补充生产回归：`把武汉大学计算机科学与技术加到方案里` 若模型只返回“已整理好加入当前方案，确认加入方案吗？”而没有结构化 preview，service 会清理确认话术，返回无卡边界，且不保存 pending。该问题归类为“无结构化候选的自然语言承诺恢复”，不是“文本场景补弹卡”。
- 同步收紧只读误路由 preview：用户明确“先看看/别直接加/先别动”时，如果模型或工具误生成 mutating preview，service 会移除本轮结构化 preview，并在文本中补明确无改动边界；不能只删“确认后执行”后留下“预览已生成/会补入”的半截承诺。
- 同步收紧无卡 intent 文本承诺：模型纯文本说“如果你确认，我会把安徽作为后续避开的地域”时，保留用户目标实体和解释，但清掉“确认后写入/作为后续参考”的承诺，返回“未列出可采纳内容/未写入后续参考”的边界；不调用 intent preview recovery，不保存 pending。
- 2026-06-21 hard-cut 增量：删除 `_fetch_fix_proposal_confirmation_source` 和 `generate_planning_fix_proposals` runtime 补捞路径。旧工具返回“已生成修复建议”但没有 `execute_plan_action(preview_fix_proposal)` 结构化结果时，不再由 service 重新拉 Java proposal、分类用户目标并补 `apply_fix_proposal` pending/card；该工具输出只能作为文本事实留在当前回复，后续 Java proposal evidence 应走 compiler/adapter dry-run 接入。
- 2026-06-21 hard-cut 增量：删除 runtime `select_fix_proposal_candidate` 选卡路径和回复文本 hint 选卡逻辑。`preview_fix_proposal` 只有在结构化结果显式给出 `selected_proposal_id`、结构化 target scope 唯一命中，或仅有一个 ready Java proposal 时才会落 `apply_fix_proposal` pending/card；多 ready proposal 且无唯一结构化目标时只保留无改动边界，后续选择权必须进入 compiler/arbitration，不由 service 后处理猜。
- 2026-06-21 hard-cut 增量：删除 `plan_next_action` 半桥接补执行路径。service 不再因为本轮只有 `plan_next_action` preview、或 `plan_next_action` 与 `execute_plan_action` action family 不匹配，就代替模型补调 `execute_plan_action` 并创建 plan/fix pending。`plan_next_action` 只能作为结构化计划/缺参 evidence；要生成 pending/card，必须有 `execute_plan_action` 结构化 preview 或后续 `CompiledProposal`。这覆盖此前 `complete_unexecuted_plan_next_action`、`complete_unexecuted_plan_next_preview` 和缺 scope 再调 `plan_next_action` 的补救路径。
- 2026-06-21 hard-cut 增量：runtime 已完全移除 `classify_plan_recovery_action -> plan_next_action -> execute_plan_action` 本地补执行链，并清理 `_plan_recovery_has_context`、`_plan_recovery_decision_to_tool_args`、`_build_recovered_plan_action_messages` 死代码。2026-06-24 后 `classify_plan_recovery_action` 本身也已删除；误路由恢复能力不再作为独立节点维护，当前方案动作必须进入 action DSL/compiler。
- 最新聚焦验证：`test_chat_service_history_persistence.py` plan_next/fix/compiled pending 子集覆盖 plan_next-only 不补 execute、不出 pending、不被短确认执行，execute preview 主路径仍出卡，legacy generate 不补卡，多 ready proposal 不按回复猜选，明确 target 唯一命中继续出卡，以及 plain/readonly review 不出卡。`test_chat_service_history_persistence.py` 覆盖 active pending 下“先不确认，看看影响”“删完了再看”“现在基于这些出方案”和新诉求冲突：前者不调用模型、不调用 pending classifier、不改变 pending active；`apply_pending_then_readonly` 会先执行已有 pending，普通 plan apply 成功且 workspace 刷新成功时直接回答执行后的数量、梯度和风险，刷新不可用时才返回 evidence/query 边界，失败时不追加只读结论；`apply_pending_then_new_request` 会先采纳 intent pending，并创建新的 `generate_plan` plan pending card，确认后才正式生成方案；新高副作用诉求会在模型前阻断，不创建第二张卡、不覆盖旧 pending。新增 `needs_plan_first` runtime guard 回归：明确无方案时的当前方案引用不调用模型、不创建 pending；未来参考诉求不被误拦。`apply_pending_then_new_request` 与 `apply_pending_then_readonly` 已在 G14/G27 profile、model-node、compiler golden 和 runtime shadow observation 中拆分，避免把 apply 后只读 follow-up 误归为新高副作用诉求。G14 最新 compiler golden `/private/tmp/proposal_compiler_320_g14_generate_pending_probe.json` 为 32/32，G14 record 已为 `pendingType=plan_mutation`。`test_mainline_dialog_scenarios.py` 15 通过。`test_proposal_compiler_runtime_selection.py` 54 通过，覆盖 fix proposal runtime arbitration、target-scope 归一/过滤、semantic decision precheck、confirmation source 过滤、compiled source 输出、user-goal proposal 选择、intent 输入校验、plan confirmation candidate contract、pending turn resolution、短文本确认 resolution、no-active-pending confirmation guard、needs-plan-first reference guard、active pending conflict guard 和 apply-then-new-request resolution。`test_runtime_hard_cut_audit.py` 2 通过，固定 service 运行时不得重新引入 recovery classifier、pending classifier、旧 wrapper、旧 selector、旧变量路径和 apply-then-readonly 边界-only 路径。`py_compile app/domain/proposal_compiler.py app/service.py examples/dialog_regression_runner.py examples/runtime_shadow_diff.py` 通过；服务主流程组 482 通过；3.2.0 gate + runner/shadow group 143 通过。离线报告 `/private/tmp/proposal_compiler_320_g1_g32_after_side_effect_split.json` 为 32/32，`/private/tmp/model_node_320_after_side_effect_split.json` 为 33/33。
- 落地只读 shadow diff 基座：[runtime_shadow_diff.py](../zhiyuan-agent/examples/runtime_shadow_diff.py)，用于比较旧 runtime 观测和 `CompiledProposal`。该工具不启动 WebSocket、不创建 pending、不 apply、不写后端状态；示例观测为 [runtime_shadow_diff_320_observations.example.json](../zhiyuan-agent/examples/runtime_shadow_diff_320_observations.example.json)。
- `dialog_regression_runner.py` 已支持 `--runtime-shadow-output`，可从真实 WebSocket 回归只读导出旧路径 observation。导出只记录可见 pending card、workspace refresh target、routing/tool observability 和归一化 `sideEffect/outputType/pendingType`，不改变当前用户响应或业务状态。
- 新增首批 G1-G32 e2e shadow 映射：[dialog_regression_320_g1_g32_shadow_cases.json](../zhiyuan-agent/examples/dialog_regression_320_g1_g32_shadow_cases.json)。当前覆盖 21 个可复用历史 fixture/session 的 G case；剩余 11 个继续留在 profile/compiler/node benchmark 层，待专门 fixture 构造后再进入 e2e shadow。
- 2026-06-21 完成 G1-G32 shadow r1：52 step，49 successful，3 content failure；21 个 profile case 有 runtime observation。修正只读工具 `applied=true` 的观测分类后，sideEffect 分布为 `readonly=10`、`readonly_while_pending=4`、`intent_pending=5`、`plan_preview=2`。
- 2026-06-21 corrected shadow diff：32 total、21 observed、9 clean、1 blocking、11 major、11 info。blocking 为 G1 文本承诺 plan mutation 但缺 pending card；major 集中在 G8 intent/plan sideEffect 边界、G16 局部锁定 DSL、G27 pending apply + readonly follow-up、以及 workspace refresh/presentation 协议不一致。
- 2026-06-21 完成 G1-G32 shadow r2/r3：
  - r2：52 step，47 successful，5 content failure；elapsed median `16466ms`，p95 `34596ms`，max `46255ms`。
  - r3：52 step，49 successful，3 content failure；elapsed median `14507ms`，p95 `28544ms`，max `36221ms`。
  - r2/r3 runtime observation 均为 `readonly=10`、`readonly_while_pending=4`、`intent_pending=6`、`plan_preview=1`；`pendingType` 为 `none=10`、`unchanged_existing_pending=4`、`intent_change=6`、`plan_mutation=1`。
  - r2/r3 diff 均为 32 total、21 observed、9 clean、3 blocking、9 major、11 info；新增稳定差异包括 `missing_pending=2`、`unexpected_pending_creation=1`、`presentation_mismatch=6`、`missing_workspace_refresh=8`。
- 三轮稳定结论：
  - G1、G27 为三轮稳定失败，分别对应 plan mutation pending 丢失、active pending 后复合 readonly follow-up 不执行。
  - G19 为 r2/r3 稳定失败，说明无正式方案引用必须由 `needs_plan_first` guard 处理，不能直接创建 intent pending；当前已先落明确无方案前置 guard，后续仍需纳入完整 TurnDecision/reference resolution。
  - G16/G17、G4/G29、G25、G30/G21 分别确认 plan local DSL、偏好强度、混合极性、special admission path 结构化能力仍不足。
  - G23、G10、G32 部分行为已相对稳定，可作为后续硬切不回退的正向基线。
  - 性能长尾集中在强基路径、分数/省份纠错后的重复查分、focused review 和 plan slice query，必须进入 EvidencePlan/tool budget/batch query 设计。

下一步：

1. 2026-06-25 复核 G27 focused live 后修正口径：之前“focused G27 4/4 successful”依赖当时 live session 正好生成了 `remove_units` active pending，不能作为长期 fixture 结论。当前 source35 两万以上命中 0，source26 虽有高学费项但缺稳定意向/profile 贴合 evidence，“两万以上且跟我意向不沾边”可合法返回 `no_change`，不会生成 pending。因此 e2e shadow 已拆成 `320-shadow-G27-tuition-readonly-and-atomic-selector-observation`，只验证学费阈值只读查询和 `TurnDecision + AtomicPlanActionDsl -> remove_units` 工具链；真正的 `G27-apply-pending-then-readonly-followup` 继续要求 `activePending + orderedPlan` fixture，后续必须用真实 preview/fix sink 产出的显式 active pending fixture 或审计化 `seedPendingConfirmation`，不能在 runner 里手写 selector 绕过 sink contract。
2. 下一步重跑 G1-G32 golden/full live，统计 successful/content failure、shadow cleanRate、平均/median/p95/max latency、G12/G7/G17/G27/G31 长尾和重复工具。G27 只按拆分后的 readonly/atomic selector 观测进入 live；正式 apply-then-readonly 效果回归必须等 active pending fixture contract 稳定后再开。G21/G31 仍有强基/profile/intent hard-cut 相关长尾；后续要进入 EvidencePlan/tool budget/batch query，而不是继续加 service 后处理。
3. 扩大 mainline/regression 回归，重点检查多路径残留：旧 recovery classifier、文本承诺补卡、plan_next 半桥接补执行、Java fix proposal 补捞、local action 专用旁路、profile-change fallback 是否重新出现；runtime hard-cut audit 继续作为门禁。
4. 将已三轮全绿的 live-node profile 输出接到 ProposalCompiler/replyPlan/displayPayload contract：`preferenceStrength/preferenceScope/entityPolaritySpans`、TurnDecision 和 reply profile 已在离线 profile/compiler/benchmark 层验证，但还没有 runtime hard-cut。未支持字段仍只记 `schemaGaps`，不桥接。
5. 将已离线验证的 `planActionDsl`、`admissionPath` 和 runtime intent/entity profile contract 接成更完整的 runtime candidate，只读输出和 fixture replay，不创建无证据 pending；`needs_plan_first`、`conflict_with_existing_pending`、`apply_pending_then_readonly`、`readonly_while_pending` 已有确定性 guard/最小路径，下一步接完整 TurnDecision/EvidencePlan，不再增加旧桥接。
6. pending action 继续收敛到确定性前置门禁；后续补完整 pending merge/replace 选择，以及 intent_change 采纳后的独立影响评估节点，而不是从 service 临时拼桥。
7. 细化 plan local action DSL 到 Java proposal endpoint：tier-local reorder、pin/lock、current-major-group 范围由 compiler/DSL 接管，模型只输出用户意图和选择器。
8. 将真实 Java `fix-proposals/user-goal/generate` 和 `fix-proposals/generate` 的只读响应接入 adapter dry-run 报告，先在 fixture/session dry-run 中验证，不创建 pending、不 apply。重点校验 `capacityStatus/noResultReason/missingMustCover/contractGaps`。
9. 定义后续 Java 查询统一条件合同：`PlanQueryCondition` 需要覆盖 ordered scope、candidate pool scope、tuition range、preference-fit、projection、slice、sort、no-result reason；Java 具备执行能力前，不在 Python service 扩完整筛选器。
10. 明确 workspace refresh/presentation 归属：compiler 负责输出 `workspaceRefreshTargets` 和 display presentation，旧 formatter/service 不再自行补或漏发。
11. 建立 explorer issue normalization 和 golden promotion 流程，把新问题按 `model_capability/schema_gap/compiler_gap/fixture_mismatch/provider_env/latency_longtail` 归因后再进入固定回归。

- 2026-06-25 收口：`full_agent` 兜底也开始写 `displayPayload/replyPlan`，带修复选项的 review/repair boundary 会稳定落 `conditional_options`；plan confirmation candidate 在缺少显式 `target_view` 时默认走 `ordered`，并显式带出 `workspaceRefreshTargets=["ordered"]`。本轮 focused live G1/G2/G19 已验证：G1 返回 `planningWorkspaceAction(ordered) + pendingConfirmationCard`，G2 返回 `conditional_options` 且无 followup，G19 稳定 `needs_plan_first`。
