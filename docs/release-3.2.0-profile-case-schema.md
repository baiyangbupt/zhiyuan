# Release 3.2.0 Profile Case Schema

本文定义 3.2.0 离线模型能力 profile 与 compiler golden 共用的 case 契约。该契约不进入 runtime 主裁决，不作为 shadow router，也不用于生产双写；它只用于把模型理解、结构化计划、回复生成、fixture 前置状态和断言分开评估。后续可以复用该契约做只读 shadow diff，但不能改变用户响应、pending、apply 或 workspace refresh。

## 1. Case 顶层字段

```json
{
  "caseId": "G1-exclude-current-plan-english-major",
  "source": "3.1.1 P0-3",
  "priority": "P0",
  "tags": ["mixed_intent_plan", "plan_preview", "pending_protocol"],
  "prompt": "不要英语相关专业，当前方案里有的话也删掉",
  "historyContext": [],
  "fixtureContract": {
    "type": "formal_plan_present",
    "sessionTemplate": "has_english_major_in_ordered_plan",
    "requiredState": ["orderedPlan", "candidatePool"],
    "forbiddenState": []
  },
  "planningStateProfile": {
    "scoreReady": true,
    "formalPlanPresent": true,
    "candidatePoolPresent": true,
    "pendingExists": false
  },
  "expectedTurnDecision": {
    "taskLayer": "plan",
    "sideEffect": "plan_preview",
    "scopeAnchor": "current_plan",
    "scenario": "atomic_mutation",
    "targetIssue": ["major_scope"],
    "replyMode": ["concise", "confirmable_preview"],
    "missingInfo": []
  },
  "forbiddenDecisions": [],
  "expectedEvidencePlan": {
    "requiredInputs": ["formal_ordered_plan"],
    "steps": [],
    "toolBudget": {"maxToolCalls": 4, "batchPreferred": true},
    "noResultReason": null
  },
  "expectedProposal": {
    "type": "plan_mutation",
    "pendingType": "plan_mutation",
    "actionFamilies": ["remove_units", "apply_fix_proposal"],
    "intentPayloadAllowed": true,
    "requiresConfirmation": true
  },
  "expectedPending": {
    "type": "pendingConfirmationCard",
    "required": true,
    "targetView": "ordered",
    "workspaceRefreshTargets": ["ordered"]
  },
  "replyQualityAssertions": {
    "mustAnswer": [],
    "mustMentionAny": [],
    "mustNotMention": []
  },
  "metricsTags": ["sideEffect_accuracy", "pending_type_accuracy"]
}
```

## 2. 字段说明

| 字段 | 含义 |
| --- | --- |
| `caseId` | 稳定唯一 ID，不随 prompt 改写变化 |
| `source` | 来源，例如 `3.1.1 P0-3`、`full_journey_round1`、`autoexplorer` |
| `priority` | `P0/P1/P2/observe` |
| `tags` | 场景标签，用于按问题族聚合 |
| `prompt` | 当前用户输入 |
| `historyContext` | 进入当前轮前的关键上下文，允许空数组 |
| `fixtureContract` | 后端/会话必须满足的前置状态 |
| `planningStateProfile` | 离线 profile 时使用的状态摘要，不要求保存完整 backend JSON |
| `expectedTurnDecision` | 模型或 compiler 应输出的唯一 turn 决策 |
| `forbiddenDecisions` | 明确禁止的错误裁决 |
| `expectedEvidencePlan` | 取证计划和缺参/no-result 约束 |
| `expectedProposal` | 期望 proposal 类型，不要求提前写死底层全部 payload |
| `expectedPending` | 是否应有 pending/card、主展示目标工作区，以及确认/apply 后需要刷新的工作区 |
| `replyQualityAssertions` | 回复质量断言，聚焦用户问题和禁用内部词 |
| `metricsTags` | 参与统计的指标维度 |

## 3. 枚举

### taskLayer

```text
pending
policy
explore
intent
plan
mixed
clarification
```

### sideEffect

```text
readonly
readonly_while_pending
intent_pending
plan_preview
composite_pending
apply_existing_pending
apply_pending_then_new_request
apply_pending_then_readonly
cancel_existing_pending
clarification
conflict_with_existing_pending
needs_plan_first
```

### scopeAnchor

```text
general
future_reference
current_plan
current_major_group
candidate_pool
current_profile
special_path
unknown
```

### fixture type

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

### root cause labels

```text
product_defect
model_capability
schema_gap
compiler_gap
reply_generation_gap
fixture_mismatch
assertion_noise
provider_env
latency_longtail
```

## 4. 断言边界

Profile case 不应把具体中文回复模板写死。优先断言：

