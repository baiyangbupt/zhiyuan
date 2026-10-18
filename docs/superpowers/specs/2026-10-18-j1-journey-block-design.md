# J1 旅程块：独立设计（供审核确认）

状态：**已部署，真栈验收通过（2026-10-18）**（用户拍板：全做 J1a/b/c；
`hasProfile` 严格口径；`available_actions` 仅提示、不做运行时白名单）。
已实现：Java journey/freshness/可解读/对账/upsert 保护；Agent 派生/注入/reconcile/
人工审查摘要；40 条触发目录；applying 硬不变量与 planned ChangeSet 收口。
证据：`docs/superpowers/reviews/2026-10-18-j1-true-stack-acceptance.md`
（10041984 snapshot、900040 只读回合、reconcile 接线）。
本文只覆盖 J1（旅程事实 + 触发目录 + 网关硬不变量），不包含 J3 回执、
J4 方案增删改、J5 求解器、J6 风险姿态。

上位文档：`2026-10-18-journey-control-and-admission-interpretation-design.md`（v6）
与计划 `2026-10-18-journey-control-and-admission-interpretation.md`。
本文是 J1 的单独设计；**与上位文档冲突处，以本文的“决策”节为准**，确认后再落代码。

---

## 一、目标与非目标

### 1.1 目标

1. Java 快照新增紧凑 `journey` 块：让模型每轮**不靠对话记忆**就知道
   “画像齐不齐、候选有没有、方案有没有、方案多少条、审查新不新、有没有待确认”。
2. Agent 从块派生 `statePhase`，在模型输出前注入一段**有界**的旅程上下文；
   模型输出后按固定映射派生 `taskIntent`，记入回合结果（不落库）。
3. 建立固定动作枚举与触发目录（40 条 fixture + 契约校验器）；
   `planned` 动作永不出现在“可用动作”里。
4. 网关只做**可判定的硬不变量**：一轮一个写、有 pending 才能确认/取消、
   `applying` 拒绝新写、版本守卫。不做 8 状态机、不自动修方案、不猜文本意图。

### 1.2 非目标

- 不新增数据库表、不新增事件/卡片、不改前端。
- 不把 `journeyPhase` 落库，不持久化“上一轮旅程阶段”。
- 不在 J1 里实现 replace/remove/move/regenerate/undo。
- 不用文本关键词在 pre-turn 猜意图；不把 `available_actions` 当运行时白名单。
- 不把 Java 的业务阻断（配额、目标不存在、dry-run）复制成网关硬失败。

---

## 二、关键决策（先看这一节）

| # | 决策 | 理由 / 与上位文档的差异 |
|---|---|---|
| D1 | `stale` 由 **Java 计算成布尔**，并给 `staleReasonCode/staleMessage`；agent 只读布尔，不再从 `staleFlags` 推导 | `StaleFlagsDTO` 永远非 null，“按非空判断”必然恒 true（语义权威审查 B3）。单一来源避免两层各算一遍 |
| D2 | `pendingStatus` 用**新查询** `getActiveOrApplyingStatus`（`status ∈ {active, applying}`，revision 倒序）；**不改** `getCurrent` | 表有 `(tenant_id, chat_session_id)` 唯一键，但 `getCurrent` 被 upsert/resolve 写路径使用，改它会改变“已解决行仍可见”的语义；只读派生另开方法 |
| D3 | `hasProfile` = 省份 + 年份 + 批次 + **科类** +（成绩或位次）；`subjectType` 从 `buildStudentPlanningSummary` 已在读的成绩详情补进 summary | 上位文档要求科类，但 summary 现在没有该字段（B3）；不额外读库。缺项通过 `profileMissing` 明示 |
| D4 | `hasCandidates` = `summary.total > 0 \|\| summary.unitTotal > 0`；**不**用存储的 `statusCode` 把关 | `statusCode` 是生成时写入的派生值，迁移/回填后可能是默认 `not_generated`；池里真有条目才是事实 |
| D5 | `hasPlan` = ordered ∪ working 的 items/units 任一非空；`planEntryCount` 按 mode 优先、另一形状兜底；`planVersion` = 快照计数器；`planContentDigest` = 有 ordered 用 ordered、否则用 working 的内容哈希 | 只看 items 会在 unit-only 方案上误判 false（B3）；计数与业务 helper 同口径但允许兜底；digest 与 `EvaluationContextBuilder` 在“有 ordered”时逐字一致 |
| D6 | `available_actions` **只做提示，不做运行时白名单**；网关不因“动作不在列表”拒绝 | 动作是 post-model 派生的，`intentDraft.action` 还是自由字符串；硬拦只会制造无意义失败。§5.5 的“DialogueController 校验”由本文收敛为仅硬不变量 |
| D7 | `blocked_actions` 只列**可从 journey 块直接判定**的阻断：无方案、无候选、已确认冲稳保配额、已确认目标数与当前数不一致、`applying`。**不**列“方案条目 stale 的精确条数” | 精确条数需要把 working/ordered 方案与**完整候选池**求差；workspace 投影只带方案用到的候选，算不出真相（B3 / 语义审查）。J4a 再补 `stalePlanItemCount`。目标数/当前数用专用字段，避免与展示用 `planEntryCount` 混用 |
| D8 | `taskIntent` 用**确定性映射**，工具来源用 `build_turn_trace(turn).tool_calls`，不用关键词；写动作 + `statePhase=build` → `adjust`；结果只记入回合结果/trace，不持久化 | 实际采集事件是 `{type:"item/completed", item:{type:"mcpToolCall", tool}}`，设计初稿的两种形状都不存在；`build_turn_trace` 已按真实载荷做嵌套提取。下一轮仍只注入 `statePhase` |
| D9 | `applying` 时拒绝一切新写，**不提供“取消”**；在 `validate_turn_output` **最前面**抛 `pending_applying`，固定文案、**不 repair** | 代码没有 `applying → cancelled`（只有 complete/fail/expire）。`applying` 时快照没有 `activeProposal`，既有 confirm 校验会先报 `proposal_reference_mismatch`；新检查必须排在它之前。上位 §9.3/§12.3 也要求固定文案不 repair |
| D13 | `intentDraft` 的 `ChangeSet` 对照 `JourneyAction` 状态：**最终 operations 全是 planned** → `blocked`，且 blocked 不落 TaskDraft（清掉旧账）；含至少一个已支持操作 → 保留原状态（`needs_constraints_first`/`needs_negotiation`）并带 `unsupportedActions`。判定必须在**现有归一化与机制折叠之后**；`prioritize_within_tier` 单独映射为已实现的 `prioritize`，不能落进 planned 的 `reorder` | 不能一刀切 block：纯约束里的 `replace/fill/remove` 是 `apply_constraint_and_regenerate` 的执行机制，先查 `additionalMutations` 会误伤学费/范围流程（`intent_draft.py:258-270`）。另有两个漏网：`prioritize_within_tier` 被归一成 reorder（已实现动作被误杀）、`replace_units/move_units/undo/rollback` 原样返回后走“只读动作”早退（ready + 空 operations + 落 TaskDraft）；必须在早退前拦下。`working_set.apply_output` 对任何 intentDraft 都写 TaskDraft（`working_set.py:130-136`），blocked 必须在落账前清/跳过，否则下一轮上下文还会出现 |
| D14 | `applying` 期间不得创建/替换 pending 的**最终 owner 是 Java 写入口**：`PendingConfirmationBizService.upsert` 在 revision/CAS 之前拒绝 `current.status=applying`（409 `pending_applying`）；Agent 快照检查只做提前反馈 | 快照是取回合时的事实；另一请求可在取快照后 claim。普通 prepare 已有 applying 前置，但发展方向走通用 upsert、会重新读最新 revision，CAS 反而会成功覆盖 applying（审阅 J1-R2） |
| D15 | `applying` 的异常出口由**受信 Java 对账流程**提供：读 pending + operation 台账，按 `succeeded → applied`、`running + 租约过期超宽限 → expired(结果未知)`、其余 → `still_applying` 做 CAS；**绝不重发命令**。`no_operation_submitted` 只对 command 型 pending 且在“无台账可证明”窗口内成立；`career_update` 是网关侧执行、无 Java 台账，缺席一律按结果未知 | 正常等待不能覆盖 claim 后重启、执行成功但回写失败、租约过期；Agent 不能凭超时判“未执行”（审阅 J1-R3）。发展方向写成功但 complete 前重启时，Java 台账没有行；retention 还会删 30 天前的 succeeded 行，所以“台账没有”不是永久证明（复审追加） |
| D16 | Java 给组件级新鲜度：`candidateFreshness/planFreshness/reviewFreshness ∈ {fresh,stale,absent}` + `refreshRequirement ∈ {none,candidates,plan,review}`；Agent 只消费，不解析 reason/message | 补录成绩后旧候选/旧方案仍在，只看 `hasPlan` 会继续推荐加入/审查/解读；但 `stale` 是六 flag 并集，不能一刀切阻断（审阅 J1-R5） |
| D17 | 增加正式方案判据 `orderedEntryCount` / `planInterpretable`；`hasPlan` 仍表示“有草稿/历史内容”，`review_plan`/`interpret_admission` 只在 `planInterpretable=true` 时可用 | 解读只读 ordered 且按 mode 取 items/units；working-only 或异形 ordered 会“旅程说可解读、接口返回 no_plan”（审阅 J1-R4） |
| D18 | 人工审查与规则审查分离：Java 的 `reviewFreshness` 表示规则结果是否新鲜；Agent 在 `taskIntent=review` 时记录 `lastManualReviewDigest=planContentDigest`，只在摘要未变时跳过重复推荐人工审查 | 人工审查是只读技能，不会清 Java `reviewStale`；两者不能互相代替，也不能为测试人为标旧（审阅 J1-R6） |
| D10 | `journey` 进 `build_snapshot` 透传、`diff_snapshots` 与 `StatePatch` 白名单；不合成、不落库 | 不补白名单会让 patch 被 `except ValueError` 吞掉、每轮退全量快照（v3 审查 N1） |
| D11 | 注入预算 = 阶段 / 事实摘要 / 可用 / 阻断 / 建议下一步 / `planVersion` / 待确认；不含全量矩阵 | `planning.interpret_admission` 必填 `planVersion`，不注入模型就会猜（v3 审查 N1） |
| D12 | Java 先上、agent 后上均安全：agent 对 `journey` 用 **dict 透传 + 缺省容忍**，不建 `extra="forbid"` 的严格模型 | 与 `EvidenceRef` 的历史事故同理：Java 先加字段时，严格模型会让整个快照解析失败 |

