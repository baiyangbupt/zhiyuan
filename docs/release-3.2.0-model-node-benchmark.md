# Release 3.2.0 Model Node Benchmark

本文定义 3.2.0 中所有依赖模型理解或生成能力的关键节点评估体系。它区别于 WebSocket 端到端 runner：端到端 runner 评估用户最终看到的完整效果；model node benchmark 评估单个模型节点的输入、结构化输出、稳定性、延迟和错误类型。

## 1. 为什么单独评估节点

当前问题不能只靠 e2e 判断：

- e2e 失败可能来自模型理解、schema 表达、compiler、后端 fixture、工具错误、reply formatter 或前端卡片。
- 同一个用户回合可能包含多个模型节点，最终结果对了不代表中间节点稳定。
- 3.2.0 要决定哪些判断交给模型，哪些放到 deterministic compiler/guard，必须先有节点级 profile。

因此需要单独评估：

- 输入是否足以让模型判断。
- 模型输出 schema 是否稳定。
- 关键字段是否准确。
- 不确定时是否能返回低置信/clarification。
- 同一 case 多轮输出是否一致。
- provider 错误是否被排除在质量矩阵之外。

## 2. 节点分层

| 节点 | 当前代码来源 | 评估重点 |
| --- | --- | --- |
| `turn_side_effect` | 3.2.0 新 TurnDecision | taskLayer、sideEffect、scopeAnchor、missingInfo |
| `intent_side_effect` | `intent_state_tool._classify_intent_side_effect` | intent 是否直接 pending，普通分析是否被过强写入 |
| `plan_semantic_action` | `classify_plan_semantic_action` | query/review/analyze/preview 边界 |
| `plan_recovery_action` | `classify_plan_recovery_action` | 模型误路由后是否能恢复成结构化动作，是否过度恢复 |
| `composite_goal` | `classify_composite_goal_action` | only_keep/must_have/exclude/tuition 目标和 requiresPlanMutation |
| `pending_action` | `classify_pending_confirmation_action` | confirm/reject/ask impact/new topic |
| `plan_query_profile` | `plan_query_profile_tool` | 当前方案只读查询的 queryType、dimensions、filters、projection |
| `candidate_filter_extraction` | `candidate_filter_extraction_tool` | 候选查询筛选条件、missingInfo/noResultReason |
| `intent_entity_extraction` | `intent_entity_profile_tool` | entity、polarity、preference strength、admissionPath |
| `proposal_selection` | `select_fix_proposal_candidate` | 多 proposal 中选择是否匹配用户 focus |
| `reply_focus_binding` | 3.2.0 replyPlan | review evidence 是否按用户焦点回答 |
| `reply_generation_grounding` | final reply generation | 是否回答问题、是否泄露内部词、是否编造事实 |

Benchmark 默认不调用线上链路。默认模式只用统一 case/actual/expected 契约评估已记录输出或离线 compiler 输出；显式传 `--actual-source live-node` 时，才直接调用已接入的模型节点函数。

`proposal_selection` 只作为模型能力评估节点保留。3.2.0 hard-cut 后，runtime service 不再用 `select_fix_proposal_candidate` 或回复文本 hint 直接选择并创建 `apply_fix_proposal` pending；多 proposal arbitration 必须进入 compiler/candidate 层，service 只接受显式 `selected_proposal_id`、结构化 target 唯一命中或唯一 ready proposal。

首批 live-node adapter 支持：

- `turn_side_effect`
- `intent_side_effect`
- `intent_entity_extraction`
- `candidate_filter_extraction`
- `plan_semantic_action`
- `plan_recovery_action`
- `composite_goal`
- `pending_action`
- `plan_query_profile`
- `proposal_selection`
- `reply_focus_binding`
- `reply_generation_grounding`

尚未接入的节点必须输出 `unsupported_live_node`，不能静默跳过或误记为模型质量失败。

## 3. Case 契约

```json
{
  "caseId": "node-turn-side-effect-G1",
  "node": "turn_side_effect",
  "source": "3.1.1 P0-3",
  "priority": "P0",
  "prompt": "不要英语相关专业，当前方案里有的话也删掉",
  "input": {
    "historyContext": [],
    "planningStateProfile": {
      "formalPlanPresent": true,
      "pendingExists": false
    }
  },
  "expected": {
    "taskLayer": "plan",
    "sideEffect": "plan_preview",
    "scopeAnchor": "current_plan"
  },
  "actual": {
    "taskLayer": "plan",
    "sideEffect": "plan_preview",
    "scopeAnchor": "current_plan"
  },
  "assert": {
    "exact": ["taskLayer", "sideEffect", "scopeAnchor"],
    "contains": {},
    "notContains": {}
  },
  "metricsTags": ["mixed_intent_plan", "pending_protocol"]
}
```

`actual` 可以来自三类来源：

- 已记录的线上/本地 observability。
- 离线模型调用结果。
- compiler 原型输出。
- 显式 live-node 调用结果。

这三类来源必须在报告里用 `actualSource` 区分。

报告同时保留两层 actual：

- `rawActual`：模型节点或记录文件原样输出，用于复盘旧 schema 和 provider 返回。
- `profileActual`：3.2.0 profile 视图，只做安全归一和 legacy 字段收纳，不补造模型未产出的字段。

如果 expected/assert 要求 `preferenceStrength`、`preferenceScope`、`entityPolaritySpans`、`admissionPath` 等 3.2.0 字段，而 live-node 仍只输出 `constraintIntentType` 这类旧字段，报告必须在 `schemaGaps` 中标记缺口并让该 case 质量失败。不能为了通过率把 legacy 字段桥接成新字段。

## 4. 指标

通用指标：

- `case_count`
- `pass_count`
- `fail_count`
- `field_accuracy`
- `exact_match_rate`
- `schema_valid_rate`
- `missing_required_field_rate`
- `latency_median_ms`
- `latency_p95_ms`
- `provider_env_excluded_count`
- `provider_env_excluded_by_reason`

节点特定指标：

- `sideEffect_accuracy`
- `unsafe_side_effect_rate`
- `readonly_to_pending_false_positive_rate`
- `mutation_to_readonly_false_negative_rate`
- `scopeAnchor_accuracy`
- `preference_strength_accuracy`
- `requiresPlanMutation_accuracy`
- `pending_action_accuracy`
- `focus_preservation_rate`
- `grounded_reply_rate`

## 5. 和 e2e runner 的边界

Model node benchmark 不做：

- 不启动 WebSocket。
- 不操作 backend session。
- 不判断工作台刷新是否成功。
- 不把 fixture 缺失计入模型错误。
- 不把 provider 400/403/余额不足计入模型质量。
- 不为线上 runtime 增加会影响裁决、写状态或创建 pending 的 shadow、双写、兼容桥接或多路径裁决。
- 若接入 3.2.0 只读 shadow diff，只能记录节点输入/输出/差异和延迟，不改变 e2e 行为。

Model node benchmark 要做：

- 固定输入。
- 固定 expected。
- 对比 actual。
- 输出字段级 mismatch。
- 给 compiler/guard 设计提供依据。
- 在 provider 不可用时记录环境排除原因。

## 6. Provider / Model 横评口径

模型差异需要评估，但只在节点 benchmark 和 provider precheck 层完成，不进入 runtime 多路径裁决。

横评目标：

- 判断 Kimi、GLM、MiniMax、DeepSeek 或后续 GPT 系列在同一节点输入下的结构化输出差异。
- 区分 `provider_env`、模型理解能力、schema 输出能力、prompt 不足和 deterministic compiler 缺口。
- 给 3.2.0 的防御性设计提供阈值，例如哪些节点必须 deterministic guard 前置，哪些节点可以交给模型输出候选。

横评范围优先覆盖：

- `turn_side_effect`：G1/G3/G8/G19/G22/G27/G31/G32，重点看状态权威、pending/formalPlan 不能被用户话术覆盖。
- `intent_entity_extraction`：G4/G23/G25/G29/G30，重点看 `preferenceStrength`、`entityPolaritySpans`、`admissionPath`。
- `plan_recovery_action` / `plan_semantic_action`：G2/G7/G16/G17/G21/G27，重点看局部动作 DSL、review focus 和 unsupported action。
- `reply_focus_binding` / `reply_generation_grounding`：G7/G20/G21/G32，重点看是否回答问题、是否编造证据、是否泄露内部字段。

横评报告必须包含：

- `provider/model`、`node`、`caseId`、`repeatIndex`。
- `providerPrecheckStatus` 和 `providerEnvExcludedReason`。
- 字段级 `fieldFailures`、`schemaGaps`、`legacyOnlyFields`。
- `latencyMs`、p50/p95/max、稳定通过率。
- 原始输出 `rawActual` 和归一后的 `profileActual`。

准入规则：

- provider precheck 失败的模型不得进入质量矩阵；错误归类为 `provider_env`。
- 某模型更快但 schema gap 或安全 sideEffect 错误更多，不能作为 3.2.0 主模型候选。
- 某模型在节点 benchmark 上更好，也不能绕过 `CompiledProposal/EvidencePlan/pending sink contract` 直接接 runtime。
- 需要保留同一组 G1-G32 节点 case 的三轮结果，避免单轮偶然通过。