- task layer 是否正确。
- sideEffect 是否正确。
- scopeAnchor 是否正确。
- 是否生成或不生成 pending。
- 是否回答用户真正问题。
- 是否有 missingInfo / noResultReason。
- 是否暴露内部词。
- 是否把无 evidence 的状态说成事实。

只有涉及 card 用户可见内容时，才用 `mustMentionAny` 或 `mustNotMention` 做轻量断言。

`expectedPending.targetView` 表示单个 pending/card 或只读回复的主展示目标；当一个 turn 需要同时刷新多个工作区时，使用
`expectedPending.workspaceRefreshTargets` 表达完整刷新集合。例如 apply 已有删除 pending 后又回答“还剩多少、梯度有没有问题”，主面板可以仍是
`ordered`，但刷新集合应为 `["ordered", "review"]`。

## 5. 与 Runner 的关系

后续 runner 应分三种模式读取同一份 case：

- `model-profile`：只测模型输出 `TurnDecision / EvidencePlan / replyPlan`。
- `compiler-golden`：把模型或人工 `TurnDecision` 喂给 compiler，测 `CompiledProposal`。
- `dialog-e2e`：在 fixture 已构造的本地服务上跑 WebSocket，测 pending/apply/reply/refresh。

三种模式不能混淆：

- provider 不可用不能计入模型质量。
- model node benchmark 使用节点级子契约，不要求包含完整 fixture 或 e2e 断言。

## 6. Model Node 子契约

节点级 benchmark case 保持更小的输入面，避免把端到端 fixture 噪声带进模型节点评估：

```json
{
  "caseId": "node-plan-semantic-action-G7",
  "node": "plan_semantic_action",
  "source": "3.2.0 structural analysis 2.14",
  "priority": "P0",
  "prompt": "方案里中外合作是不是有点多，家里预算一般，帮我用大白话看下风险，先别动",
  "input": {
    "planningStateProfile": {
      "formalPlanPresent": true,
      "pendingExists": false
    },
    "recentPlanContext": {
      "reviewIssueCodes": ["cooperative_program", "high_tuition"]
    }
  },
  "expected": {
    "actionFamily": "none",
    "replyFocus": ["target_issue_only"]
  },
  "actual": {
    "actionFamily": "none",
    "replyFocus": ["target_issue_only"]
  },
  "assert": {
    "exact": ["actionFamily"],
    "contains": {"replyFocus": ["target_issue_only"]},
    "notContains": {"replyFocus": ["unavailable_guidance"]}
  },
  "metricsTags": ["review_focus", "readonly_to_pending_false_positive_rate"]
}
```

字段口径：

- `node` 是节点名，不是业务场景名。
- `input` 只放该节点直接需要的摘要上下文，不放完整后端状态。
- `expected` 是节点结构化输出，不是用户最终可见回复。
- `actual` 可以来自 recorded fixture、compiler prototype 或显式 `live-node` 调用。
- `rawActual` 由 benchmark 报告自动保留原始输出，尤其用于识别旧节点仍只输出 `constraintIntentType` 等 legacy 字段。
- `profileActual` 是报告层的 3.2.0 profile 视图，只允许安全归一和 legacy 收纳，不允许把缺失字段桥接成通过。
- `schemaGaps` 用于统计 expected/assert 需要但 actual 缺失的 profile 字段，如 `preferenceStrength`、`preferenceScope`、`entityPolaritySpans`、`admissionPath`。
- `assert` 使用字段级 exact/contains/notContains，禁止用整段中文回复模板做模型节点断言。
- `contains` 支持对象数组的子集匹配，可用于断言 span 级 entity polarity。
- fixture 不成立不能计入产品缺陷。
- runtime e2e 失败不能直接归因到模型，必须结合 observability 和 compiler output。

## 7. Shadow 权限边界

3.2.0 允许在设计约束下使用 shadow，但 shadow 的权限只能是观测和报告：

- 可以读取当前回合消息、followup card、workspace action 和 observability。
- 可以导出 `runtimeShadowObservations`，并和 compiler 输出做 diff。
- 可以标注 `schemaGaps`、`missing_pending`、`unexpected_pending_creation`、`workspaceRefreshTargets` 等差异。
- 不可以改变用户响应。
- 不可以创建或替换 pending。
- 不可以 apply。
- 不可以写 backend/session/profile state。
- 不可以触发 workspace refresh。
- 不可以作为长期 bridge/compat 路径保留。

一旦某项 shadow 逻辑需要参与裁决或修复，就必须进入 3.2.0 runtime hard cut 设计，而不是留在 shadow 分支里。