---

## 三、Java `journey` 块

### 3.1 位置与形状

`ConversationTurnSnapshotDTO` 新增字段 `private ConversationJourneyDTO journey;`
（新类 `model/dto/planning/ConversationJourneyDTO.java`）。
`admissionMode` **不重复**放进块内，继续用快照顶层字段。

```json
"journey": {
  "hasProfile": true,
  "profileMissing": [],
  "hasCandidates": true,
  "candidateEntryCount": 120,
  "candidateSourceVersion": 12,
  "hasPlan": true,
  "planEntryCount": 45,
  "orderedEntryCount": 45,
  "planInterpretable": true,
  "selectionTargetCount": 45,
  "selectionCurrentCount": 45,
  "planVersion": 87,
  "planContentDigest": "9f2c…",
  "candidateFreshness": "fresh",
  "planFreshness": "fresh",
  "planAdjustmentStale": false,
  "reviewFreshness": "fresh",
  "refreshRequirement": "none",
  "reviewSourceVersion": 86,
  "reviewStale": false,
  "tierQuotaGoal": false,
  "stale": true,
  "staleReasonCode": "score_detail_updated",
  "staleMessage": "成绩信息已补录，候选池、专家推荐与当前方案需要重新计算。",
  "pendingStatus": "active"
}
```

字段全为**只读派生**，不新增表。`planVersion` 就是当前唯一计数器
（`planningState.version = workspace.version = snapshotVersion = sourceVersionGuard`），
不是内容版本；内容版本用 `planContentDigest`。

### 3.2 字段真值表

| 字段 | 计算 | 边界 |
|---|---|---|
| `hasProfile` | `provinceName` 非空 ∧ `examYear != null` ∧ `batchName` 非空 ∧ `subjectType` 非空 ∧（`score != null ∨ rank != null`） | 全部取自 `StudentPlanningSummaryDTO`；`subjectType` 为本切片新增字段，由 `buildStudentPlanningSummary` 从已加载的 `CreateSessionReq.SubjectType` 取 `desc`（如“物理/历史/综合”），`desc` 为空时回落 `code`（WL/LS/N） |
| `profileMissing` | 上述五项中缺失的键名，固定枚举 `province/examYear/batch/subjectType/scoreOrRank`，最多 5 项 | 只用于模型问缺口，不替代 `missingFacts` |
| `hasCandidates` | `summary.total > 0 \|\| summary.unitTotal > 0` | `summary` 为 null 时 false；不看 `statusCode` |
| `candidateEntryCount` | `major_group` 取 `summary.unitTotal`，`major` 取 `summary.total` | 展示用数量；不做业务判断 |
| `candidateSourceVersion` | `candidatePoolState.sourceVersion` | 可空 |
| `hasPlan` | `ordered.items ∪ ordered.units ∪ working.items ∪ working.units` 任一非空 | stale 不影响；补录成绩后 phase 可回 `profile_ready`，此值仍 true |
| `planEntryCount` | 先取“实际在用的方案”（ordered 任一非空 → ordered，否则 working），再按 mode：`major_group` 优先 units、否则 items；`major` 优先 items、否则 units | 是“条目数”展示口径，不是业务目标数；业务动作仍用各自 helper。group 模式下 ordered 只有 items、units 为空时按 items 兜底（不能显示 0） |
| `orderedEntryCount` | 只数 **ordered** 且按 mode：`major_group` 数 units、`major` 数 items；另一形状为 0 | 与解读接口 `PlanAdmissionInterpretationFacade.buildEntries` 的条目来源同口径（可抽取共享选择器或做 parity 测试） |
| `planInterpretable` | `orderedEntryCount > 0` | `hasPlan` 可以因 working-only 为 true，但解读/审查只认正式 ordered 方案；两者不能混用 |
| `selectionTargetCount` | `constraintState.hardPlanningObjectives.selectionTargetCount` | 可空；只用于 add_units / add_units_by_scope 的目标数阻断，不参与展示计数 |
| `selectionCurrentCount` | **复用业务 helper**：`major` 用 `UserGoalProposalBuilder.currentPlanVolunteerCount`，`major_group` 用 `currentPlanUnitCount`；在 `buildPlanningWorkspaceStateRes` 算好放进 workspace，再复制进 journey | helper 还有 units→`majorItems` 求和、items 回退等分支（`:2900-2940`），不能在 snapshot 里重写简化公式；**不要**用 `planEntryCount` 代替 |
| `planVersion` | 快照 `snapshotVersion` | 无方案时也照常给；是计数器，不是内容版本 |
| `planContentDigest` | 有 ordered 内容：`SHA-256(JSON(orderedPlanState))`（与评价相同）；否则有 working：`SHA-256("working\\|" + JSON(workingPlanState))`；都空为 null | ordered 分支必须与 `EvaluationContextBuilder` 做 parity 测试；working 分支加 `working\|` 前缀，避免与评价 digest 混用 |
| `candidateFreshness` | `absent` if `!hasCandidates`；`stale` if `staleFlags.candidatePool ∨ recommendationOverlay ∨ initialRecommendation ∨ dataFreshness.requiresCandidateRefresh`；否则 `fresh` | 组件级，不是六 flag 并集；只影响“要不要先刷新候选”，不阻断解读 |
| `planFreshness` | `absent` if `!hasPlan`；`stale` **只看** `staleFlags.orderedPlan`；否则 `fresh` | `planAdjustment` 每次写方案都会置位（`markPlanStructureStale`），且 runReview 不清它；把它算进 freshness 会让 add/fill 后立刻“方案过期”，阻断下一次操作（复审追加） |
| `planAdjustmentStale` | `staleFlags.planAdjustment` | 独立信号：表示方案结构有过调整、待后续重排/审查；不参与 `planFreshness`/`refreshRequirement` |
| `reviewFreshness` | `absent` if `reviewState.status=idle` 或 `reviewSourceVersion=null`；`stale` if `staleFlags.review`；否则 `fresh` | 这是**后端规则审查**的新鲜度，不等于用户是否刚看过人工审查（D18） |
| `refreshRequirement` | 依次取第一个：`candidates`（candidateFreshness≠fresh）→ `plan`（planFreshness≠fresh）→ `review`（reviewFreshness≠fresh）→ `none` | 有界枚举，Agent 只消费，不解析 reason/message；`none` 表示无需刷新 |
| `reviewSourceVersion` | `reviewState.sourceVersion` | 可空（从未审查） |
| `reviewStale` | `staleFlags.review == true` | 独立于“有没有审查” |
| `tierQuotaGoal` | `constraintState.hardPlanningObjectives.tierQuotaGoal != null` | 用于 add_units/fill 阻断提示 |
| `stale` | 六个 flag 任一 true ∨ `reasonCode` 非空 ∨ `message` 非空 | `staleFlags` 为 null 时按 false |
| `staleReasonCode` / `staleMessage` | 原样取 `staleFlags.reasonCode/message`；message 截断 200 字 | 用于提示“先刷新/重算” |
| `pendingStatus` | 新查询：`status ∈ {active, applying}`，revision 倒序取最新；无则 null | 已解决行（applied/cancelled/expired）返回 null |

### 3.3 `pendingStatus` 查询

`PendingConfirmationSharedService` 新增：

```java
public PendingConfirmationEntity getActiveOrApplying(Long tenantId, Long chatSessionId) {
    // eq tenant/session + in(status, active, applying) + orderByDesc(revision) + limit 1
}
```