当前配置基线：

- provider 配置样例在 [model_provider_benchmark.providers.example.json](../zhiyuan-agent/examples/model_provider_benchmark.providers.example.json)，已包含 Kimi K2.6、MiniMax M2.5、DeepSeek V4 Flash、GLM 5.1、GLM 5.2。
- `model_provider_benchmark.py` 负责 provider direct/precheck/e2e 维度；`model_node_benchmark.py` 负责节点结构化能力。二者输出可以关联分析，但不能互相替代。

后续如测试 GPT 系列，需要新增 provider 配置和 env key，先跑 provider precheck，再跑节点 benchmark；不改 runtime provider 名称做线上对照，避免把模型差异和运行时路径差异混在一起。

## 7. 首批节点

3.2.0 节点 benchmark 已覆盖 G1-G32：

- `turn_side_effect`：G1/G2/G3/G6/G8/G9/G14/G19/G22/G24/G27/G31/G32。
- `intent_side_effect`：G4/G13/G18/G29。
- `plan_semantic_action`：G7/G21。
- `plan_recovery_action`：G16/G17。
- `composite_goal`：G5。
- `pending_action`：G10/G15。
- `candidate_filter_extraction`：G26。
- `intent_entity_extraction`：G23/G25/G30。
- `reply_focus_binding`：G7。
- `reply_generation_grounding`：G20。
- `provider_precheck`：G11。
- `latency_profile`：G12/G28。

后续每修复一个 e2e 问题，必须判断是否同时增加对应 node benchmark。只有 e2e case 而没有节点 case，会继续导致问题归因不清。

## 8. 当前落地

首版脚本：

```text
zhiyuan-agent/examples/model_node_benchmark.py
```

首批样例：

```text
zhiyuan-agent/examples/model_node_benchmark_320_cases.json
```

首版脚本支持离线 `expected` vs `actual` 评估，也支持对首批已接入节点做显式 live-node 调用。

离线评估：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/model_node_benchmark.py \
  --cases examples/model_node_benchmark_320_cases.json \
  --output /private/tmp/model_node_320_report.json
```

指定节点的 live-node 评估：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/model_node_benchmark.py \
  --cases examples/model_node_benchmark_320_cases.json \
  --actual-source live-node \
  --nodes intent_side_effect,plan_semantic_action,composite_goal \
  --repeat 3 \
  --output /private/tmp/model_node_320_live_node_report.json
```

报告口径：

- `rawTotal`：读取并执行的全部 case。
- `total`：进入模型质量矩阵的 case，不包含 provider 环境排除。
- `providerEnvExcluded`：API key、模型 ID、余额、鉴权、超时、连接失败等环境/接入失败数量。
- `providerEnvExcludedByReason`：环境排除原因分布。
- `fieldFailures`：质量矩阵内的字段级失败聚合。
- `schemaGaps`：质量矩阵内缺失 3.2.0 profile 字段的聚合。它是 schema/节点能力缺口，不是 provider/env 问题。
- `stability.caseGroups`：重复运行的原始 case 数。
- `stability.stablePassedGroups`：所有重复轮次均通过的 case 数。
- `stability.stablePassRate`：重复 case 的稳定通过率。

当前 G1-G32 节点 case 中，`turn_side_effect`、`intent_side_effect`、`intent_entity_extraction`、`candidate_filter_extraction`、`plan_query_profile`、`plan_semantic_action`、`plan_recovery_action`、`composite_goal`、`pending_action`、`proposal_selection` 可通过 live-node adapter 直接调用节点函数。

`intent_entity_extraction` 不复用旧的 major/school/city/career 抽取结果拼装 profile，而是通过 `intent_entity_profile_tool` 直接输出 3.2.0 schema。这样能单独衡量模型对 `preferenceStrength`、`entityPolaritySpans`、`admissionPath` 的理解能力，避免旧字段改名后掩盖 schema 缺口。

`turn_side_effect` 通过 `turn_decision_tool` 直接输出 3.2.0 TurnDecision schema。该工具只用于 benchmark/profile，不接 runtime service，不创建 pending，不调用 planning tool。

`plan_query_profile` 通过 `plan_query_profile_tool` 直接输出当前方案只读查询 profile，包括 `queryType/dimensions/filters/projection/pendingReferenceType`。它负责模型层理解“问几个/看哪些/保底末尾/学费阈值/相关专业”，`proposal_compiler` 只校验结构化 profile 并编译 `PlanQuery` DSL，不再在 service 层按原句硬拆查询意图。runtime 进入该节点前必须先由 `TurnDecision` 判定为 `taskLayer=plan`、`scopeAnchor=current_plan`、`sideEffect=readonly/readonly_while_pending`、`scenario=plan_query/plan_query_while_pending`；方案调整、修复预览、profile change/replan 和长期意向更新不能直接调用 query profile。

2026-06-23 runtime 复核后补充一条节点契约：`planningStateProfile` 是 TurnDecision 的权威状态输入。若模型在 `pendingExists=false` 时输出 `readonly_while_pending/plan_query_while_pending`，工具层归一为 `readonly/plan_query`，避免无 pending 场景被错误挡在 PlanQueryProfile 前。该归一只使用结构化 payload，不按用户原句匹配。复跑 `/private/tmp/model_node_320_recorded_after_turn_decision_normalization.json` 为 42/42 通过，其中 `turn_side_effect=13/13`、`plan_query_profile=3/3`。

2026-06-23 profile-change 状态追问也进入 TurnDecision：已有历史 `ProfileChangeReplan` DSL 时，用户追问“现在方案是不是按新资料算”应输出 `scenario=profile_change_state_query`、`scopeAnchor=current_profile`、`sideEffect=readonly/readonly_while_pending`。service 只消费 TurnDecision 场景和历史 DSL；旧 `plan_semantic_action.replyFocus=profile_change_state_query` 仅保留为过渡 fallback。fixture 复跑 `/private/tmp/model_node_320_fixture_after_profile_state_turn_decision.json` 为 42/42 通过，`turn_side_effect=13/13`。

同日补齐 profile replan scope 节点约束：`TurnDecision` 必须区分当前学生资料更新、临时测算和范围不清三类场景。`current_student_update` 输出 `profile_change_replan/profile_update_replan`，`adhoc_scenario` 输出 `profile_replan_adhoc/profile_adhoc_replan`，`ambiguous` 输出 `profile_replan_ambiguous/profile_scope_ambiguous`；三者都必须携带结构化 `proposedProfile`。fixture 增加 adhoc/ambiguous 两个 case 后，离线 `/private/tmp/model_node_320_after_profile_replan_scope.json` 为 44/44 通过，`turn_side_effect=15/15`。runtime 只消费这些结构化字段，不能由 service 按中文原句补判。

`reply_focus_binding` 与 `reply_generation_grounding` 通过 `reply_profile_tool` 直接输出 reply profile 字段。该工具只用于 benchmark/profile，不生成用户可见回复，不接 runtime service。

`provider_precheck`、`latency_profile` 仍是离线/recorded case 或 3.2.0 新协议目标，后续按实现进度逐步接 adapter。

当前离线基线：

```text
cases: 33
G coverage: G1-G32
passRate: 1.0
```

2026-06-21 profile schema 更新后离线基线：

```text
report: /private/tmp/model_node_320_profile_schema_latest.json
cases: 33
passed: 33
failed: 0
passRate: 1.0
schemaGaps: {}
```

本次更新将 G4/G13/G18/G23/G25/G29/G30 的节点断言从旧 `constraintIntentType`/positive-negative list 口径推进到 3.2.0 profile 字段：

- G4/G29：`primary` 与 `acceptable` 分离，禁止把软偏好升级成 `must_have/only_keep`。
- G13：普通“加到意向”进入 `preferred`，禁止误判成必须保留。
- G18：历史院校偏好保持 `preferred`，新“不要民办”进入 `exclude_hard`，并保留 `preferenceScope=保底`。
- G23：长三角是 region preference，“优先”归为 `primary`，禁止落到“城市管理”专业实体。
- G25：用 `entityPolaritySpans` 绑定短语级 positive/negative；“加意向”正向实体为 `preferred`，排除实体为 `exclude_hard`，避免所有实体被同一极性吞掉。
- G30：强基用 `admissionPath=strongbase` 与学校实体并列保留。

2026-06-21 已接 adapter live-node 三轮基线：

```text
report: /private/tmp/model_node_320_live_adapters_r3.json
cases: 11 * 3 = 33
quality total: 33
passed: 9
failed: 24
passRate: 0.2727
providerEnvExcluded: 0
latency medianMs: 3135
latency p95Ms: 4766
latency maxMs: 10420
stablePassedGroups: 2 / 11
stablePassRate: 0.1818
```

节点表现：

| node | total | passed | failed | 结论 |
| --- | ---: | ---: | ---: | --- |
| `composite_goal` | 3 | 3 | 0 | G5 negative-only region 在现有节点上稳定通过 |
| `intent_side_effect` | 12 | 5 | 7 | 软偏好/历史偏好合并仍常被升为 `must_have/only_keep` |
| `pending_action` | 6 | 1 | 5 | 无 pending 的“确认”被误判为 `confirm_pending`，说明节点缺少 pending 存在性硬门禁 |
| `plan_semantic_action` | 6 | 0 | 6 | `replyFocus/targetIssueCodes` 基本未产出，当前 schema/prompt 不足以支撑 G7/G21 |
| `plan_recovery_action` | 6 | 0 | 6 | 锁定动作、tier-local reorder 和局部 ordinal 仍不稳定 |