`PendingConfirmationBizService` 新增 `PendingConfirmationRes getActiveOrApplying(...)`。
`ConversationSnapshotService` **只取一次**这条记录，同时用于：
- `activeProposal`（仅当 `status=active`，载荷与今天一致）；
- `journey.pendingStatus`（`active`/`applying`，其余为 null）。

`getCurrent` 保持原语义不动；`fillActiveProposal` 改为接受这条已取到的记录，
避免同一快照一边展示 active 卡、一边声称 applying（同一行的两个读取）。

### 3.4 Java 测试

`ConversationSnapshotServiceTest` 新增：

1. 无画像 → `hasProfile=false`，`profileMissing` 含 `province/scoreOrRank`。
2. 画像齐（省份/年份/批次/科类/成绩）→ true。
3. 有候选无方案 → `hasCandidates=true, hasPlan=false`。
4. ordered items 方案 → `hasPlan=true, planEntryCount=items.size`。
5. **unit-only working plan** → `hasPlan=true`（防只数 items 的回归）。
6. 补录成绩（version +1、phase=profile_ready、stale flags 置位）→ `hasPlan` 仍 true。
7. `stale`：全 false 无 reason → false；单 flag true → true；仅 reasonCode → true。
8. `pendingStatus`：active / applying / applied(null) / 无行(null)。
9. digest：改 ordered 内容 → 变；只 bump version、不改内容 → 不变；
   与 `EvaluationContextBuilder.build(...).planContentDigest` 在 ordered 分支**逐字相等**；
   working 回退值是 `sha256("working|" + JSON)`，不与评价 digest 相等。
10. `major_group` 计数用 units；`major` 计数用 items；`major_group` 下 ordered 只有 items 时按 items 兜底。
11. `selectionCurrentCount` 与 `currentPlanVolunteerCount/currentPlanUnitCount` 同口径，
    覆盖回退分支：major 的 items→units( majorItems 求和)、group 的 units→items；
    `selectionTargetCount != selectionCurrentCount` 时 journey 原样给出两个值。
12. `subjectType`：`desc` 优先、`code` 兜底。
13. journey 块不含 `admissionMode`。
14. 旧 workspace（无 journey）不报错，字段为 null。

---

## 四、Agent `JourneyContext`

### 4.1 数据流

```
Java turn-snapshot（含 journey）
  → snapshot.py::build_snapshot 透传 journey（dict）
  → service.py 在模型输出前注入 journey_context_text(snapshot)
  → 模型输出后 derive_task_intent(output, events, state_phase)
  → 回合结果附带 journey: {statePhase, taskIntent, phase}
```

- `build_snapshot` 只认顶层 `journey`；缺省/非 mapping → `None`。
- `StatePatch._validate_change_paths` 与 `diff_snapshots.allowed` 增加 `journey`。
- 不按 workspace 形状自行合成 journey；Java 是唯一生产者。

### 4.2 `statePhase`（pre-turn）

| hasProfile | hasCandidates | hasPlan | statePhase |
|---|---|---|---|
| false | any | any | discover |
| true | false | false | explore |
| true | true | false | candidates |
| true | any | true | build |

`planningStage` 只作展示，不参与推导。`statePhase` 在模型输出前可算。

### 4.3 `taskIntent`（post-model，固定映射）

按顺序取第一个命中：

1. 本回合工具调用里出现 `planning.interpret_admission` → `interpret`
   （即使工具失败；失败也说明用户在问落点）。
2. `responseType == "review"` → `review`。
3. `responseType == "fact"` 或工具调用里出现
   `recommendation.compare_candidates` / `recommendation.explain_fit` → `verify`。
4. 本回合带有写草稿（`proposalRequest` / `scoreUpdateRequest` / `careerUpdateRequest`）
   且 `statePhase == "build"` → `adjust`。
5. 其他 → `None`（最终 phase 沿用 `statePhase`）。

- **工具来源**：复用 `build_turn_trace(turn, output).tool_calls`，不要自己解析事件。
  真实采集形状是 `{type:"item/completed"|"item/started", item:{type:"mcpToolCall", tool:"…"}}`
  （或 `item/mcpToolCall` → `tool.progress`），`build_turn_trace` 已按嵌套映射提取；
  测试必须用这个真实形状，不得用初稿里不存在的 `{type:"mcpToolCall", tool}`。
- **不读用户文本**，不按关键词猜。
- 计算位置：`_codex_turn` 末尾已构建 `trace` 的地方；把 `journey`
  （`statePhase/taskIntent/phase`）附进回合结果，不回写 Java、不持久化。

### 4.4 `available_actions`（提示，非白名单）

固定动作枚举 `JourneyAction`（`app/gateway/journey.py`）：

| 动作 | 状态 | 说明 |
|---|---|---|
| `query_plan` / `query_facts` | implemented | 读方案 / 读招生事实 |
| `compare` / `explain_fit` | implemented | 候选比较 / 适配解释 |
| `recommend_candidates` | implemented | 候选推荐 |
| `review_plan` | implemented（人工审查） | 技能 `plan-final-review`，不声称有审查产物 |
| `set_preference` | partial | scope/学费/排除 + 同档 `priority_rules`（“北方优先”）已实现；风险姿态（稳一点/冲一点）与目标优先级（保专业/保学校/保录取）未接（J6） |
| `add_units` | implemented（EXPAND） | 点名加入；REPLACE 未实现 |
| `add_units_by_scope` | implemented | 按范围加 N 条（D0） |
| `fill_to_count` | implemented | 补足/生成到目标数量 |
| `interpret_admission` | implemented | 录取解读（J2） |
| `update_score` / `update_career` | implemented | 补录成绩 / 发展方向 |
| `confirm` / `cancel` | implemented | 确认链 |
| `replace_units` / `remove_units` / `move_units` | planned | 替换 / 删除 / 排序 |
| `regenerate` | planned | 整体重生成 |
| `undo` / `rollback` | planned | 回退 |

每轮可用集合：

```
candidates = [query_plan, query_facts, compare, explain_fit, set_preference,
              update_score, update_career]
if has_profile:            + [recommend_candidates]
if planInterpretable:      + [review_plan, interpret_admission]
if has_candidates and candidateFreshness == "fresh":
                           + [fill_to_count]          # fill 可从空方案生成/重算首版
if (has_plan and has_candidates
        and candidateFreshness == "fresh" and planFreshness == "fresh"):
                           + [add_units, add_units_by_scope]
if pending_status == "active": + [confirm, cancel]

available = candidates - {blocked.action}
```

- **`fill_to_count` 不因无方案/已确认配额被阻断**：Java 的 fill 路径没有“无方案”前置，
  且 `tierQuotaGoal` 恰恰只支持 fill（`UserGoalProposalBuilder:191-196`）。
- **fill 可以在方案过期时重算方案，但不能在候选过期时用旧池凑数**：
  `candidateFreshness != fresh` 时 fill 不出现；`planFreshness != fresh` 时 fill
  仍可出现（它就是重算入口）。
- `add_units`/`add_units_by_scope` 同时要求候选与方案都 fresh；任一过期由 4.5 的
  `candidate_stale`/`plan_stale` 阻断并从 available 扣除。
- `review_plan`/`interpret_admission` 只要求 `planInterpretable`；方案过期**不**阻断只读解读，
  由注入的 `planFreshness` 提醒“这是旧条件下的一版”，避免把 stale 一刀切。
- `add_units`/`add_units_by_scope` 的 `tier_quota_goal` 阻断由 4.5 的 `blocked_actions`
  给出，并从 available 中扣除；不要在生成 candidates 时再写一遍条件。
- `planned` 动作**永不**出现；`partial` 动作出现时，提示词必须写明“只支持哪一部分”。
- 该集合只注入提示，网关**不**据此拒绝输出（D6）。

### 4.5 `blocked_actions`（可判定的才列）

按表中顺序判定；**每个动作只保留第一条命中的阻断**，避免同一动作出现多个原因。

| 顺序 | 条件 | 被阻断动作 | reasonCode | unblock |
|---|---|---|---|---|
| 1 | `pendingStatus == applying` | add_units / add_units_by_scope / fill_to_count / set_preference / update_score / update_career / confirm / cancel | `pending_applying` | 等当前变更出结果，再继续 |
| 2 | `hasPlan == false` | add_units / add_units_by_scope / interpret_admission / review_plan | `no_plan` | 先排出一版方案（可先补足到目标数量），再解读/加入 |
| 3 | `hasPlan == true && planInterpretable == false` | interpret_admission / review_plan | `plan_not_ordered` | 先把草稿排成正式顺序（生成 ordered 方案），再解读/审查 |
| 4 | `hasCandidates == false` | add_units / add_units_by_scope / fill_to_count | `candidate_source_unavailable` | 先生成或刷新候选池 |
| 5 | `candidateFreshness == stale` | add_units / add_units_by_scope / fill_to_count | `candidate_stale` | 先按新成绩/条件刷新候选池，再基于新候选调整 |
| 6 | `planFreshness == stale` | add_units / add_units_by_scope | `plan_stale` | 先按当前条件重算方案（可用“补足到目标数量”），再加入 |
| 7 | `tierQuotaGoal == true` | add_units / add_units_by_scope | `tier_quota_goal` | 先调整冲稳保配额；替换动作尚未支持 |
| 8 | `selectionTargetCount != null && selectionCurrentCount != selectionTargetCount` | add_units / add_units_by_scope | `target_count_mismatch` | 先补齐/调整到已确认目标数量，再加入 |

不列：`add_units_target_not_found/ambiguous/banned`、`add_units_dry_run_failed`、
“方案里有 N 条已不在候选池”。这些依赖本轮点名的目标或完整池成员关系，
由 Java 在 prepare 时给出权威阻断卡；网关不复制。

- `fill_to_count` **不**受 `no_plan`/`tier_quota_goal`/`plan_stale` 阻断（它就是重算入口）；
  但受 `candidate_stale` 阻断（旧候选池不能用）。
- `target_count_mismatch` 同时适用于 `add_units` 与 `add_units_by_scope`：
  两条 Builder 都有 `confirmedTarget != currentCount` 前置
  （`UserGoalProposalBuilder:348-356` 与 `:543-549`）。
- `interpret_admission`/`review_plan` **不**因 `candidateFreshness/planFreshness=stale`
  被阻断：只读解读仍可看旧方案，注入层会说明“这是旧条件下的一版”；
  真正阻断它们的是 `no_plan` 与 `plan_not_ordered`。
- `unblock` 不得指向任何 `planned` 动作（例如“改用替换”），否则等于给用户一个做不到的下一步。

### 4.6 `recommended_next`

按顺序：

| 条件（按顺序取第一条） | recommended_next |
|---|---|
| `pendingStatus == applying` | `wait`（并触发 Java 对账，见 §12.2） |
| `pendingStatus == active` | `confirm` |
| `hasProfile == false` | `update_score` |
| `refreshRequirement == "candidates"` | `recommend_candidates`（先刷新候选，不解读旧方案） |
| `refreshRequirement == "plan"` 或 `planInterpretable == false` | `fill_to_count`（生成/重算正式 ordered 方案） |
| 有未完成、未 blocked 的 `workingSet.taskDraft` | `continue_task`（元动作；新鲜度已过才轮到剩余任务） |
| `refreshRequirement == "review"` 且 `manualReviewDigest != planContentDigest` | `review_plan`（规则/人工审查都还没看本版） |
| `planInterpretable == true` | `interpret_admission` |
| 其他 | `wait` |

- `refreshRequirement="review"` 且 `manualReviewDigest == planContentDigest`：
  人工审查已看过本版，**不再推荐 review_plan**，落到 `interpret_admission`；
  但注入层仍标明“后端规则结果已过期”，两者不互相代替（D18）。
- `continue_task`、`wait` 是元动作，不出现在 `available_actions` 的业务动作里；
  它们只用于“下一步建议”，不承诺执行。

**写动作生效后不要假设 review 变 stale**：`add_units` 的冻结命令恒带
`rerunReview=true`，执行链路会重跑审查并清掉 `staleFlags.review`
（`PlanningStateService:944/953`、`PendingPlanningCommandBizService:453-461`、
`PlanningStateService:2914`）。所以生效后通常是 `reviewStale=false`，
`recommended_next=interpret_admission`；只有审查没重跑或被后续写入再次失效时才是
`review_plan`。**不要用 `reviewSourceVersion` 与 `planVersion` 比较**：审查完成时
先记 `sourceVersion=planVersion-1` 再递增版本，二者天然差 1。

### 4.7 注入格式与预算

在 `_codex_turn` 的 `context_items` 中、working set 之后追加一个
`_internal_state_block`，内容形如：

```
【当前旅程】
阶段：build
事实：画像完整；候选池 120 条；方案 45 条；待确认：active
新鲜度：候选 fresh；方案 fresh；规则审查 fresh；刷新要求 none
正式方案：可解读（45 条 ordered）
本版人工审查：未看过（或：已看过，与当前方案内容一致）
可用动作：query_plan、query_facts、…、confirm、cancel
未支持动作：replace_units、remove_units、move_units、regenerate、undo、rollback（不得声称已执行）
阻断：add_units（已确认冲稳保配额；先调整配额，替换尚未支持）
建议下一步：confirm
方案版本：87（调用 planning.interpret_admission 时 planVersion 必须用 87）
```

- `applying` 时额外一行：“上一条变更正在生效；本轮已请求服务端对账（wait/still_applying/applied/expired/unknown）”，
  不把 claim token、operationId 明细注入模型。

- 不注入完整 journey dict、不注入条目清单、不注入候选明细。
- 缺 journey 块（旧 Java）→ 整段不注入，行为与今天一致。
- `profileMissing` 非空时加一行“画像缺口：批次、科类”。

### 4.8 Agent 测试

`tests/unit/test_journey_context.py`：

1. `statePhase` 真值表 4 行 + “有方案但无候选仍 build”。
2. `taskIntent` 五种命中顺序（interpret 优先于 review/fact；写草稿+build → adjust；
   写草稿+candidates → None），工具来源用 `trace.tool_calls`。
3. 用真实采集形状 `{type:"item/completed", item:{type:"mcpToolCall", tool:"planning.interpret_admission"}}`
   构造 payload，`build_turn_trace` 后能命中 interpret；不得使用不存在的顶层 `{type:"mcpToolCall"}`。
4. `available_actions` 不含任何 planned；有候选无方案时含 `fill_to_count`；
   `tierQuotaGoal=true` 时 `add_units` 被扣掉、`fill_to_count` 仍在；
   `applying` 时写动作与 confirm/cancel 被扣掉。
5. `blocked_actions` 五种条件（no_plan / candidate_source_unavailable /
   tier_quota_goal / target_count_mismatch / pending_applying）的 reasonCode/unblock；
   target_count_mismatch 同时覆盖 add_units 与 add_units_by_scope；
   fill 不出现在 no_plan、tier_quota_goal 行。
6. `recommended_next` 七行；特别覆盖“审查已重跑、reviewStale=false →
   interpret_admission”，不得因 `reviewSourceVersion=planVersion-1` 误判 review。
7. 注入文本包含 `planVersion`、不包含完整 dict。
8. 旧快照无 journey → `None`，不抛错。

`tests/unit/test_snapshot_projection.py` 增补：

- `build_snapshot` 透传 `journey`；`diff_snapshots` 在 journey 变化时产出 `journey` 路径；
- `StatePatch` 接受 `journey` 路径（不再 `unsupported state path`）。

---

## 五、触发目录（J1b）

### 5.1 Fixture schema（`tests/fixtures/trigger_catalogue.json`）

```json
{
  "id": "T01",
  "utterance": "把这几条加进方案",
  "goalFamily": "plan_mutation",
  "expectedAction": "add_units",
  "status": "implemented",
  "carrier": "proposalRequest(goalType=add_units, exactTargets)",
  "write": true,
  "slots": ["exactTargets"],
  "ambiguity": {"question": "扩总数还是保持总数替换？", "options": ["扩总数", "保持总数替换"]},
  "failureBehavior": "目标不在候选池 → 逐条说明，不加入"
}
```

- 40 条，覆盖：查方案 2、查事实 4、比较/解释 3、偏好/排除 5、候选 3、
  加入 5（点名 / 按范围 / 补足 / 必须有且已有 / 必须有但方案已满）、
  删改排 4、审查 3、解读 3（正常 / 无方案 / 反事实）、补录成绩与发展方向 3、
  确认取消 3、元操作 2。
- `write=true` 的 `slots` 必须非空；`ambiguity` 非空的条目必须给 **1 个问题 + 2~3 个选项**。
- `planned` 条目的 `failureBehavior` 必须写“如实说不支持 + 给替代动作”。

### 5.2 契约校验器（CI 必跑）

`tests/unit/test_trigger_catalogue.py` 只证明目录自洽，不证明模型会按目录走：

1. 40 条 id 唯一、字段齐全。
2. `expectedAction ∈ JourneyAction`。
3. `status` 与 `JOURNEY_ACTION_STATUS` 一致（implemented/partial/planned）。
4. `planned` 动作不在任何状态的 `available_actions` 里。
5. 写动作槽位非空；歧义条目格式合法。
6. `carrier` 非空且不得出现 `goalType=prefer`、`system.action`。
7. 文案不得出现“概率 / 最可能 / 滑档风险低 / 风险等级”等越界表达。

可选 live eval 不纳入 CI：固定模型版本/温度，记录实际动作与命中率；
没有 harness 时不得把“40 条全绿”写成模型路由验收。

### 5.3 提示词/技能改动

- `planner-routing`：判阶段改用注入的 JourneyContext（phase/available/blocked），
  `planningStage` 只作展示；增加“未支持动作如实说”的硬门禁。
- `developer_instructions.write.md`：注入块优先级、`planVersion` 用法、
  `applying` 等待口径、planned 动作禁止声称执行。