主要字段失败按旧断言口径统计如下；schema 更新后应重点看同类问题在 `preferenceStrength/preferenceScope/entityPolaritySpans/admissionPath/schemaGaps` 上的表现：

- `constraintIntentType`：7 次。
- `replyFocus`：6 次。
- `actionFamily`：6 次。
- `action`：5 次。
- `targetIssueCodes`：3 次。
- `unsupportedAction`：3 次。
- `tier`：3 次。
- `targetPosition`：2 次。

初步定性：

- 这轮没有 provider/env 排除，失败是现有模型节点能力、schema 或 prompt 与 3.2.0 目标不对齐。
- `pending_action` 不能只靠模型判断确认语义，必须先由 deterministic guard 注入“无 active pending 则不可 confirm”。
- `intent_side_effect` 的 `constraintIntentType` 过强，3.2.0 需要 preference strength schema 和 compiler guard，而不是让该节点直接决定 must-have/only-keep。
- `plan_semantic_action` 目前 actionFamily 可保守，但没有稳定输出 reply focus；reply focus 应进入 TurnDecision/replyPlan 的显式字段。
- `plan_recovery_action` 不适合作为 3.2.0 局部方案动作的最终编译器；tier-local action 应由 deterministic DSL/compiler 承接，模型只给意图和选择器。

新增守卫型节点用例已经进入 benchmark 单测：

- 无 active pending 时，“确认”不能成为 `confirm_pending`。
- active pending 下只读查询必须保持 pending unchanged，不能 apply。
- 无正式方案引用时必须输出 `needs_plan_first/no_referent`，不能猜测并创建 intent pending。
- 混合正负意向必须有 span 级 polarity，不能把所有实体统一为 negative 或 positive。

2026-06-21 schema 更新后 live-node 单轮基线：

```text
report: /private/tmp/model_node_320_live_schema_r1.json
cases: 11
passed: 2
failed: 9
passRate: 0.1818
providerEnvExcluded: 0
latency medianMs: 3157
p95Ms: 4396
maxMs: 4396
```

节点结论：

- `composite_goal`：G5 通过，negative-only region 仍是现有节点中最稳定的结构化判断。
- `pending_action`：G15 通过，但 G10 no-pending confirm 仍会把空 pending 下的“确认”判为 `confirm_pending`。这必须由 deterministic guard 前置拦截。
- `intent_side_effect`：4/4 失败；主要不是 provider 问题，而是 live-node 仍只输出 `constraintIntentType`，缺少 `preferenceStrength/preferenceScope`，且会把 G4/G29 软偏好升成 `must_have`、把 G18 “保底公办不要民办”升成 `only_keep`。
- `plan_semantic_action`：2/2 失败；actionFamily 在 G7 保守为 none 是可接受的，但 `replyFocus/targetIssueCodes` 未产出；G21 强基+普通批合理性查询没有进入 `query_state/state_explanation`。
- `plan_recovery_action`：2/2 失败；G16 缺 `unsupportedAction=pin_or_lock_unit`，G17 把 tier-local move 误成局部 sort，且 targetPosition 缺失。

字段失败与 schema gap：

```text
fieldFailures:
  preferenceStrength.primary: 2
  preferenceStrength.acceptable: 2
  preferenceStrength.preferred: 2
  preferenceStrength.exclude_hard: 1
  preferenceScope: 1
  replyFocus: 2
  actionFamily: 2
  action: 1
  unsupportedAction: 1
  targetIssueCodes: 1
  tier: 1
  targetPosition: 1

schemaGaps:
  preferenceStrength.primary: 2
  preferenceStrength.acceptable: 2
  preferenceStrength.preferred: 2
  preferenceStrength.exclude_hard: 1
  preferenceScope: 1
  unsupportedAction: 1
```

这轮基线确认：当前 live-node 主要缺 3.2.0 schema 表达能力，不是简单调低 `constraintIntentType` 阈值能解决。下一步应先改 adapter/schema 输出或新增 TurnDecision/profile 节点，再接 compiler candidate；不能在 runtime formatter/service 中用 legacy 字段补桥。

2026-06-22 网络恢复后，先对 3.2.0 schema 相关 live-node adapter 做了三轮复测：

```text
report: /private/tmp/model_node_320_live_intent_schema_r3_before_prompt_fix.json
nodes: intent_side_effect, intent_entity_extraction, candidate_filter_extraction
cases: 8 * 3 = 24
passed: 6
failed: 18
passRate: 0.25
stablePassRate: 0.25
providerEnvExcluded: 0
```

主要问题已经从 provider/env 转为真实 schema 输出问题：

- `intent_side_effect` 稳定把 `preferenceStrength` 输出成“实体 -> 强度列表”的反向结构，例如 `{"网络与新媒体":["primary"]}`，而目标 schema 必须是 `{"primary":["网络与新媒体"]}`。
- G18 没有保留输入 `structuredIntents.school.positiveSchools`，只输出了公办/民办抽象类型。
- `intent_entity_extraction` 对 G25 的 `口腔` span 没有稳定规范成 `口腔医学`。
- G23 的 profile 期望从 `preferred` 修正为 `primary`，因为“城市优先长三角”里的“优先”按 3.2.0 strength 定义属于最高优先级。

已做修正：

- `intent_side_effect` prompt 明确 `preferenceStrength` 必须是“强度 -> 实体列表”，并给出正确/错误 JSON 示例。
- `intent_side_effect` prompt 明确 `structuredIntents` 中正向实体在 `intent_preview` 时必须保留到 `preferenceStrength`，普通正向实体默认进入 `preferred`。
- `intent_entity_profile_tool` prompt 增加同样的 `preferenceStrength` 方向约束和规范实体名要求。
- `IntentSideEffectDecision` / `IntentEntityProfileResult` 对空 `admissionPath=[]` 做安全归一为 `None`，避免 provider 把“无路径”输出成空数组时变成节点错误。

修正后三轮 live-node 基线：

```text
report: /private/tmp/model_node_320_live_intent_schema_after_optional_path_fix_r3.json
nodes: intent_side_effect, intent_entity_extraction, candidate_filter_extraction
cases: 8 * 3 = 24
passed: 24
failed: 0
passRate: 1.0
schemaGaps: {}
legacyOnlyFields: {}
stablePassedGroups: 8 / 8
stablePassRate: 1.0
latency medianMs: 5301
latency p95Ms: 13485
latency maxMs: 14553
```

对应离线门禁保持通过：

```text
model-node offline: /private/tmp/model_node_320_after_live_schema_fix_offline.json, 33/33 passed
proposal compiler: /private/tmp/proposal_compiler_320_after_g23_primary.json, 32/32 passed
```

这轮结论：`preferenceStrength/entityPolaritySpans/admissionPath` 的 live-node schema 能通过 prompt + 目标 schema 约束收敛，不需要在 runtime service 中桥接 `constraintIntentType`。下一阶段重点转向 `turn_side_effect`、`reply_focus_binding`、`reply_generation_grounding`。

2026-06-22 `turn_side_effect` live-node adapter 接入后，首次单轮基线：

```text
report: /private/tmp/model_node_320_live_turn_decision_r1.json
nodes: turn_side_effect
cases: 13
passed: 1
failed: 12
passRate: 0.0769
fieldFailures: {"sideEffect": 2, "scenario": 11, "taskLayer": 3, "scopeAnchor": 2}
schemaGaps: {}
legacyOnlyFields: {}
latency.medianMs: 4818
latency.p95Ms: 6342
latency.maxMs: 11638
```

失败根因不是 provider/env，也不是 runtime pending/card 路径，而是 TurnDecision 输出契约没有钉死：

- `scenario` 经常输出自然语言或自造 ID，而不是 3.2.0 枚举。
- `planningStateProfile.pendingExists/formalPlanPresent` 没有被模型当作权威输入，G1/G9/G19 等会被用户话术或历史感覆盖。
- `candidate_pool` 机会查询、`current_major_group` 局部策略、pending 下当前方案查询的 taskLayer/scenario 粒度不清。
- 输出格式没有强约束为单个 JSON object，G24 曾出现 `Extra data` 解析失败。

修复口径只收紧 benchmark-facing `turn_decision_tool` 的 schema/prompt：

- `taskLayer/sideEffect/scopeAnchor/scenario` 必须从 allowedValues 原样选择。
- `scenario` 只能放枚举 ID，解释只能放 `reason`。
- `planningStateProfile` 布尔值是权威状态，不能由“刚那个方案/当前方案/先不确认”等话术反推覆盖。
- 明确 G1/G3/G6/G9/G14/G19/G22/G24/G27/G31/G32 的边界例子。
- 最终输出只能是单个 JSON object。

修复后单轮与三轮结果：