- `plan-construction`：保留现有“必须有/替换 1 组/仅本次”口径，补“按范围加入”
  与“fill_to_count 可生成首版方案”。
- `plan-admission-interpretation`：`planVersion` 来自注入块，不得猜。
- 偏好口径：地域/专业“优先/为主”可落同档 `priority_rules`；
  “稳一点/冲一点”“保专业/保学校/保录取”只给建议并说明尚未生效（J6），
  不得假装已改生成器。

---

## 六、网关硬不变量（J1c）

### 6.1 执行表

| 不变量 | 位置 | 错误码 | 处置 |
|---|---|---|---|
| `pendingStatus=applying` 且输出带写草稿/确认/取消 | `validate_turn_output` **最前面**（J1c 新增） | `pending_applying` | 固定文案、**不 repair**；必须排在既有 confirm 校验之前 |
| 确认/取消必须有 active pending | `output_validation`（已有） | `proposal_reference_mismatch` | 一次修复回合（已有） |
| 一轮最多一个写草稿 | `service.py`（已有） | `conflicting_proposals` | 硬失败 |
| 确认/取消不得与新草稿/intentDraft 同轮 | `service.py`（已有） | `confirmation_conflicts_with_new_intent` | 硬失败 |
| 写草稿版本守卫 | `output_validation` / `_prepare_*`（已有） | `proposal_source_version_mismatch` / `stale_state` | 可修复优先 |
| ChangeSet 非 ready/atomic 且带草稿 | `service.py`（已有） | 无错误码 | 丢草稿、保留正文、追加说明 |
| `planned` 结构变更进入 ChangeSet | `intent_draft.build_change_set`（J1c 新增） | 单独动作 → ChangeSet `blocked`；分步草稿 → `unsupportedActions` | 单独动作不 ready/atomic；分步草稿保留 TaskDraft，但标记哪一步未支持 |
| 动作不在 `available_actions` | — | — | **不拦**（D6） |
| journey 显示已知阻断但仍提案 | — | — | **不拦**；Java 返回 blocked 预览卡（权威文案） |

### 6.2 `pending_applying` 细节

- 判定：`journey.pendingStatus == "applying"` 且输出满足任一：
  `proposalRequest` / `scoreUpdateRequest` / `careerUpdateRequest` /
  `conversationAction.actionType ∈ {confirm_proposal, cancel_proposal}`。
- **位置**：`validate_turn_output` 解析出 output 后**立即**检查，排在
  `action_type ∈ {confirm_proposal, cancel_proposal}` 的 `proposal_reference_mismatch`
  之前。原因：`applying` 时快照的 `activeProposal` 为 null（`fillActiveProposal`
  只暴露 `active`），既有 confirm 校验会先命中，用户看到的就不是“正在生效”。
- 文案固定：“上一条变更正在生效，请稍候；结果会以回执为准。”
- **不提供取消**：Java 没有 `applying → cancelled` 的转移（D9）。
- **不 repair**：不加进 `_REPAIRABLE_CONTRACT_CODES`。`_codex_turn` 的
  `OutputContractError` 分支返回固定 `reply`（与 `server.py` 的
  `result.get("reply")` 消费口径一致），用户直接看到这句话；模型不再多跑一轮。

### 6.2b `planned` 结构变更：blocked + 显式标记，不丢分步意图

1. **先归一化动作**：`prioritize_within_tier` 与含 `priorit*` 的自由命名 →
   `prioritize`（已实现：priority rule，按 `constrain` 族处理）；
   `reorder` / `sort` → `reorder`（planned）。`prioritize_within_tier` 不得再落进
   `reorder`，否则一个已实现动作会被误判。
2. **planned 动作集**同时收录归一化名与原样名：
   `remove/replace/move/reorder/generate/replace_units/remove_units/move_units/regenerate/undo/rollback`。
   主动作命中时，在“只读/解释动作”早退**之前**返回 `blocked`——
   否则 `replace_units/undo/rollback` 会走成 ready + 空 operations + TaskDraft。
3. **保留现有机制折叠**：纯约束（`is_constraint_action && !has_targets` 且
   `additionalMutations ⊆ {replace,fill,remove}`）里的这些词是
   `apply_constraint_and_regenerate` 的执行机制，折叠后不产生结构操作；
   这一步不能动（否则学费/范围流程被误判）。
4. **折叠后按最终 `operations` 判定**（不是按 `additionalMutations` 列表）：
   - `operations` **全是** planned kind（如单独 remove）→
     `status="blocked"`、`atomic=False`、`unresolved=["该动作尚未支持"]`；
   - `operations` 里**至少有一个已支持 kind**（constrain / add / add_by_scope / fill）→
     保持现有状态：
     - 约束 + 结构 → `needs_constraints_first`；
     - 多个结构 → `needs_negotiation`；
     并把这些 planned kinds 放进 `unsupportedActions`。
   例：`constrain` 主操作 + `additionalMutations=["remove"]`（带 targets）→
   operations `[constrain, remove]`，有 constrain → 仍 `needs_constraints_first`；
   `remove` 主操作 + requirements → 同样先约束后 remove，仍 `needs_constraints_first`。
5. `ChangeSet` 增加 `unsupportedActions`（默认空）：列出最终 `operations` 里属于
   planned 的 kind（如 `["remove"]`）。
   - `needs_constraints_first` / `needs_negotiation` 的 TaskDraft 照旧持久化，
     模型下一轮能看到并只推进已支持的一步；
   - `blocked` **不落 TaskDraft**：`working_set.apply_output` 跳过写入并清掉旧
     `task_draft`；`service.py` 在 `output.intent_draft` 的 ChangeSet 为 blocked 时
     **显式** `task_ledger.clear`（不能只靠 `task_draft is None`——旧账本还在）。
     否则下一轮 `working_set.as_context_text()` 仍会把未实现动作摆给模型。
6. 提示词/续接口径：`unsupportedActions` 非空时，只能说明“这一步尚未支持”，
   不得声称已执行或把 `planned` 动作当可续接任务。
7. 测试（写清输入主操作）：
   - 单独 `remove` / `replace_units` / `undo` → blocked，TaskDraft 为空，
     Redis 账本无残留；
   - `constrain` 主操作 + `additionalMutations=["remove"]` + targets →
     `needs_constraints_first`，operations `[constrain, remove]`，
     `unsupportedActions=["remove"]`，TaskDraft 保留；
   - `remove` 主操作 + requirements → `needs_constraints_first`，
     operations `[constrain, remove]`，`unsupportedActions=["remove"]`；
   - 纯约束 + `replace/fill` 机制（无 targets）→ 仍 ready/atomic，
     `unsupportedActions=[]`；
   - `add + remove` → 仍 `needs_negotiation`，标记 remove；
   - `prioritize_within_tier` → ready/atomic、operations 为 `constrain`、
     `unsupportedActions=[]`（不得被误杀）。

### 6.3 不做

- 不做“动作合法性”的运行时白名单（D6）。
- 不做 8 状态机、自动重试、自动改方案。
- 不把 Java 的业务阻断（配额/目标/dry-run）复制到网关。

---

## 七、兼容、部署与回滚

1. **无数据库迁移**；`journey` 是纯派生。
2. **部署顺序**：Java 先上（多一个快照字段，旧 agent 忽略）或 agent 先上
   （journey 缺省 None，不注入）都安全；推荐同批。
3. **回滚**：agent 回滚到不认 journey 的版本 → 快照解析不炸（dict 透传字段在旧代码里是
   extra，会被 `build_snapshot` 忽略）；Java 回滚 → journey 缺失，agent 不注入。
4. `subjectType` 进 `StudentPlanningSummaryDTO` 是加字段，`/session/workspace-state`
   旧消费者忽略即可。
5. 观察点：`journey.statePhase` 与真实动作是否长期错位；`hasProfile` 是否因批次/科类
   过严把可推进会话判成 discover（用克隆会话回归，不动用户会话）。

---

## 八、验收

### 8.1 单测

- Java `ConversationSnapshotServiceTest` 共 15 例（含既有回归 + 第 3.4 节新增）。
- Python `test_journey_context.py` 第 4.8 节 8 例。
- Python `test_snapshot_projection.py` journey 透传/diff/StatePatch。
- Python `test_trigger_catalogue.py` 40 条契约校验。
- Python `test_gateway_journey_invariants.py`：
  applying 拒绝新写且**先于** confirm 校验、固定文案不 repair、确认无 pending、
  一轮一个写、版本守卫、最终 operations 全 planned → blocked 且不落 TaskDraft/
  清旧账、分步草稿带 `unsupportedActions` 且纯约束机制不误伤、
  journey 缺失时旧行为不变。
- Java `PendingConfirmationBizServiceTest`：
  applying + 最新 revision → upsert 409；prepare 检查通过后 claim 的交错 → 409。
- Java `PendingConfirmationReconcileTest`（或 BizService 内）：
  succeeded→applied；command 型 no-operation+证明窗口内→expired(no_operation)；
  no-operation+窗口外/retention 风险→expired(unknown)；career_update 无台账→
  只 still_applying/expired(unknown)，绝不 no_operation；running+近期→still_applying；
  running+超宽限→expired(unknown)；非 applying 幂等；CAS 输重读。
- Python `test_gateway_pending_reconcile.py`：
  applying 回合调用 reconcile；applied/expired 刷新快照；still_applying 等待；
  reconcile 异常 fail-safe、不发第二个 execute。
- Python `test_journey_context.py` 增补：
  补录后 candidate/plan freshness=stale → recommend_candidates、add/fill 阻断、
  interpret 仍可用；working-only → planInterpretable=false、review/interpret
  阻断 `plan_not_ordered`；人工审查摘要一致时不再推荐 review_plan。

### 8.2 真栈（实现后，克隆会话）

1. `GET /session/turn-snapshot` 返回 journey 全部字段，数值与 workspace 对得上。
2. 只读回合：日志/回合结果能看到注入块；模型不声称 planned 动作已执行。
3. 一次加入预览 + 确认：既有链路无回归；生效后审查已重跑，
   `reviewStale=false`、`recommended_next=interpret_admission`；
   `planAdjustmentStale` 可能为 true，但 `planFreshness=fresh`（只看 orderedPlan），
   不阻断下一次加入。
4. 补录成绩后：`phase` 可回 `profile_ready`，但 `hasPlan=true`；
   `candidateFreshness/planFreshness=stale`，`recommended_next=recommend_candidates`，
   `add_units/fill` 给出 `candidate_stale` 解锁说明，解读仍可用但标注旧数据。
5. `applying` 窗口内再发写请求：固定文案，不生成第二张卡。
6. 人为制造 applying 后：
   - operation 台账 succeeded → reconcile 返回 applied，计划版本与回执可核对；
   - 无 operation 且租约过期 → expired(no_operation_submitted)；
   - running 超宽限 → expired(operation_result_unknown)，不自动重试。
7. working-only 方案（清空 ordered）：`planInterpretable=false`，
   解读/审查给出 `plan_not_ordered`，推荐 `fill_to_count`。
8. 人工审查同一 digest 后再问“继续”：不再推荐重复 review_plan；方案内容变化后
   重新推荐。

### 8.3 不验收

- “40 条 fixture 全绿 = 模型路由正确”（只证明目录自洽）。
- 自动重排/自动撤销（自动源不存在）。

---

## 九、实施切片（已确认）

顺序：**J1a-T1（Java 事实）→ J1-R1（写入口保护）→ J1-R2（对账/恢复）→
J1a-T2（agent 派生/注入，含 freshness 与人工审查）→ J1b（触发目录）→
J1c（硬不变量）**。前三步是“先补写入最终保护、异常恢复与 freshness”；
J1a-T2 之后统一方案可读性与审查语义；不需要重做架构。

### J1a-T1 Java `journey` 块

- 新增 `ConversationJourneyDTO`；`ConversationTurnSnapshotDTO.journey`。
- `PlanningWorkspaceStateRes` 增加 `stalePlanItemCount`？**不加**（D7）。
- `StudentPlanningSummaryDTO.subjectType`（`desc` 优先、`code` 兜底）；
  `buildStudentPlanningSummary` 赋值。
- `UserGoalProposalBuilder.currentPlanVolunteerCount/currentPlanUnitCount` 改为包内可见；
  `PlanningWorkspaceStateRes` 增加 `selectionTargetCount/selectionCurrentCount`，
  由 `buildPlanningWorkspaceStateRes` 用上述 helper（有完整 state）计算。
- `ConversationSnapshotService` 投影 journey：`planEntryCount`、两个 selection 字段、
  `orderedEntryCount/planInterpretable`、`candidateFreshness/planFreshness/
  reviewFreshness/refreshRequirement`、digest（ordered 分支与评价 parity；working
  分支加 `working|` 前缀）、stale、pending。
- `PendingConfirmationSharedService.getActiveOrApplying`；
  `PendingConfirmationBizService.getActiveOrApplying`（返回整行）；
  `ConversationSnapshotService` **只取一次**，同时供 `activeProposal` 与
  `journey.pendingStatus`。
- 测试：`ConversationSnapshotServiceTest`（含 digest parity / selection count /
  group 模式 items 兜底 / working-only 不可解读 / 补录后 freshness）。

### J1-R1 Java：`upsert` 拒绝覆盖 applying（P1）

- `PendingConfirmationBizService.upsert`：在 `isSameActiveSnapshot` 之后、revision
  比较之前，`current.status=applying` → `BusinessException(409, "pending_applying")`；
  CAS 仍带 expectedStatus。
- 测试：静态 applying + 最新 revision → 409；`prepareOnce` 检查通过后状态被另一请求
  claim 的交错 → `upsert` 409、行不变。

### J1-R2 Java：`applying` 对账/恢复（P1）

- 新增 `POST /session/pending/reconcile`（`ChatSessionInnerController`）与
  `PendingConfirmationBizService.reconcile`（§12.2）。
- 读 pending + `assistant_planning_pending_command`，按表返回
  `still_applying/applied/expired/expired_unknown`；只 CAS 状态，不调用 execute。
- 阈值配置 `planning.pending.reconcile.operation-stale-ms`（默认 600000）。
- 测试：succeeded→applied、无 operation+过期→expired、running+近期→still_applying、
  running+超宽限→expired(unknown)、非 applying→幂等、CAS 输→重读。

### J1a-T2 agent 派生与注入

- 新增 `app/gateway/journey.py`：`JourneyAction`、`BlockedAction`、`JourneyContext`、
  `state_phase`、`derive_task_intent`、`context_text`。
- `contracts.py`：`ConversationTurnSnapshot.journey: dict | None`；
  `StatePatch` 白名单加 `journey`。
- `snapshot.py`：透传 + `diff_snapshots.allowed` 加 `journey`。
- `service.py`：注入块；复用 `build_turn_trace(turn, output).tool_calls`
  计算 `taskIntent`；回合结果附 `journey`（statePhase/taskIntent/phase）。
- `service.py`：`journey.pendingStatus=applying` 时调用 Java reconcile；
  applied/expired 刷新快照并注入结果说明；still_applying 保持等待；
  异常 fail-safe 为等待。
- `working_set`：`taskIntent=review` 时记录 `last_manual_review_digest/version`；
  注入层按 digest 是否一致显示“本版人工审查已看过/未看过”。
- `recommended_next`：pending → `continue_task`（有未完成 TaskDraft）→ 画像 →
  freshness（candidates/plan/review）→ interpret；元动作 `wait/continue_task`。
- 测试：`test_journey_context.py`（真实事件形状、freshness、planInterpretable、
  人工审查摘要、recommended 优先级）、`test_snapshot_projection.py`。

### J1b 触发目录

- `tests/fixtures/trigger_catalogue.json`（40 条）+
  `tests/unit/test_trigger_catalogue.py`。
- 技能/提示词按 5.3 修改。
- 插件 cachebuster + 重装（部署时）。

### J1c 硬不变量

- `output_validation.py`：`pending_applying` 检查放在最前面；固定文案、不 repair。
- `service.py`：`pending_applying` 的固定 `reply`；不做修复回合。
- `intent_draft.py`：最终 operations 全是 planned → `blocked`；分步草稿增加
  `unsupportedActions` 标记（保留 TaskDraft，不误伤纯约束的 replace/fill 机制）。
- `working_set.apply_output`：blocked 不写 TaskDraft 并清旧值；
  `service.py` 同步清 Redis task ledger。
- 测试：`tests/unit/test_gateway_journey_invariants.py`、`test_intent_draft.py`、
  `test_working_set.py`。

---

## 十、开放问题（不阻塞 J1，记录）

1. `stalePlanItemCount` 精确条数：J4a 在方案编辑动作前补；当前只做粗提示。
2. 上一轮 `taskIntent` 不持久化：若模型需要“用户刚看完解读”的连续感，
   后续可把 `lastJourneyPhase` 放进 working set（Redis 7d），不进 DB。
3. `hasProfile` 是否对浙江等“综合”省份强制科类：本设计按硬事实要求；
   若真栈发现大量会话无 subjectType，再放宽为“省份+年份+批次+成绩/位次”。
4. `set_preference` 的 partial 状态如何在技能里表达：J1b 写清
   “scope/学费/排除 + 同档 priority_rules 可用；风险姿态/目标优先级未接（J6）”。
5. `applying` 对账的定时兜底（扫过期 claim）是可选增强；J1 先上按需 reconcile，
   已有入口与幂等语义，后续加 `@Scheduled` 不改协议。
6. 恢复后的完整回执（origin/actionType/scope）仍归 J3；J1 只刷新快照并注入
   “已生效/未完成/结果待核对”说明，不新增事件。
7. 人工审查摘要标记是 WorkingSet 进程内信号，重启丢失只会多推荐一次审查，
   不影响 Java 业务状态；不为此新增持久化表。

---

## 十一、独立评审发现与处置

评审结论：**需修改后通过**。以下均为代码核对后的硬事实，已并入上文。