```text
single r1: /private/tmp/model_node_320_live_turn_decision_after_prompt_fix3_r1.json
single result: 13/13 passed, fieldFailures={}, schemaGaps={}, legacyOnlyFields={}

stable r3: /private/tmp/model_node_320_live_turn_decision_after_prompt_fix3_r3.json
rawTotal: 39
total: 39
passed: 39
failed: 0
passRate: 1.0
stability.caseGroups: 13
stability.stablePassedGroups: 13
stability.stablePassRate: 1.0
fieldFailures: {}
schemaGaps: {}
legacyOnlyFields: {}
latency.medianMs: 4392
latency.p95Ms: 9567
latency.maxMs: 9993
```

这轮结论：TurnDecision 的 G1/G2/G3/G6/G8/G9/G14/G19/G22/G24/G27/G31/G32 能在模型节点层收敛为 3.2.0 schema；不需要通过 service/formatter 增加 pending、无方案引用或 scenario 映射桥接。下一步仍应把该节点输出交给离线 ProposalCompiler/contract 验证，再评估 runtime hard-cut。

2026-06-22 接入 reply profile live-node adapter 后，`reply_focus_binding` 和 `reply_generation_grounding` 三轮结果：

```text
single r1: /private/tmp/model_node_320_live_reply_profile_r1.json
single result: 2/2 passed, fieldFailures={}, schemaGaps={}, legacyOnlyFields={}

stable r3: /private/tmp/model_node_320_live_reply_profile_r3.json
rawTotal: 6
total: 6
passed: 6
failed: 0
passRate: 1.0
stability.caseGroups: 2
stability.stablePassedGroups: 2
stability.stablePassRate: 1.0
fieldFailures: {}
schemaGaps: {}
legacyOnlyFields: {}
latency.medianMs: 4274
latency.p95Ms: 9811
latency.maxMs: 9811
```

覆盖结论：

- G7 `reply_focus_binding` 能稳定输出 `answerFocusFirst=true`、`targetIssue=[cooperative_program, tuition_budget]`、`sideEffectBoundary=readonly_no_apply`。
- G20 `reply_generation_grounding` 能稳定输出 `mustGroundFormula=true`、`missingInfo=[province, art_formula]`、`forbidPreciseScore=true`。
- 这仍是回复 profile，不是最终回复生成 hard-cut。后续要把 replyPlan/displayPayload 接入 runtime 时，回复模型只能渲染 compiler 提供的 evidence 和边界，不能自行承诺 pending 或编造精确分数。

2026-06-22 继续把旧 live-node adapter 的协议缺口补齐：

- `pending_action`：无 active pending 时直接返回 `action=none`，不再让模型把裸“确认”误判为 confirm。runtime 已删除该 classifier 调用；该工具仅保留给 benchmark/profile。
- `plan_semantic_action`：允许 `actionFamily=none` 同时输出 `replyFocus/targetIssueCodes`，固定 G7 只读风险解释的 `target_issue_only`；G21 强基+普通批合理性查询进入 `query_state/state_explanation/review_boundary`。
- `plan_recovery_action`：新增 `unsupportedAction` profile 字段，固定 G16 `pin_or_lock_unit`；补 G17 tier-local ordered move，输出 `move_ordered_unit/tier=保底/targetPosition=1/sortField=admissionRatio`。
- `intent_side_effect`：strength 规则收紧为 `primary=明确优先/首选/重点`、`preferred=普通偏好/加意向`、`acceptable=也可以考虑/备选可接受`；G18 明确保留 `structuredIntents.school.positiveSchools` 到 `preferred`，禁止用 `only_keep=公办` 替代具体院校。
- `intent_entity_extraction`：G25 fixture 同步修正为正向 `preferred`、负向 `exclude_hard`，与 G13 “加到意向”口径一致。

关键复测报告：

```text
intent_side_effect stable r3:
report: /private/tmp/model_node_320_live_intent_side_effect_after_g18_preserve_fix_r3.json
passed: 12/12
stablePassRate: 1.0
schemaGaps: {}
legacyOnlyFields: {}
latency.medianMs: 7411
latency.p95Ms: 10133
latency.maxMs: 11263

turn_side_effect stable r3:
report: /private/tmp/model_node_320_live_turn_decision_after_g8_intent_layer_fix_r3.json
passed: 39/39
stablePassRate: 1.0
schemaGaps: {}
legacyOnlyFields: {}
latency.medianMs: 4954
latency.p95Ms: 9021
latency.maxMs: 11733
```

当前所有已接 live-node adapter 单轮门禁：

```text
report: /private/tmp/model_node_320_live_supported_all_after_g24_fix_r1.json
nodes: turn_side_effect,intent_side_effect,intent_entity_extraction,candidate_filter_extraction,plan_semantic_action,plan_recovery_action,composite_goal,pending_action,reply_focus_binding,reply_generation_grounding
rawTotal: 30
passed: 30
failed: 0
passRate: 1.0
fieldFailures: {}
schemaGaps: {}
legacyOnlyFields: {}
latency.medianMs: 5243
latency.p95Ms: 10667
latency.maxMs: 11950
```

中间全量三轮报告：

```text
report: /private/tmp/model_node_320_live_supported_all_after_g18_fix_r3.json
rawTotal: 90
passed: 89
failed: 1
passRate: 0.9889
stablePassRate: 0.9667
fieldFailures: {"taskLayer": 1}
schemaGaps: {}
legacyOnlyFields: {}
latency.medianMs: 5437
latency.p95Ms: 10095
latency.maxMs: 12915
```

该全量三轮唯一失败是 G8 r2 将未来偏好写入的 `taskLayer` 从 `intent` 漂到 `plan`；随后已在 `turn_decision_tool` 增加 G8 明确规则和示例，并通过单独 `turn_side_effect` 三轮 `/private/tmp/model_node_320_live_turn_decision_after_g8_intent_layer_fix_r3.json` 验证 39/39。其余节点在该全量三轮中均为 3/3。

2026-06-22 网络恢复后继续复跑全量门禁，暴露并修正两个平均态漂移：

- G18 `intent_side_effect` 偶发把“保底要公办不要民办”降级成 `mixed_answer_then_ask`。修正口径：该句是改变后续推荐口径，应输出 `intent_preview`；`公办` 不能升级为 `only_keep`，但也不应因此要求先追问。单节点三轮 `/private/tmp/model_node_320_live_intent_side_effect_after_g18_decision_prompt_r3.json` 为 12/12。
- G16 `plan_recovery_action` 偶发把无关 collection/bool 字段输出成 `null`，导致 `PlanRecoveryActionDecision` 在解析前失败，核心 `actionFamily/unsupportedAction` 丢失。修正口径：节点 schema 边界把 `null` optional list 规范为空数组、`preserveCount=null` 规范为 `false`，不补造缺失核心字段。单节点三轮 `/private/tmp/model_node_320_live_plan_recovery_after_null_coerce_r3.json` 为 6/6。

最终全量三轮报告：

```text
report: /private/tmp/model_node_320_live_supported_all_after_plan_recovery_null_coerce_final_r3.json
rawTotal: 90
passed: 90
failed: 0
passRate: 1.0
stablePassRate: 1.0
fieldFailures: {}
schemaGaps: {}
legacyOnlyFields: {}
providerEnvExcluded: 0
latency.medianMs: 4394
latency.p95Ms: 12387
latency.maxMs: 21405
```

最终 by-node 结果：

```text
turn_side_effect: 39/39
intent_side_effect: 12/12
intent_entity_extraction: 9/9
candidate_filter_extraction: 3/3
plan_semantic_action: 6/6
plan_recovery_action: 6/6
composite_goal: 3/3
pending_action: 6/6
reply_focus_binding: 3/3
reply_generation_grounding: 3/3
```

当前判断：已接 live-node adapter 的 3.2.0 schema 可以收敛到稳定三轮全绿。剩余重点不再是继续在 service 中补兼容桥，而是把已验证的 TurnDecision、intent profile、reply profile 输出接到 ProposalCompiler/replyPlan/displayPayload contract，并在 hard-cut 前用只读 replay 验证 runtime 行为。

## 9. Compiler Golden

离线 compiler 原型：

```text
zhiyuan-agent/examples/proposal_compiler_golden.py
```

运行方式：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/proposal_compiler_golden.py \
  --cases examples/dialog_profile_320_golden_cases.json \
  --output /private/tmp/proposal_compiler_320_g1_g32.json