| # | 发现 | 处置 |
|---|---|---|
| 1 | `fill_to_count` 没有“无方案”前置，且 `tierQuotaGoal` 恰是 fill 唯一支持项；初稿却把 fill 放进 no_plan/tier_quota 阻断 | §4.4 改为“有候选即可用 fill”；§4.5 的 no_plan/tier_quota 行移除 fill；§4.6 无方案推荐 fill |
| 2 | `add_units` 冻结命令恒 `rerunReview=true`，执行后审查重跑并清 flag；初稿“生效后 reviewStale=true”相反 | §4.6 改为“生效后通常 reviewStale=false → interpret_admission”；禁止用 reviewSourceVersion 与 planVersion 比较（天然差 1） |
| 3 | 真实工具事件是 `{type:"item/completed", item:{type:"mcpToolCall", tool}}`；初稿两种形状都不存在 | §4.3 改为复用 `build_turn_trace(...).tool_calls`；测试用真实形状 |
| 4 | `applying` 时快照无 `activeProposal`，既有 confirm 校验会先报 `proposal_reference_mismatch`；初稿又把它加入可修复码 | §6.1/§6.2 改为 `validate_turn_output` 最前面检查、固定文案、不 repair；`available_actions` 扣除 blocked |
| 5 | `build_change_set` 会把单独的未实现结构动作标 ready/atomic，并存进 TaskDraft | 新增 D13/§6.2b：单独 planned → blocked；分步草稿保留 TaskDraft 但带 `unsupportedActions`；纯约束的 replace/fill 机制不误伤 |
| 6 | Java 口径细节：subjectType desc/code、digest parity、group 计数兜底、add_units 目标数阻断 | §3.2/§3.4 写死 desc↔code、ordered digest parity + working 前缀、shape 兜底；新增 selectionTargetCount/selectionCurrentCount 与 target_count_mismatch 阻断 |
| 7 | `unblock` 指向 planned 的“替换动作” | §4.5 明确 unblock 不得指向 planned；tier quota 的 unblock 改为“先调整配额（替换尚未支持）” |
| 8 | `add_units_by_scope` 也有 `confirmedTarget != currentCount` 前置，初稿只归给 add_units | §3.2/§4.5 改为两者都适用，并去掉“by_scope 不受阻断”的错误说明 |
| 9 | D13 若在机制折叠前查 `additionalMutations` 会误伤纯约束；且 `prioritize_within_tier` 被归一成 planned 的 reorder，`replace_units/undo/rollback` 走只读早退仍 ready | §6.2b 改为“归一化→机制折叠→再判 planned”；`prioritize*` 单独映射为已实现的 `prioritize`；planned 原样名在只读早退前拦下 |
| 10 | `selectionCurrentCount` 简化公式漏了 helper 的 units→majorItems 求和与 items 回退，会误报 target mismatch | 改为在 `buildPlanningWorkspaceStateRes` 复用 `currentPlanVolunteerCount/currentPlanUnitCount`，不重写公式；测试覆盖回退分支 |
| 11 | 注入示例仍写“改用替换”；§8.1 写 12 例与 §3.4 的 14 例不一致 | 示例改为“先调整配额，替换尚未支持”；统一为 14 例 |
| 12 | `working_set.apply_output` 对任何 intentDraft 都写 TaskDraft，blocked 动作仍会落账并进下一轮上下文 | §6.2b 第 5 条：blocked 不写 TaskDraft、清旧值，service 同步清 Redis 账本；补测试 |
| 13 | “只有一个 planned → blocked”对 constrain+remove 有歧义，且与 `needs_constraints_first` 测试矛盾 | 改为按**最终 operations**判定：全是 planned → blocked；含已支持操作 → 保持原状态并标 `unsupportedActions`；测试写清主操作 |
| 14 | P1：只靠 Agent 快照不能保证 applying 期间不创建新 pending；发展方向通用 upsert 可覆盖 applying | D14/§12.1：Java `upsert` 最终拒绝 applying（409），CAS 带 expectedStatus；Agent 检查只做提前反馈；加交错测试 |
| 15 | P1：applying 只有等待，没有 claim 重启/回写失败/租约过期的出口 | D15/§12.2：Java 受信 reconcile 读 operation 台账，按 succeeded/no-operation/running 分支出 applied/expired/still_applying；不重发命令；加对账测试 |
| 16 | P1：推荐逻辑不消费候选/方案 freshness，补录后仍推荐旧方案 | D16/§12.3：Java 给组件级 freshness + refreshRequirement；推荐/阻断消费；只读解读不因 stale 一刀切 |
| 17 | P2：`hasPlan` 包含 working-only，解读只读 ordered，导致“可解读但 no_plan” | D17/§12.4：新增 `orderedEntryCount/planInterpretable`；解读/审查只认正式 ordered；working-only 推荐 fill |
| 18 | P2：人工审查不清 Java reviewStale，下一轮重复推荐审查 | D18/§12.5：Java reviewFreshness 与 Agent `lastManualReviewDigest` 分离；摘要一致时不再推荐人工审查，不冒充规则审查 |
| 19 | career_update 在网关侧执行、没有 Java operation 台账；reconcile 不能把“无行”判成未送出 | §12.2：按 kind 分支，career 只 still_applying/unknown；command 型加 24h 证明窗口，retention 外一律 unknown |
| 20 | `planFreshness` 把 planAdjustment 算进去；每次写方案都置位且 runReview 不清，导致 add/fill 后立刻“方案过期” | §3.2/§12.3：planFreshness 只看 orderedPlan；新增独立 `planAdjustmentStale` 参考信号 |
| 21 | facade 的 mode 判据只认 `majorGroup`，快照 canonical 还认 `major_group`；null 条目计数不一致 | §12.4：两处统一 canonical；orderedEntryCount 数非 null；补 parity fixture |

仍未纳入（记录在案）：精确 `stalePlanItemCount`、`lastJourneyPhase` 持久化、
`hasProfile` 对“综合”省份的强制科类口径。三者都不阻塞 J1 的落地与验收。

---

## 十二、追加审阅（2026-10-18）：写入保护、恢复与新鲜度

以下五项来自 `docs/superpowers/reviews/2026-10-18-j1-journey-block-design-review.md`。
结构不变：Java 生产事实 → Agent 对话派生 → 提示性动作目录；只补闭环。

### 12.1 P1：`applying` 的最终保护在 Java pending 写入口

**问题**：Agent 只在回合快照上检查 `applying`。另一请求可在取快照后 claim；
发展方向路径直接保存 pending 并重新读取最新 revision，通用 `upsert` 没有拒绝
`applying`，CAS 以最新 revision 为基线，反而会成功覆盖正在执行的行。

**实现**：

1. `PendingConfirmationBizService.upsert` 在取到 `current`、判完
   `isSameActiveSnapshot` 之后、任何 revision 比较/构造新 active 之前：
   ```java
   if ("applying".equals(current.getStatus())) {
       throw new BusinessException(409, "pending_applying");
   }
   ```
   `resolve`/`complete`/`fail` 不走 `upsert`，正常收尾不受影响。
2. CAS 仍保留 `expectedStatus=current.status`：即使状态在读取后变化，也输掉 CAS，
   不靠单点判断。
3. Agent 侧：
   - 回合前的 `journey.pendingStatus=applying` 检查保留，作为**提前反馈**；
   - 提案/补录/发展方向在 prepare/save 收到 Java `409 + pending_applying` 时，
     统一抛 `OutputContractError("pending_applying")`，走固定文案；
   - 不再新增第二套判断。
4. 测试：
   - Java：`current.status=applying` + 最新 revision → `upsert` 409，行不变；
   - Java 交错：`prepareOnce` 的 `activePendingStatus=active` 检查通过后，
     行被另一请求改成 `applying`，随后 `upsert` 必须 409；
   - Agent：发展方向 prepare 收到 409 pending_applying → `pending_applying`，
     固定文案、不生成卡。

**边界**：`getCurrent` 仍返回任意状态行（写路径需要看到已解决行）；本保护只加在
`upsert`，不改 `resolve`。

### 12.2 P1：`applying` 的受信对账与恢复出口

**问题**：`applying` 只有“等待”。claim 后 Agent 重启、执行成功但 complete 回写失败、
租约过期，都会无限停在 `applying`。不能凭超时判“未执行”，也不能重发第二个 operation。

**现有台账**：

- `assistant_chat_session_pending_confirmation`：`pendingId/revision/status/claimToken/
  claimExpiresAt/dataValue.operationId`；
- `assistant_planning_pending_command`：`operationId/pendingId/commandType/status
  (running|succeeded)/expectedPlanVersion/resultJson/updateTime`。

**受信 owner**：Java 新增 `POST /session/pending/reconcile`（inner）与
`PendingConfirmationBizService.reconcile(tenantId, chatSessionId)`：

1. `lockCurrent` 取 pending；非 `applying` → 原样返回（幂等）。
2. 从 `dataValue.operationId` 取 operationId；按 operationId 读 command 行。
3. 判定（只读台账 + CAS，**绝不调用 execute**）：

| 台账事实 | 租约/时效 | 结论 |
|---|---|---|
| `kind/actionFamily` 是网关侧执行（`career_update`） | 任意，command 不存在 | 不允许 `no_operation_submitted`；claim 未过期 → `still_applying`；已过期且超宽限 → `expired`，resultCode=`operation_result_unknown` |
| command 不存在（command 型 pending） | claim 已过期，且在“无台账可证明”窗口内（pending 创建 < 24h，远小于 retention 30 天） | `expired`，resultCode=`no_operation_submitted`（可证明没有命令送出） |
| command 不存在（command 型 pending） | claim 已过期，但超出证明窗口/无法确认 kind | `expired`，resultCode=`operation_result_unknown`（retention 可能已删行，不能证明未执行） |
| command 不存在 | claim 未过期 | `still_applying`（Agent 还可能送） |
| command.status=`succeeded` | 任意 | `applied`，从 resultJson 取 `resultPlanVersion`；`receiptAvailable=true` |
| command.status=`running` | claim 未过期 | `still_applying` |
| command.status=`running` | claim 已过期且 `command.updateTime` 超过宽限（默认 10 分钟） | `expired`，resultCode=`operation_result_unknown`（结果未知，不重试） |
| command.status=`running` | claim 已过期但仍在宽限 | `still_applying`（可能还在跑） |

**career_update 的边界**：`_execute_career_update` 在网关侧写 latent profile，
不走 Java `pending-command` 台账；若写完、complete 前重启，Java 只看到 pending
applying、没有 command 行。因此对 `kind=career_update`：
- 不允许 `no_operation_submitted`；
- claim 未过期 → `still_applying`；已过期且超宽限 → `expired(operation_result_unknown)`；
- 可选增强（J1 不做）：在方向写前后落一条只用于对账的 operation 台账，届时再允许
  `succeeded/applied`；不伪造台账。

**retention 边界**：`PlanningPendingCommandRetentionTask` 会删 30 天前的 succeeded 行；
command 型 pending 的“无行”只在证明窗口内可判 `no_operation_submitted`，
窗口外一律结果未知。

4. 需要迁移时用 `compareAndSet(next, revision, pendingId, "applying")`：
   - `applied`：status=applied；
   - `expired`：status=expired + resultCode；
   - CAS 失败 → 重读并按最新状态返回。
5. 返回有界 DTO：`pendingId/pendingStatus/operationStatus/outcome/resultPlanVersion/
   receiptAvailable/claimExpiresAt`；**不返回 claimToken、不返回完整 resultJson**。

**调用方**：

- 网关在 `journey.pendingStatus=applying` 的回合开始时调用一次（超时/异常就按
  `still_applying` 处理，fail-safe，不判未执行）；
- 若 `applied`/`expired`：刷新快照；注入一行“上一条变更已生效/未完成（原因）”，
  模型据此回执；J1 不发新事件，完整回执统一留 J3；
- 若 `expired(operation_result_unknown)`：固定文案“上次变更结果待核对，请刷新方案
  核对版本”，不自动重试；
- 可选 `@Scheduled` 兜底：每 5 分钟扫一批“applying 且 claim 过期”的会话，调用同一
  reconcile（bounded，失败只记日志）。不实现也不阻塞 J1，但设计保留入口。

**不变量**：

- 对账**只读台账 + 迁移 pending 状态**，不创建新 operation、不重发命令；
- 超时不等于未执行；`running` 且未过宽限继续等；
- `no_operation_submitted` 才是“确认没有送出”的结论。

### 12.3 P1：组件级 freshness 与推荐优先级

**问题**：补录成绩后旧候选/旧方案仍在；只看 `hasPlan` 会继续推荐加入/审查/解读。
`stale` 是六 flag 并集，不能一刀切阻断。

**Java 字段**（见 §3.2）：`candidateFreshness/planFreshness/reviewFreshness/
refreshRequirement`。来源：

- `candidateFreshness`：`staleFlags.candidatePool/recommendationOverlay/
  initialRecommendation` 或 `DataFreshnessStateDTO.requiresCandidateRefresh=true`；
- `planFreshness`：**只看** `staleFlags.orderedPlan`（`planAdjustment` 每次写方案都置位，
  不计入；另给 `planAdjustmentStale` 作为参考信号）；
- `reviewFreshness`：`staleFlags.review` + review 是否存在；
- `refreshRequirement` 按 `candidates → plan → review` 取第一个非 fresh。

**Agent 消费**（§4.4/§4.5/§4.6）：

- 推荐：`candidates → recommend_candidates`；`plan → fill_to_count`；
  `review → review_plan`（人工审查摘要已覆盖本版时降级为 interpret）；
  `none → interpret_admission`。
- 阻断：写动作在 `candidate_stale`/`plan_stale` 时给出可解锁说明；
  只读解读/审查**不**因 stale 阻断，注入层标注“旧条件下的一版”。
- 不解析 `staleReasonCode/staleMessage` 重新实现业务规则。

**典型场景（补录成绩）**：`candidateFreshness=stale`、`planFreshness=stale` →
`recommended_next=recommend_candidates`；`add_units/add_by_scope/fill` 被
`candidate_stale` 阻断；`interpret_admission` 仍可用但注明旧数据。

### 12.4 P2：`hasPlan` 与“可解读/可审查”分离

**问题**：解读只读 ordered，并按 admissionMode 取 items/units；working-only 或
异形 ordered 会出现“旅程可解读、接口 no_plan”。

**实现**：

- 新增 `orderedEntryCount`（只数 ordered，按 mode）与 `planInterpretable =
  orderedEntryCount > 0`；
- `hasPlan` 继续表示 ordered ∪ working 有内容，用于“有没有草稿/历史方案”；
- `review_plan`/`interpret_admission` 的可用与阻断改用 `planInterpretable`：
  working-only → `plan_not_ordered`，unblock“先排成正式 ordered 方案”；
- `recommended_next` 在 `hasPlan && !planInterpretable` 时推荐 `fill_to_count`；
- 口径来源：与 `PlanAdmissionInterpretationFacade.buildEntries` 的 ordered/mode
  选择一致；抽取共享选择器或加 parity 测试（同一 fixture 的条目数相等）。
- **必须对齐 mode 拼写**：facade 现在只认 `"majorGroup"`，快照 canonical 还认
  `"major_group"`；两处统一走 canonical（facade 补 `"major_group"`），否则
  major_group 数据会出现“journey 可解读、接口 no_plan”。
- `orderedEntryCount` 数**非 null** 条目（facade 的 buildEntries 跳过 null）；
  加一组 majorGroup/major_group/含 null 的 parity fixture。
- `planContentDigest` 仍只是内容指纹，不作为可解读判据。

### 12.5 P2：人工审查与后端规则审查的生命周期

**事实**：

- `review_plan` 是只读人工审查，不清 Java `reviewState/staleFlags.review`；
- `reviewFreshness` 只表示**后端规则结果**是否新鲜；加入等写动作若 `rerunReview`
  会重跑并清 flag，不能用人工审查代替；
- 不得为了让推荐消失而人为清业务 stale。

**Agent 侧人工审查标记**：

- `working_set` 增加 `last_manual_review_digest` / `last_manual_review_version`；
- 回合 `taskIntent == "review"`（`responseType=review`）且快照有
  `planContentDigest` 时，记录当前 digest 与 `planVersion`；
- 注入层加“本版人工审查：已看过/未看过（与当前方案内容是否一致）”；
- `recommended_next`：`refreshRequirement=review` 且
  `manualReviewDigest == planContentDigest` → 不再推荐 `review_plan`，落到
  `interpret_admission`；若 digest 变了（方案内容变化）→ 重新推荐人工审查。
- 该标记是 Agent 进程内/WorkingSet 信号，重启丢失只会导致多推荐一次审查，不影响
  业务状态；不写 Java、不冒充规则审查。

**验收**：按真实回执判定——`rerunReview` 的写动作后 `reviewFreshness=fresh`；
未重跑的写动作后为 `stale`；人工审查前后 Java `reviewFreshness` 不变。

### 12.6 非阻塞一致性

1. `recommended_next` 必须是有效业务动作或元动作 `wait`/`continue_task`/
   `clarify`，不得给出 planned 动作。
2. 推荐优先级：安全/pending → 画像 → 组件 freshness（候选/方案）→ 未完成 TaskDraft →
   review/interpret。`continue_task` 只在 TaskDraft 未 blocked 且新鲜度已过时出现；
   旧候选上的 TaskDraft 不直接“继续”。
3. 能力说明区分：`priority_rules`（同档优先）已实现；风险姿态/目标优先级（J6）未接；
   “仅本次”按具体字段的真实生命周期写，不笼统承诺持久化。
4. `activeProposal` 与 `pendingStatus` 来自**同一次** pending 记录读取（§3.3）。
5. 已修正项（blocked 清账、按最终 operations 判 planned、真实事件形状、
   applying 检查顺序）保持。