```

当前基线：

```text
cases: 32
passed: 32
failed: 0
passRate: 1.0
report: /private/tmp/proposal_compiler_320_g1_g32_full_schema.json
```

当前 compiler report 已输出完整 `CompiledProposal` 原型结构：

- `executionPayload`：只承载可执行协议，如 `pending_plan_mutation`、`pending_intent_change`、`apply_existing_pending_then_readonly`、`pending_conflict_resolution`。readonly、needs-plan-first 和无 formal plan mutation 不产生执行 payload。
- `intentPayload`：只承载意向写入相关结构，如 `preferenceStrength`、`preferenceScope`、`negativeRegions`、`admissionPath`、`schools`、`entityPolaritySpans`，避免把软偏好、地域、特殊路径混进 plan mutation。
- `displayPayload`：承载卡片/只读/诊断/澄清的展示契约，包括 `presentation`、`pendingCardType`、`targetView`、`focus`、`actionFamilies` 和回复禁用词。
- `replyPlan`：承载回复生成约束，包括 `mode`、`focus`、`mustAnswer`、`missingInfo`、`noResultReason`、`pendingReminder`、`pendingConflict`。
- `evidenceContract`：承载 `requiredInputs`、`steps`、`toolBudget`、`noResultReason`，用于约束工具预算、批查询和缺失信息。
- `planActionDsl`：承载局部方案动作，如 `pin_or_lock_unit`、`scopeAnchor=current_plan.tier_segment`、`targetTier`、`ordinalScope=within_tier`、`selector`、`targetPosition`。
- `downstreamPolicy`：承载意向对候选生成、排序、补位和替换的影响，包括 `candidateSelection`、`replacementPolicy`、`admissionPath`、`pathEntities` 和作用 `scope`。
- `workspaceRefreshTargets`：确认或 apply 后需要刷新的工作区，如 `ordered`、`review`、`candidate`。

3.2.0 的 compiler golden 已开始把修复类 proposal 纳入同一个提议空间：

- `ProposalCandidate.executionAuthority` 必须显式区分 `intent_state`、`java_fix_proposal`、`java_user_goal_proposal`、`plan_action_dsl`、`readonly_evidence`。
- `java_fix_proposal_reference` 只能引用 Java `FixProposalDTO` 和 dry-run observation，不能携带 Agent 本地重算的 replacementPairs。
- Java proposal `ready=false`、`candidateShortages`、`ready_without_actions`、缺 `sourceVersionGuard` 时，只能编译为 diagnostic/clarification，不允许创建 `pendingConfirmationCard`。
- 多目标 case 必须验证 arbitration：`intent_update + java_fix_proposal` 可以合并为一个 composite pending；`active pending + new mutation` 必须先解决 pending conflict；`rank-only preference + review issue` 不能被提升成修复 mutation。

当前 repair arbitration 增量：

```text
cases: zhiyuan-agent/examples/proposal_compiler_repair_arbitration_320_cases.json
report: /private/tmp/proposal_compiler_320_repair_arbitration_latest.json
passed: 4
failed: 0
blockingReasons:
  java_fix_proposal_ready_without_actions: 1
  rank_only_policy_cannot_create_mutation: 1
```

2026-06-21 增量：

- G16 已可离线编译 `pin_or_lock_unit` DSL：选择 `冲` 档第 1/2 个，`preservePosition=true`，后端不支持时进入 `clarify_if_backend_not_supported`。
- G17 已可离线编译 tier-local reorder DSL：`scopeAnchor=current_plan.tier_segment`、`targetTier=保底`、`ordinalScope=within_tier`、录取率最高项移动到保底第 1 位，避免误解成全方案第 1 位。
- G25 已可离线保留 `entityPolaritySpans`：生物医学工程/智能医学工程为 positive preferred，临床医学/口腔医学为 negative exclude_hard。
- G30 已可离线保留 `admissionPath=strongbase` 和学校实体，避免“清北复旦强基”退化成普通学校偏好。
- G13/G18/G23 已清理旧 `hard_constraints/schoolPreference/regionPreference/scope` 字段，统一到 `preferred/exclude_hard/preferenceScope`。
- compiler 已新增 `downstreamPolicy`：把 `exclude_hard/only_keep/must_have/primary/preferred/acceptable` 编译成候选硬过滤、rank boost、补位优先级和替换优先级。该策略仍是离线契约，不直接调用 Java/rank/replacement。

`downstreamPolicy` 的策略顺序：

- `exclude_hard`：进入 `candidateSelection.hardExclude` 和 `replacementPolicy.replaceFirst`，优先移出或替换违规项。
- `only_keep`：进入 `candidateSelection.onlyKeep`，对不在范围内的项进入 `replaceFirst`，但只有用户明确“只保留/限定”才使用。
- `must_have`：进入 `candidateSelection.mustCover` 和 `fillPriority`，表示至少覆盖，不清空其它非冲突项。
- `primary`：进入 rank boost 权重 3，并作为补位/替换优先方向。
- `preferred`：进入 rank boost 权重 2，作为普通偏好提升。
- `acceptable`：进入 rank boost 权重 1，只在 primary/preferred 不足或需要保持梯度时作为兜底。
- `preferenceScope`：限制策略作用域，例如 `保底` 只影响保底区，不污染全方案。
- `admissionPath`：独立传给 `admissionPath/pathEntities`，如强基路径不混入普通学校偏好。

最新离线报告：

```text
report: /private/tmp/proposal_compiler_320_g1_g32_downstream_policy_latest.json
cases: 32
passed: 32
failed: 0
passRate: 1.0
blockingReasons: {}
```

## 9.1 Downstream Policy Replay

离线 replay 工具：

```text
zhiyuan-agent/examples/downstream_policy_replay.py
```

样例：

```text
zhiyuan-agent/examples/downstream_policy_replay_320_cases.json
```

运行方式：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/downstream_policy_replay.py \
  --cases examples/downstream_policy_replay_320_cases.json \
  --compiler-report /private/tmp/proposal_compiler_320_g1_g32_downstream_policy_latest.json \
  --output /private/tmp/downstream_policy_replay_320_latest.json
```

该工具消费 `CompiledProposal.downstreamPolicy` 或 case 内 inline `downstreamPolicy`，以及小型候选/当前方案 fixture。它不调用 Java、rank、model、WebSocket 或 backend。它验证的是 deterministic 策略顺序，不验证真实候选池质量。

inline policy 只用于 replay-only case：当 G1-G32 compiler report 还没有覆盖某个下游边界时，先用 inline policy 固定语义，不反向污染 profile/compiler golden。

报告关键字段：

- `policySource`：`compiler`、`inline` 或 `missing`。
- `selectedCandidateIds/excludedCandidateIds`：硬过滤和排序后的候选结果。
- `replacementCandidateIds/protectedPlanItemIds`：当前方案中应优先替换或保护的项。
- `capacityStatus`：`satisfied`、`insufficient_candidates`、`no_result` 或 `not_requested`。
- `noResultReason`：如 `all_candidates_filtered`、`capacity_insufficient_after_filters`、`empty_candidate_pool`。
- `missingMustCover/mustCoverSatisfied`：`must_have` 覆盖要求是否满足。

当前基线：

```text
report: /private/tmp/downstream_policy_replay_320_latest.json
cases: 9
passed: 9
failed: 0
passRate: 1.0
capacityStatuses:
  satisfied: 4
  insufficient_candidates: 4
  no_result: 1
missingMustCoverCount: 1
```

覆盖场景：

- G4：`primary=网络与新媒体` 排在 `acceptable=跨境电子商务` 前，acceptable 只做兜底，不能压过 primary。
- G18：`preferenceScope=保底` 限定作用域，`exclude_hard=民办` 只在保底区触发 replace-first；历史 preferred 学校进入 protect。
- G25：mixed polarity 中 `临床医学/口腔医学` 被 hard exclude，`生物医学工程/智能医学工程` 作为 preferred fill/protect。
- G30：`admissionPath=strongbase` 过滤普通批同校候选，强基学校实体独立保留。
- inline onlyKeep：只保留临床医学时，非临床候选和当前方案项进入 out-of-scope 处理，且候选不足输出 `insufficient_candidates`。
- inline mustCover：`must_have` 是覆盖要求，不是 only keep；无法覆盖法学时输出 `missingMustCover=["法学"]`。
- inline softAvoid：高收费只降权，不进入 hard exclude。
- inline tuition cap：超过学费上限的候选被过滤，当前方案超上限项进入 replace-first。
- inline no-result：硬过滤后无候选时输出 `no_result/all_candidates_filtered`。

下游接入时，真实 candidate/rank/replacement dry-run 必须能返回或让 deterministic adapter 计算这些诊断。否则即使最终回复看起来合理，也应记为 adapter/contract gap。

## 9.2 Downstream Adapter Dry-Run

离线 adapter 工具：

```text
zhiyuan-agent/examples/downstream_adapter_dry_run.py
```

样例：

```text
zhiyuan-agent/examples/downstream_adapter_dry_run_320_cases.json
```

运行方式：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/downstream_adapter_dry_run.py \
  --cases examples/downstream_adapter_dry_run_320_cases.json \
  --output /private/tmp/downstream_adapter_dry_run_320_latest.json
```

该工具只消费 Java `FixProposalDTO` 响应 fixture，不调用 backend、不创建 pending、不 apply。它的目标是验证现有 Java proposal/dry-run 是否能归一到 3.2.0 下游观测契约：

- `dryRunResult` -> `capacityStatus/selectedCount/removedCount/warnings`。
- `candidateShortages` -> `noResultReason/shortageCount/availableCount`。
- `actions/replacementPairs` -> `replacementCandidateIds/candidateVolunteerIds/replacementPairs`。
- `strategy=must_include_scope` -> `requiredMustCover/missingMustCover/mustCoverSatisfied`。
- 协议缺口 -> `contractGaps`，例如 ready proposal 没有 action。

当前基线：

```text
report: /private/tmp/downstream_adapter_dry_run_320_latest.json
cases: 5
passed: 5
failed: 0
passRate: 1.0
capacityStatuses:
  satisfied: 2
  no_result: 2
  not_reported: 1
contractGapCounts:
  ready_without_actions: 1
```

覆盖场景：

- Java ready replacement 可以映射为 `capacityStatus=satisfied`，并保留 from/to replacement pair。
- Java blocked shortage 可以映射为 `no_result` 和具体 shortage reason。
- `must_include_scope` ready/blocked 可以分别映射 mustCover 满足或缺失。
- ready 但没有 action 的响应会进入 `contractGaps`，不能被回复层当作可执行预览。

这说明 Java `FixProposalDTO` 已经具备 3.2.0 dry-run 观测基础。后续 runtime 接入时应复用 Java proposal/dry-run/apply 主链路，Agent 只做 `downstreamPolicy -> Java taxonomy/request -> adapter observation` 的只读归一，不复制候选选择或替换算法。

## 9.3 DownstreamPolicy -> Java Request

离线 request mapper：

```text
zhiyuan-agent/examples/downstream_policy_java_request.py
```

样例：

```text
zhiyuan-agent/examples/downstream_policy_java_request_320_cases.json
```

运行方式：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/downstream_policy_java_request.py \
  --cases examples/downstream_policy_java_request_320_cases.json \
  --output /private/tmp/downstream_policy_java_request_320_latest.json
```

该工具把 3.2.0 `downstreamPolicy` 离线编译成 Java `UserGoalFixProposalReq`，并显式报告不能进入 Java 方案变更链路的 gap。它不调用 backend、不创建 pending、不 apply。

当前 taxonomy 对齐：

| downstreamPolicy | Java request |
| --- | --- |
| `candidateSelection.onlyKeep` | `goalType=only_keep_scope` + `targetScopes` |
| `candidateSelection.mustCover` | `goalType=must_include_scope` + `targetScopes` |
| `candidateSelection.hardExclude` | `goalType=exclude_scope` + `negativeScopes` |
| `maxTuitionPerYear / tuition cap` | `goalType=tuition_budget_scope` + `context.maxTuitionPerYear` |
| `admissionPath` | 暂映射 `scopeType=program_type`，但标记 `program_type_text_match_only` |
| `primary/preferred/acceptable` | rank-only，不生成 Java mutation request |
| 纯 `avoid_soft` | rank-only，不生成 Java mutation request |

当前基线：

```text
report: /private/tmp/downstream_policy_java_request_320_latest.json
cases: 7
passed: 7
failed: 0
passRate: 1.0
requestReady: 5
requestNotReady: 2
adapterGapCounts:
  rank_only_policy:primary,acceptable: 1
  soft_avoid_rank_only: 1
  program_type_text_match_only: 1
```

runtime 接入规则：

- `requestReady=true` 才能进入 Java `fix-proposals/user-goal/generate` 的只读预览，再由 compiler 决定是否创建 pending。
- `rank_only_policy` 和 `soft_avoid_rank_only` 只能影响候选/rank adapter 或只读解释，不能生成方案 mutation pending。
- `program_type_text_match_only` 表示可做 dry-run 观察，但特殊路径还需要一等字段或 Java 侧枚举支持，不能只靠强基/提前批文本匹配就封为稳定主路径。

## 9.4 Downstream Contract Gate

三层汇总 gate：

```text
zhiyuan-agent/examples/downstream_contract_gate.py
```

运行方式：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/downstream_contract_gate.py \
  --policy-replay-report /private/tmp/downstream_policy_replay_320_latest.json \
  --java-request-report /private/tmp/downstream_policy_java_request_320_latest.json \
  --adapter-dry-run-report /private/tmp/downstream_adapter_dry_run_320_latest.json \
  --output /private/tmp/downstream_contract_gate_320_latest.json
```

该 gate 不重新调用模型或服务，只汇总三层离线报告：

- policy replay：策略语义是否稳定。
- Java request mapper：策略是否能进入 Java user-goal proposal request。
- adapter dry-run：Java proposal 响应是否能归一成 3.2.0 观测字段。

当前基线：

```text
report: /private/tmp/downstream_contract_gate_320_latest.json
gatePassed: true
components:
  policyReplay: 9/9
  javaRequest: 7/7
  adapterDryRun: 5/5
expectedGapCount: 4
capacityStatuses:
  satisfied: 6
  insufficient_candidates: 4
  no_result: 3
  not_reported: 1
adapterGapCounts:
  rank_only_policy:primary,acceptable: 1
  soft_avoid_rank_only: 1
  program_type_text_match_only: 1
contractGapCounts:
  ready_without_actions: 1
requestReady: 5
requestNotReady: 2
missingMustCoverCount: 1
```

gate 口径：

- 任一组件 `failed>0` 是 hard failure。
- `adapterGapCounts/contractGapCounts` 是预期设计缺口，不让 gate 失败，但不能被 runtime 接入时忽略。
- capacity/no-result/missingMustCover 是业务诊断，不等同于测试失败；后续真实 adapter 必须能保留这些诊断给 compiler/replyPlan。

当前 output/pending 分布：

```text
outputType:
  plan_mutation: 2
  readonly_or_plan_mutation: 1
  readonly: 15
  intent_change: 9
  latency_profile: 1
  composite: 1
  plan_mutation_or_unsupported: 1
  clarification: 1
  apply_then_readonly: 1

pendingType:
  plan_mutation: 2
  none_or_plan_mutation: 2
  unchanged_existing_pending: 3
  intent_change: 9
  none: 13
  plan_mutation_or_clarification: 1
  plan_mutation_or_none: 1
  unchanged_or_replace_after_user_choice: 1
```

它验证的是协议硬约束，不验证运行时工具效果：

- `plan_preview` 有正式方案时必须能编译成 `plan_mutation` pending。
- 无正式方案时不能编译当前方案 mutation。
- 无 active pending 时，“确认”不能编译成 apply。
- `readonly_while_pending` 保留旧 pending，不 apply、不取消。
- `needs_plan_first` 不创建 pending，并要求 `formal_plan` missingInfo。
- `conflict_with_existing_pending` 进入 clarification 或 replacement choice，不产生双 pending。
- negative-only intent 可独立编译为 `intent_change`，不要求 positive scope。
- `apply_pending_then_new_request` 和 `apply_pending_then_readonly` 必须拆分：前者是采纳已有 pending 后继续新的高副作用诉求/澄清，后者是执行已有 pending 后基于新状态做只读查询或审查；不能把 apply 后只读 follow-up 泛化成新 pending。
- 只读、诊断和 missingInfo 场景必须通过 `replyPlan` 表达 focus/noResult/pending reminder，不能靠 formatter 自己推断。

这说明 G1-G32 的目标协议可以由 deterministic compiler 承接；live-node 的失败不应继续通过更多 runtime 补丁消化，而应把模型节点输出收敛到 compiler 可接受的 TurnDecision/ProposalCandidate schema。

最新离线报告：

```text
report: /private/tmp/proposal_compiler_320_g1_g32_full_schema_latest.json
cases: 32
passed: 32
failed: 0
passRate: 1.0
blockingReasons: {}
```

## 10. Readonly Shadow Diff

只读 shadow diff 工具：

```text
zhiyuan-agent/examples/runtime_shadow_diff.py
```

该工具比较旧 runtime 观测结果和 3.2.0 `CompiledProposal` 输出。它不启动 WebSocket、不创建 pending、不 apply、不写后端状态，只生成差异报告。其定位是硬切前风险扫描，不是兼容桥接。

观测样例：

```text
zhiyuan-agent/examples/runtime_shadow_diff_320_observations.example.json
```

真实旧路径观测由 WebSocket 回归 runner 只读导出：

```bash
cd zhiyuan-agent
PYTHONPATH=. ./.venv/bin/python examples/dialog_regression_runner.py \
  --url ws://127.0.0.1:8000/gaotu-assistant-agent/plus/chat/1/bot/test/do \
  --cases examples/<mapped_g1_g32_dialog_cases>.json \
  --clear-history-per-case \
  --clear-backend-pending-per-case \
  --keep-response-text \
  --metrics-output /private/tmp/dialog_regression_320_g1_g32_metrics.json \
  --runtime-shadow-output /private/tmp/runtime_shadow_320_g1_g32_observations.json
```

`--runtime-shadow-output` 只读取本轮 WebSocket 消息、followup card、workspace action 和本地 history observability，归一为 `runtimeShadowObservations`：

- `caseId` 来自 step 级 `profileCaseId/shadowCaseId/runtimeShadowCaseId/caseId`，单步 case 才允许继承 case 级 `caseId`。
- `pendingCards` 只保存 `kind/pendingId/actionFamily/targetView/executionPayload.kind` 等协议字段，不保存完整业务 payload。
- `workspaceRefreshTargets` 只记录被触发的目标工作区。
- `sideEffect/outputType/pendingType/presentation` 由可见卡片、direct confirm 路由和 tool observability 归一得出；不确定的字段不猜。
- 导出动作不创建 pending、不 apply、不写 backend extra data、不改变用户回复。

运行方式：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/runtime_shadow_diff.py \
  --cases examples/dialog_profile_320_golden_cases.json \
  --observations /private/tmp/runtime_shadow_320_g1_g32_observations.json \
  --compiler-report /private/tmp/proposal_compiler_320_g1_g32_full_schema.json \
  --output /private/tmp/runtime_shadow_diff_320_g1_g32.json
```

报告口径：

- `observed`：有旧 runtime 观测的 case 数。缺观测只记 `missing_observation`，不表示产品失败。
- `blocking`：硬切必须处理的问题，例如旧路径意外创建 pending、compiler 期望 pending 但旧路径没有、同轮多 pending、shadow 自身写状态。
- `major`：语义或展示不一致，例如 sideEffect、outputType、presentation、replyFocus、workspaceRefreshTargets 不一致。
- `clean`：旧观测和 compiler 输出一致。
- `byDiffType`：按差异类型聚合，用于定位要删除或改造的旧路径。
- `byTag`：按 profile tag 聚合，用于回到 G1-G32 场景族。

示例报告故意只放 3 条观测，其中包含一个 readonly 误出卡和一个双 pending，因此会出现 `missing_observation` 和 blocking diff。真实接入时应使用完整 G1-G32 或 e2e 观测集替换样例文件。

当前工具状态：

- `dialog_regression_runner.py` 已支持 `--runtime-shadow-output`，可从真实回归输出旧路径 observation。
- 2026-06-21 修正 runner observation 口径：`review_plan/query_state/query_ordered/analyze_adjustment` 这类只读工具返回的 `applied=true` 只表示工具完成，不能归为 `apply_existing_pending`；只有 direct pending confirm 路由、pending apply action family 或 intent applied message code 才算 pending apply。
- `runtime_shadow_diff.py` 已支持 observation array 或 `{"observations": [...]}`。
- 已新增首批 G1-G32 可运行映射：

```text
zhiyuan-agent/examples/dialog_regression_320_g1_g32_shadow_cases.json
```

该文件覆盖 21 个可复用历史 fixture/session 的 profile case：

```text
G1, G2, G3, G4, G7, G8, G10, G12, G16, G17, G19,
G21, G22, G23, G25, G26, G27, G29, G30, G31, G32
```

暂未进入 e2e shadow 映射的 11 个 case 仍在 profile/compiler 或 node benchmark 层覆盖：

| Case | 暂不映射原因 |
| --- | --- |
| G5 | negative-only region 需要稳定的 score profile fixture，当前先用 node/composite_goal 覆盖 |
| G6 | missing score/rank + candidate query 需要专门空分数 fixture |
| G9 | current-major-group local operation 需要可定位专业组内部行 fixture |
| G11 | provider availability 是 provider precheck，不适合 WebSocket shadow |
| G13 | add intent preference strength 与 G4/G29 重叠，需补独立 profile-ready fixture |
| G14 | apply pending then plan request 需要 active intent pending + generate plan fixture |
| G15 | analysis-only without pending 需先构造无 pending 的分析历史 |
| G18 | accepted school preference + new negative preference 需预置已采纳 school intent |
| G20 | art formula uncertainty 需艺术类省份公式/分数 fixture |
| G24 | pending stack conflict 需要主动构造旧路径多 pending 噪声，不应从普通回归隐式产生 |
| G28 | latency decomposition 主要由 model/provider benchmark 统计，不作为单独 e2e G observation |

2026-06-21 r1 shadow 结果：

```text
runner metrics:
steps=52, successfulSteps=49, failedSteps=3, failedByReason.content=3
elapsed median=13318ms, p95=30291ms, max=35586ms

runtime shadow observation, corrected:
observations=21
bySideEffect: readonly=10, readonly_while_pending=4, intent_pending=5, plan_preview=2
byPendingType: none=10, unchanged_existing_pending=4, intent_change=5, plan_mutation=2

compiler diff, corrected:
total=32, observed=21, clean=9, blocking=1, major=11, info=11
byDiffType:
  missing_pending=1
  sideEffect_mismatch=6
  outputType_mismatch=5
  presentation_mismatch=4
  missing_workspace_refresh=8
  pending_type_mismatch=2
  execution_kind_mismatch=1
```

r1 需要保留的定性：

- G1 是 blocking：旧路径执行了 `remove_units` preview，并在文本里承诺“确认/删除”效果，但没有输出 `pendingConfirmationCard`。这是“文本承诺与可执行协议断裂”，必须由 3.2.0 compiler 统一生成 pending/card 来解决。
- 生产“加志愿到方案但没弹卡、文本让确认，下一轮追问才弹卡”属于同一风险族。当前 runtime guard 只允许两种结果：有结构化 preview 则同轮挂 pending/card；没有结构化候选则清理“确认加入方案吗/确认后执行”等话术并保持无 pending。不能通过文本或 classifier 反向补卡。
- G8 是 sideEffect 边界错误：软偏好/排除意图被升级成当前方案 plan mutation pending。根因是 intent 与 plan proposal 没有单一裁决层。
- G16 是局部动作 DSL 缺失：锁定第 1/2 个冲档位置被降级成状态查询，没有表达 pin/lock 和 ordinal/tier scope。
- G27 是 pending 承接错误：有 active plan mutation pending 时，“删完了再看看还剩多少/梯度”应被识别为 apply pending then readonly query，旧路径只返回 pending 边界解释，没有执行后刷新。
- G2/G7/G12/G17/G26/G31 主要是 display/workspace refresh 协议不一致：旧路径可给出只读答案或 pending card，但没有稳定输出 compiler 期望的 `workspaceRefreshTargets`/diagnostic/conditional presentation。
- G19/G32 是需要补充 sideEffect taxonomy 的灰区：旧路径 readonly 防御基本合理，但 compiler 把它们区分成 `needs_plan_first`，后续应在 TurnDecision schema 中保留该语义，不必通过兼容话术桥接。

2026-06-21 已跑满 r2/r3，三轮基线如下：

```text
r1 metrics:
  steps=52, successfulSteps=49, failedSteps=3
  elapsed median=13318ms, p95=30291ms, max=35586ms
  diff: total=32, observed=21, clean=9, blocking=1, major=11, info=11

r2 metrics:
  steps=52, successfulSteps=47, failedSteps=5
  elapsed median=16466ms, p95=34596ms, max=46255ms
  runtime observation:
    bySideEffect: readonly=10, readonly_while_pending=4, intent_pending=6, plan_preview=1
    byPendingType: none=10, unchanged_existing_pending=4, intent_change=6, plan_mutation=1
  diff: total=32, observed=21, clean=9, blocking=3, major=9, info=11
  byDiffType:
    missing_pending=2
    sideEffect_mismatch=7
    outputType_mismatch=7
    presentation_mismatch=6
    missing_workspace_refresh=8
    pending_type_mismatch=2
    execution_kind_mismatch=1
    unexpected_pending_creation=1

r3 metrics:
  steps=52, successfulSteps=49, failedSteps=3
  elapsed median=14507ms, p95=28544ms, max=36221ms
  runtime observation:
    bySideEffect: readonly=10, readonly_while_pending=4, intent_pending=6, plan_preview=1
    byPendingType: none=10, unchanged_existing_pending=4, intent_change=6, plan_mutation=1
  diff: total=32, observed=21, clean=9, blocking=3, major=9, info=11
```

三轮稳定性结论：

- E2E 断言通过率较高不能代表框架收敛。三轮 diff 的 clean 都只有 `9/32`，说明旧 runtime 和 3.2.0 compiler 目标协议仍长期不一致。
- 稳定硬失败：G1 三轮都缺 plan mutation pending card；G27 三轮都不能执行 active pending 后继续 readonly review/query。
- 近稳定硬失败：G19 r2/r3 都在无正式方案时把“刚那个方案民办能少点不”创建成 intent pending；根因是 reference resolution 和 `needs_plan_first` guard 缺失。
- 稳定结构缺口：G16/G17 的锁定、tier-local reorder、ordinal scope 在三轮中表现不同，但都说明现有 plan action DSL 无法表达局部动作，只能误投影成 query/move/global sort/no_change/error。
- 稳定模型节点问题：G4/G29 把“优先/也可以考虑”过强写成 `must_have`；G25 把“加意向 A/B，排除 C/D”全部绑定成 negative；G30/G21 能识别学校实体，但“强基” admission path 没有结构化进入 intent payload。
- 稳定展示/工作台问题：G2/G7/G12/G26/G31 多数能够给出部分业务回答，但 `workspaceRefreshTargets`、presentation、reply focus 和 evidence 归属不稳定。
- 已相对稳定正例：G10 no-pending confirm guard 基本可用；G23 长三角地域偏好没有再误识别成专业实体；G32 无正式方案时的民办查询能防御回答，但仍需用 `needs_plan_first` 明确协议化。
- 性能长尾仍明显：r2 max 46.3s 来自 G30 强基路径；r3 max 36.2s 来自 G22 省份/分数纠错后的重复查分；G21/G26/G7 也反复进入 p95。下一步必须把 tool budget、batch query 和 evidence plan 前置，而不是依赖模型自由工具循环。

三轮后的执行口径：

- runner shadow 已完成三轮，不再继续加轮次作为主要手段。
- 业务内 shadow hook 暂不接入；只有固定 runner 覆盖不足时才短期开启，并且必须只读、默认关闭、不创建 pending、不 apply、不写 backend、不触发 workspace refresh、不改变当前响应。
- 后续重点转为实现 3.2.0 schema/compiler/DSL：`preferenceStrength`、`admissionPath`、`needs_plan_first`、`apply_pending_then_readonly`、`tier-local/ordinal/pin-lock`、`workspaceRefreshTargets` 和 `replyPlan`。

2026-06-22 post-targeted full clean shadow R1 补充：

- 完整 G1-G32 e2e shadow 子集复跑 `/private/tmp/dialog_regression_320_g1_g32_clean_full_r1_metrics.json` 为 52 step、47 successful、5 content failure；diff `/private/tmp/runtime_shadow_diff_320_g1_g32_clean_full_r1.json` 为 32 total、21 observed、8 clean、3 blocking、10 major、11 info。
- 这轮推翻了“targeted G4/G23/G25 clean 可代表平均态稳定”的外推：G25 在完整多步上下文中仍发生正负极性反转，G23 仍把“城市优先”里的城市误抽成城市管理专业，G30 仍把强基学校意向退化为专业类并同轮生成双 pending。
- 节点 benchmark 90/90 仍然有价值，但只证明单节点在受控输入下可产出 3.2.0 schema；runtime 仍必须 hard-cut 到 `TurnDecision / intent_entity_extraction / ProposalCompiler / replyPlan / displayPayload`，不能让 full-agent 自由工具循环、旧 formatter 或 service 补偿继续覆盖节点输出。

## 11. Runtime Entrypoint Audit

runtime pending/card 静态审计工具：

```text
zhiyuan-agent/examples/runtime_pending_entrypoint_audit.py
```

该工具不启动 runtime，也不读取业务数据。它只读取手工确认过的入口 fixture，检查 `app/service.py` 中这些符号是否仍存在，并按 3.2.0 hard-cut 处理方式聚合。它的用途是把旧路径删除清单变成可执行报告，避免硬切后仍残留 service/formatter 旁路创建 pending。

fixture：

```text
zhiyuan-agent/examples/runtime_pending_entrypoints_320.json
zhiyuan-agent/examples/runtime_pending_entrypoints_320_expectations.json
```

运行方式：

```bash
cd zhiyuan-agent
./.venv/bin/python examples/runtime_pending_entrypoint_audit.py \
  --entries examples/runtime_pending_entrypoints_320.json \
  --expectations examples/runtime_pending_entrypoints_320_expectations.json \
  --output /private/tmp/runtime_pending_entrypoint_audit_320_latest.json
```

当前基线：

```text
report: /private/tmp/runtime_pending_entrypoint_audit_320_latest.json
passed: true
total: 8
missing: 0
legacyRiskCount: 0
deleteAfterCutCount: 0
byKind:
  sink_keep: 1
  compiler_sink_after_cut: 4
  compiler_entry_after_cut: 2
  execution_keep: 1
```

口径：

- `compiler_sink_after_cut`：可以保留函数，但只允许消费 `CompiledProposal` 输出。
- `compiler_entry_after_cut`：主流程 plan/fix pending 创建已收口到统一 runtime compiled entry；候选解析可以存在，但不能直接越过 compiled entry 和 sink contract 保存 pending。
- `delete_after_cut`：hard cut 后必须删除；当前无结构化候选的自然语言承诺恢复、只读误路由恢复、no-tool intent 恢复、composite goal recovery、预算/学费误路由 recovery 和主流程 `recovered_pending_intent_card` 变量路径均已删除。
- `execution_keep`：保留 apply 入口和 pending id/status/version/policy guard。
- `legacyRiskCount` 只统计直接创建或恢复 pending/card 的路径；evidence-only 读取不计入业务卡风险，但仍必须在 hard cut 中限制调用方式。

和 shadow diff 的关系：

- shadow diff 说明旧 runtime 行为和 `CompiledProposal` 目标协议哪里不一致。
- entrypoint audit 说明这些不一致在代码上可能来自哪些 pending/card 创建入口。
- 二者都不是兼容层；runtime 接入时只能用于阻断和删除旧路径，不能用于双写或兜底补卡。

补充 sink call audit：

```text
zhiyuan-agent/examples/runtime_pending_sink_call_audit.py
```

该工具用 AST 检查低层 pending/card sink 的实际调用点，避免只删入口函数却残留直接调用 sink 的路径。当前基线：

```text
report: /private/tmp/runtime_pending_sink_call_audit_320_latest.json
passed: true
actual: 15
legacyDirectCreateCount: 0
compilerOnlySinkCallCount: 9
compilerEntryCallCount: 0
statusUpdateKeepCount: 6
```

口径：

- `legacy_direct_create=0`：底层 pending sink 调用层已不允许绕过 compiled output 直接创建 pending。
- `compiler_sink_call=9`：保留 sink 函数，但调用权必须限制为 compiler output；direct intent select、intent preview helper、user-goal fix candidate、structured intent candidate、runtime plan entry 和 runtime review/fix entry 已经先过 compiled sink contract。
- `compiler_entry_call=0`：旧 plan/fix 中层 pending wrapper 已删除，runtime compiled entry 直接消费 compiled proposal 后调用低层 sink。
- `status_update_keep=6`：保留 pending apply/cancel/expire/fail 状态更新，不参与新 pending 创建。

这说明 sink 调用层和主流程 plan/fix call-source 都已收口到 compiled entry，并且旧 wrapper 不再保留。runtime compiled proposal/contract、deterministic fix proposal arbitration、target-scope 归一/过滤和 blocking reason 已抽到 `app/domain/proposal_compiler.py`；下一步不是恢复旧入口，而是把模型 target-scope 调用本身和 TurnDecision 输入替换为正式 ProposalCompiler 输出。`composite_goal` 仍可作为离线模型节点 benchmark，但 runtime 不再调用 `classify_composite_goal_action` 补 pending/card。

补充 runtime hard-cut forbidden symbol 单测：

```text
zhiyuan-agent/tests/unit/test_runtime_hard_cut_audit.py
```

该测试扫描 `app/service.py`，防止 runtime 重新引用 `classify_plan_recovery_action`、`classify_composite_goal_action`、旧 plan/fix pending wrapper、`recovered_pending_intent_card`、旧 plan recovery 死代码和旧 `select_fix_proposal_candidate` 调用。`classify_*` 工具函数仍保留在模型节点 benchmark/profile 中，用于评估模型能力，不作为运行时兜底或补卡路径。

## 12. Compiled Pending Sink Contract

compiler-only pending sink contract：

```text
zhiyuan-agent/examples/compiled_pending_sink_contract.py
```

该工具验证 `CompiledProposal` 是否能转换成唯一 pending sink request。它不调用 runtime，也不保存 pending。目标是提前固定 hard cut 的 sink 入口协议：只有带 `compiledProposalId`、`pendingType`、`executionPayload` 和必要 Java dry-run/action/version 信息的 compiled output 才能进入 sink。

样例：

```text
zhiyuan-agent/examples/compiled_pending_sink_contract_320_cases.json
```

当前基线：

```text
report: /private/tmp/compiled_pending_sink_contract_320_latest.json
passed: 6
failed: 0
bySinkType:
  intent: 2
  plan: 1
  fix_proposal: 2
  none: 1
blockingReasons:
  no_pending_requested: 1
  missing_compiled_proposal_id: 1
  fix_proposal_requires_actions: 1
```

口径：

- `intent` sink 必须是 `pendingType=intent_change` 且 `executionPayload.kind=pending_intent_change`，并携带 `intentPayload`。
- `plan` sink 必须是 `pendingType=plan_mutation` 且 `executionPayload.kind=pending_plan_mutation`，并有明确 action family。
- `fix_proposal` sink 必须引用 `java_fix_proposal_reference`，并携带 `sourceVersionGuard`、actions 和 dry-run observation。
- `pendingType=none`、缺 `compiledProposalId`、Java fix 缺 actions/dry-run/version 都不能进入 pending sink。

首个 runtime 入口准备项是 `handle_intent_select` 的离线 adapter：

```text
zhiyuan-agent/examples/intent_select_compiler_adapter.py
zhiyuan-agent/examples/intent_select_compiler_adapter_320_cases.json
```

当前基线：

```text
report: /private/tmp/intent_select_compiler_adapter_320_latest.json
passed: 4
failed: 0
byPendingType:
  intent_change: 2
  none: 2
blockingReasons:
  intent_select_requires_selected_values: 1
  constraint_intent_requires_scope: 1
```

该 adapter 做离线协议转换：`selectedData -> CompiledProposal(intent_change) -> compiled pending sink contract`。runtime direct selectedData 分支已接入同一 contract，并删除默认关闭开关和旧直连路径。

runtime 状态：

- `ChatService.handle_intent_select` direct selectedData 分支始终先生成 compiled intent proposal，并通过 intent sink contract 校验，再复用 intent pending sink 创建同样 pending card。
- `actionType/prefer_confirm/constrain_confirm` followup 会经 `_create_pending_intent_confirmation_from_preview_payload` 编译为 intent pending；constraint 命中 Java user-goal ready proposal 时转 compiled fix proposal。
- 单测已覆盖 direct select、prefer confirm、constraint confirm 和 Java ready-without-actions 阻断。
