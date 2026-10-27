# 方案原子动作 v2（ProposalRequest.add_units）——复审

复审对象：`docs/superpowers/specs/2026-10-17-plan-action-contract-design.md`（v2，已整体重写）
代码基线：`616464c`（`wip/2026-09-28-p2-write-loop-green`）
前次审查：`docs/superpowers/reviews/2026-10-17-plan-action-contract-review.md`
复审日期：2026-10-17
复审方式：逐条核对 v2 第八节修订表与代码；不改代码、不改设计稿。

## 一、结论

**v2 方向正确，v1 的大部分 blocker 已实质解决；但仍有 3 个实施前必须钉死的阻塞点，不能按现稿直接开工。**

已解决/基本解决：
- B3 apply 早分支：设计写了在 `_execute_claimed_command` 最前面分流，跳过 `proposalApply`/canonical；方向正确。
- B4 回执链路：`PendingPlanningCommandRes`/`compactResultForReplay`/网关 `_action_result_payload`/前端白名单都列了。
- B5 review 语义：明确选 A（同事务回滚），并写了重读版本；方向正确。
- B6 schema：明确 `TURN_OUTPUT_SCHEMA` 接入与版本守门位置；方向正确。
- M1/M2/M4/M7/M8/M9：flag、prompt 目标、digest、重复确认、旧 pending、展示权威，均按前次意见改。

仍有阻塞（详见第三节）：
1. **B1 未真正落地**：v2 说 Java 用 `resolveEffectiveCandidates(state)`，但该方法在 `PlanningStateService` 里是 `private`；现有 prepare 路径 `generateUserGoalFixProposals` 用的是 `resolveCandidateFactsForProposalAnalysis(state)`（不含已确认硬约束/学费过滤）。按现稿实现，prepare 与 execute 仍可能不是同一候选集。
2. **B2 未真正落地**：`PrepareResultDTO.result` 是 `FixProposalStateDTO`（含 `proposals` 列表），不是 v2 示例里的单个 preview 对象。按 v2 的“沿用 score prepare 映射”会读不到 `title/summary/status`。另外 `prepared` 且 `pendingId=null`（blocked/info）没有映射规则。
3. **B6 新契约自相矛盾**：`ProposalTarget.school_name/major_name` 是必填非空字符串，`volunteer_id` 可选，validator 又写“名称或 ID 二选一”；ID-only target 在 Pydantic/schema 层就无法表达。且 `targets` 与 `goal_type=add_units` 的条件校验（add 必须非空、非 add 必须为空）没有 validator。

另有两个 major 会直接影响目标 5（legacy 不变）与验收：
- `add_units` 分支的“执行前重校验”是无条件的，会改变 legacy add_units 的旧行为（旧路径可能被 409），与 v2 目标 5/第八节“legacy 行为不变”冲突；必须按 flag/kind 分流。
- `runReview` 的 `reviewState.sourceVersion` 是**递增前**的版本（`PlanningStateService.java:2801` 先 set，`:2835` 才 +1）；v2 E2E 却要求“review 的 sourceVersion 与最终版本一致”，按现实现必红。需要改验收口径或明确语义。

## 二、B1–B6 / M1、M2、M4–M10 逐项状态

| 项 | v2 状态 | 结论 |
|---|---|---|
| B1 目标解析权威 | 部分解决 | 方向对（移到 Java），但 `resolveEffectiveCandidates` 私有、现有 prepare 用 raw 候选集；未说明如何在不改变 fill/priority/scope 的前提下接入。**剩余 blocker**。 |
| B2 prepare 响应 | 部分解决 | 嵌套 `result` 方向对，但 `result` 是 `FixProposalStateDTO.proposals[]`，不是单 preview；blocked/no-pending 映射缺失。**剩余 blocker**。 |
| B3 apply 早分支 | 基本解决 | 早分支位置、跳过 proposalApply/canonical、expectedPlanVersion 来源都对；但 dataValue `commandType/volunteerIds` 的落点未写到 `prepareUserGoalProposal`，且早分支控制流/`rerun_review` 客户端参数未写。**major**。 |
| B4 回执链路 | 基本解决 | DTO/replay/网关/前端都列了；实现时注意 `ConversationActionResult.as_dict` 与 `_action_result_payload` 两处都要加 `reviewState`。**major（实现细节）**。 |
| B5 review 语义 | 基本解决 | 选 A 一致；成功后重读版本正确。但 `reviewState.sourceVersion` 与最终版本不一致、review 失败无独立 code、`planningState` 是否替换为 post-review 未写。**major**。 |
| B6 schema | 部分解决 | `TURN_OUTPUT_SCHEMA` 接入写了；但 `ProposalTarget` ID-only 矛盾、targets 条件 validator 缺失、`targets` 对所有 ProposalRequest 变必填的兼容面未列全。**剩余 blocker（ID-only/条件校验）**。 |
| M1 legacy add_units | 部分解决 | `rerunReview` flag 对；但“执行前重校验”无条件，legacy 行为会变。**major**。 |
| M2 prompt/技能 | 基本解决 | 不改 legacy `prompt.py`、改 codex 四处、开关回滚两步，均对。缺“先 preview_candidates 拿准确名称/ID”和“非 add 也要输出 `targets: []`”的显式指令。**minor/major**。 |
| M4 digest | 解决 | “只覆盖模型输入”正确；注意 target 顺序可规范化、`UserGoalFixProposalReq` 要加 `targets` 字段。**minor**。 |
| M5 目标语义 | 基本解决 | 结果表、全有或全无、already_selected 例外、删 unit_id，均对。缺 names/ID 冲突、banned/locked 精确定义、no_plan/source_unavailable 的 Java 判定来源。**major**。 |
| M6 重校验/actualChanges | 基本解决 | 执行前重校验、不得覆盖硬约束、before/after diff 都对。但重校验未 gate legacy；diff 应围绕 select 而非 review 后；`generateOrderedPlan` 仍可能剔除。**major**。 |
| M7 重复确认 | 解决 | stale/已生效提示，不承诺同一结果。**minor**。 |
| M8 旧 pending | 基本解决 | 新 kind/旧 plan_mutation 拒绝对；但旧 pending 无 operationId，拒绝检查必须在 `operation_id_missing` 之前；row kind 与 dataValue kind 的关系要写清。**major**。 |
| M9 展示权威 | 解决 | Java 生成 affectedItems/summary/addedCount。**minor**（`FixProposalDTO` 需加 affectedItems 字段）。 |
| M10 测试 | 基本解决 | 清单更全；仍缺 ID-only/name-ID 冲突、prepare result `proposals` 形状、blocked/no-pending、resolveEffectiveCandidates 同池、review sourceVersion、legacy 重校验、非 add targets 等。**major**。 |

## 三、实施前必须钉死的阻塞点

### B1'. `resolveEffectiveCandidates` 不可直接调用，现有 prepare 用的不是同一候选集

**问题**
v2 3.2 写“候选来源：`PlanningStateService.resolveEffectiveCandidates(state)`（与 execute 同池）”。但：

- `resolveEffectiveCandidates` 是 `private`（`PlanningStateService.java:9426`），`UserGoalProposalBuilder` 在另一个类里，无法直接调用。
- 现有 prepare 路径 `generateUserGoalFixProposals` 先执行
  `state.getCandidatePoolState().setItems(resolveCandidateFactsForProposalAnalysis(state))`
  （`PlanningStateService.java:847-851`），该方法只做候选身份归一/overlay/分类补全，**不应用**
  `applyConfirmedPlanRequirements`（已确认硬约束 + 学费过滤）；而 execute 的 `selectWorkingPlanItems`
  用的是 `resolveEffectiveCandidates(null, chatSessionId, state, false)`（`:2218-2220`），**会应用**。
- `resolveEffectiveCandidates` 还有一个 `refreshOverlayIfNeeded` 参数：select 传 false，`generateOrderedPlan` 传 true（`:2391`）。v2 只说“相同”，没有说取哪一个。

**后果**
prepare 可能把“候选池里有、但被已确认硬约束/学费过滤掉”的条目标为 `ok` 并生成 ready 卡；execute 的 select 找不到它，按 v2 的新逻辑会 409，用户拿到一张必失败的卡。或者反过来，prepare 用 raw 池拒绝/放行的结果与 execute 不一致。

**最小修改**
- 在 `PlanningStateService` 增加包内可见方法（例如 `resolveEffectiveCandidatesForProposal(state)`），内部调用 `resolveEffectiveCandidates(null, state.getSessionId(), state, false)`；`UserGoalProposalBuilder` 与 `PlanningStateService` 同包，可直接用。
- 只在 `goalType=add_units` 时把该列表传给 builder（新增 `buildAddUnits(state, req, effectiveCandidates)` 或给 `build` 增加重载）；**不要**改变 fill/priority/scope 的现有 `resolveCandidateFactsForProposalAnalysis` 路径。
- 明确 refresh 参数：prepare 用 `false`（与 select 一致）；在测试里钉住 prepare 与 execute 对同一批 volunteerIds 的资格判断一致。
- 如果 `generateOrderedPlan` 的 `true` 刷新 overlay 后可能改变候选，测试要覆盖“prepare 后 overlay 刷新导致条目被剔除”的场景；要么在 execute 重校验时用同一 `false` 口径，要么明确接受并报失败。

### B2'. `PrepareResultDTO.result` 不是单个 preview，而是 `FixProposalStateDTO`

**问题**
v2 3.3 的示例：
```json
"result": { "proposalId": "...", "title": "...", "summary": "...", "status": "ready", ... }
```
实际 `prepareUserGoalProposal` 的 `PrepareOutcome` 第三参是 `preview`，类型是 `FixProposalStateDTO`（`PlanningStateService.java:873-926`；`FixProposalStateDTO.java:9-17`），其形状是：
```json
{ "status": "...", "proposalSource": "...", "sourceVersion": 5, "proposals": [ {FixProposalDTO...} ], "total": 1 }
```
没有顶层 `title/summary/status=ready`。v2 说“沿用 score prepare 的映射方式（`service.py:1446-1476`）”——score 的 `result` 是单个 `ScoreUpdatePreviewDTO`，不是这个状态对象；照抄会得到空 card。

**后果**
网关按 v2 示例读 `data.result.title` 会全空，卡片没有标题/摘要/状态，或把 `result.status`（state 级状态）误当卡片状态。

**最小修改**
- 网关复用**现有 proposal 分支**的提取逻辑（`service.py:2889-2902`）：先 `data.result`，再取 `result.proposals`，选第一条/ready 的 `FixProposalDTO`，再交给 `_proposal_preview_payload`。
- 设计 3.3 的示例改成真实形状：`result.proposals[0]` 才是 `proposalId/title/summary/status/strategy/requiresConfirmation/affectedItems/addedCount`。
- **blocked/info 无 pending**：`prepareUserGoalProposal` 在 `primary == null || requiresConfirmation != true` 时返回 `PrepareOutcome(null, null, preview)`（`PlanningStateService.java:881-883`）。此时 `PrepareResultDTO.status=prepared`、`pendingId=null`、`result=state`。必须明确：`pendingId == null` 或 `result.proposals[0].status != ready` → 渲染 blocked/info 卡、**不出确认按钮**；不能按 `prepared → ready`。
- `superseded` 可能没有 `result`（`ConversationProposalRequestService.replay`），要单独映射为“已被新预览取代”的 blocked 卡。

### B6'. `ProposalTarget` 的“名称或 ID 二选一”在 schema 层不成立

**问题**
v2 3.1：
```python
school_name: str = Field(min_length=1, max_length=80)
major_name: str = Field(min_length=1, max_length=120)
volunteer_id: str | None = Field(default=None, max_length=128)
...
if not (self.school_name.strip() and self.major_name.strip()) and not (self.volunteer_id or "").strip():
    raise ValueError("target requires schoolName+majorName or volunteerId")
```
但 `school_name`/`major_name` 是**必填非空字符串**；Pydantic 在 model validator 之前就会拒绝 `None`/空串。因此 ID-only 的 target **根本无法表达**，validator 的“or volunteerId”分支对合法输入不可达。v2 同时说“volunteerId 可选；名称与 ID 同时给时以核验后的 ID 为准”，语义自相矛盾。

另外，`targets` 与 `goal_type` 的条件约束没有 validator：
- `goal_type=add_units` 时 `targets` 必须非空；
- 非 `add_units` 时 `targets` 必须为空（v2 说“其他 goalType 传空列表”）；
- `add_units` 时 `target_count/tier_quota_goal/requirements/priority_rules/target_scopes` 应拒绝或明确忽略（v2 未说）。

**最小修改**
- 二选一：
  - **推荐**：`school_name`/`major_name` 改为 `str | None = None`，validator 要求 `(school && major) || volunteer_id`；strict schema 下 nullable；Java DTO 允许 null；并规定 names 与 ID 同时给时必须一致，不一致 → `target_mismatch`（不能“以 ID 为准”静默接受）。
  - 或者：名称必填，**删除** `volunteer_id` 或把它降为“仅展示/交叉校验”的可选字段，并删除“or volunteerId”的语义。第一期从 `recommendation.preview_candidates` 复制准确名称即可。
- 增加 `ProposalRequest` model validator：
  - `add_units` ↔ `targets` 非空；
  - 非 `add_units` → `targets` 必须为空；
  - `add_units` 拒绝 `target_count/tier_quota_goal/requirements/priority_rules/target_scopes`（或明确写入“忽略”，但不要静默混用）。
- 增加 schema 测试：ID-only、names-only、both、neither、add with empty targets、non-add with targets、add with target_count/requirements。

## 四、因“扩展 ProposalRequest”引入的新问题

1. **`targets` 与既有 `targetScopes`/`requirements` 语义重叠（major）**
   `ProposalRequest` 已有 `target_scopes`（范围 OR 匹配）、`requirements`（coverage）和 `negative_scopes`；新增 `targets` 是精确学校+专业配对。模型很容易把 add_units 的目标写进 `targetScopes` 或 `requirements`，Java add 分支只读 `targets`，结果被忽略/blocked。设计要求：
   - `targets` 的 schema description 明确“仅 add_units 使用；不要写进 targetScopes/requirements”；
   - prompt/`.write.md`/三个 SKILL 给出对象数组示例；
   - Java add 分支对非空 `targetScopes/requirements/priority_rules` 明确拒绝，不静默。
   如果担心命名混淆，可考虑把字段命名为 `addTargets`/`exactTargets`（v2 现在叫 `targets`）。

2. **`targets` 对所有 ProposalRequest 变必填（major）**
   `_strict_model_schema` 把所有 properties 设为 required（`service.py:259-268`），所以非 add_units 的提案也必须输出 `targets: []`。v2 第六节风险 2 已意识到，但需要列全落地点：
   - `test_turn_output_schema.py`（proposal required 集合）；
   - `test_gateway_contracts.py:421`、`test_gateway_output_repair.py:663`、`test_shadow_gateway.py` 的 proposalRequest fixture；
   - `skills/codex/developer_instructions.write.md` 与三个 SKILL 的 proposal 示例；
   - 模型侧 schema 的 `targets` description 要写“非 add_units 传 []”。
   这些 fixture 用 Pydantic 默认 `[]` 仍能解析，但模型输出/schema 断言会变；S1 必须一起改，否则“模型漏 targets → 修复回合”会出现在所有既有提案路径上。

3. **`RepairProposalTaxonomy` 没有 `add_units` strategy（major/minor）**
   `RepairProposalTaxonomy.Strategy`（`RepairProposalTaxonomy.java:43-58`）没有 ADD_UNITS；`normalizeStrategy("add_units")` 原样返回 "add_units"，`buildProposal` 会落到 `buildBlockedProposal(REASON_ENGINE_NOT_READY)`，除非新增分支。`STRATEGY_ACTION_TYPES` 也没有 add_units。设计要求：
   - 新增 `Strategy.ADD_UNITS = "add_units"` 与 `STRATEGY_ACTION_TYPES` 映射到 `ADD_VOLUNTEERS`；
   - `UserGoalProposalBuilder.buildProposal` 在 fallback 前加 add 分支；
   - title/message/strategy label 加“加入志愿预览”。
   注意 `RepairProposalApplyPolicy.isUserGoalApplyableStrategy`（`RepairProposalApplyPolicy.java:76`）不含 add_units；add_units 不走 `apply_plan_change_proposal`，但如果有通用 UI/校验用到它，需显式排除或加入。

4. **`prepareUserGoalProposal` 没有写 `commandType/volunteerIds/kind`（major，接近 blocker）**
   v2 3.3 要求 pending dataValue 有 `kind=plan_action/actionFamily=add_units/commandType=add_units/volunteerIds`，但现有 `prepareUserGoalProposal`：
   - `upsert.setKind("plan_change_proposal")`、`setActionFamily("apply_plan_change_proposal")`（`PlanningStateService.java:914-915`）；
   - dataValue 只有 `operationId/proposalSource/userGoalRequest/sourceVersion/proposalId/canonical*`（`:885-906`）；
   - 没有 `commandType`、没有 `volunteerIds`。
   如果按现稿只加 builder 分支而不改 prepare：
   - 网关早分支 `active_data.get("commandType") == "add_units"` 永远不命中，会掉回 proposalApply 路径；
   - 即使命中，`volunteerIds` 为空，execute 报 40001。
   最小修改：在 `prepareUserGoalProposal` 里按 `req.getGoalType()` 分支：
   ```
   boolean addUnits = "add_units".equalsIgnoreCase(req.getGoalType());
   upsert.setKind(addUnits ? "plan_action" : "plan_change_proposal");
   upsert.setActionFamily(addUnits ? "add_units" : "apply_plan_change_proposal");
   dataValue.put("commandType", addUnits ? "add_units" : ...);
   dataValue.put("goalType", req.getGoalType());
   dataValue.put("volunteerIds", primary.getAffectedVolunteerIds());
   ```
   并明确 row kind 与 dataValue `kind` 的关系；如果保留 row kind=`plan_change_proposal`，早分支只依赖 dataValue 也可行，但不要同时声称“新 pending kind=plan_action”而未列修改点。

5. **`prepareOnce` digest 与 target 顺序（minor）**
   digest 只覆盖模型输入是对的；但 `targets` 是列表，模型重试/修复若改变顺序，digest 会变。建议在计算 digest 前对 targets 做稳定排序（按 schoolName/majorName/volunteerId），或在设计里明确“顺序变化视为不同输入”。`UserGoalFixProposalReq` 必须加 `targets` 字段，否则 Java 收不到。

6. **`targets` 命名与 `targetScopes`（见第 1 条）**
   如果保留 `targets`，必须在 schema description 和 prompt 里反复强调两者区别；否则这是最可能的新 model-confusion 点。

7. **`FixProposalDTO` 没有 `affectedItems/addedCount`（minor/major）**
   v2 3.3 示例要求 `result.proposals[0].affectedItems/addedCount`，但 `FixProposalDTO`（`FixProposalDTO.java:9-34`）只有 `affectedVolunteerIds/affectedUnitIds/actions/...`。S2 必须新增字段，或网关从 `actions[].volunteerIds` + 候选行/`detail` 生成。建议新增结构化 `affectedItems`，避免前端解析 `actions.detail` 文本。

## 五、v2 关键点的逐条结论

### 1) apply 早分支是否有新阻塞

**设计方向正确，无新阻塞，但有 3 个实现细节必须写死：**
- `active_data.commandType/volunteerIds` 的来源（见第四节第 4 条）：`prepareUserGoalProposal` 必须落 dataValue；否则早分支不命中。
- 控制流：`_execute_claimed_command` 现有结构里 `command_type`/`expected_plan_version` 只在 score/proposal 分支内赋值；早分支若只 `if` 不 `return`，后面会引用未定义变量。建议把 add 分支做成独立函数并直接返回结果，或提前设置 `command_type=ADD_UNITS`、`expected_plan_version` 并 `if/else` 跳过 proposal 分支。
- `rerun_review=True` 要沿 `_execute_claimed_command` → `internal_client.execute_pending_planning_command` → `PendingPlanningCommandReq` 全链传下去；当前 client 签名（`internal_client.py:1830-1847`）没有该参数。
- 还应跳过 `_resolve_region_scope_ids`/`_resolve_major_scope_ids`（v2 只写了跳过 proposalApply/canonical），避免无谓调用。

### 2) Java `resolveEffectiveCandidates` 解析是否有新阻塞

**有（B1'）**：方法 private、现有 prepare 用 raw 候选集、refresh 参数未定。按第三节 B1' 的最小修改落地后，方向正确。

### 3) review 语义 A 是否有新阻塞

**无方向性阻塞，但有 2 个必须修正的验收/语义点：**
- **`reviewState.sourceVersion` 与最终版本不一致**：`runReviewInternal` 在 `PlanningStateService.java:2801` 先 `reviewState.setSourceVersion(state.getVersion())`，`:2835` 才 `state.setVersion(version+1)`。所以 reviewState.sourceVersion = 被审方案的版本 N，最终 state version = N+1。v2 E2E 要求“review 的 sourceVersion 与最终版本一致”必红。建议：把验收改为“reviewState.sourceVersion = 审查时的方案版本；resultPlanVersion = N+1”，或明确产品是否要求相等（若要求，需改 `runReview` 的 sourceVersion 赋值，影响所有审查消费者，不建议第一期）。
- **review 失败需要独立 code/文案**：v2 要求卡片显示“未生效（审查失败）”，但 `runReview` 抛出的可能是 40901/writeCasConflict 或内部异常；网关只能看到通用失败。建议在 `PendingPlanningCommandBizService` 捕获 review 异常并转成独立业务码（如 `40907 review_failed`），或在 response 里带 `reviewStatus=failed`；否则卡片无法区分“加入失败”与“审查失败”。
- 另外：review 成功后应把 `result.planningState` 也替换为重读后的 state，而不只是 `resultPlanVersion`；否则结果里的 `planningState.reviewState/orderedPlanState` 可能还是 review 前的。

### 4) actualChanges/reviewState 全链是否有新阻塞

**无方向性阻塞**；v2 列了 DTO/replay/网关/前端。实现时注意：
- `ConversationActionResult.as_dict` 当前只带 `actualChanges`，不带 `reviewState`；要加。
- `server._action_result_payload` 当前明确不带 `actualChanges`；要加，且成功/失败两处（`:1164`、`:1478`）都走它。
- `_native_reply_frame` 用 `result["actionResult"]` 整体序列化；`as_dict` 加了字段就自动带上，但前端 `conversationEvents.mjs:43` 与 `ProposalCard.tsx:101` 要同步。
- `actualChanges` 建议围绕 `selectWorkingPlanItems` 前后做差（不是 review 后），否则 `generateOrderedPlan` 的 sync/enforce 可能把无关变化算进去；并明确“add 的 net 新增”与“requested volunteerIds”的关系。

### 5) strict schema 的 targets 必填是否有新阻塞

**有（B6'）**：
- ID-only target 无法表达（school/major 必填非空 vs “or volunteerId”）。
- 缺 `add_units ↔ targets` 条件 validator；非 add 的 `targets` 处理没有校验。
- `targets` 对所有 ProposalRequest 变必填的兼容面未列全（schema/fixtures/prompt）。
- `targets` 与 `targetScopes/requirements` 的语义重叠未在 schema/prompt 里隔离。

### 6) 是否可进入实施

**修完 3 个 blocker（B1'、B2'、B6'）后可进入实施；修完前不建议开工。**
最小修改清单：
1. B1'：加包内 `resolveEffectiveCandidatesForProposal(state)`；只在 add_units 分支传入 effective candidates；明确 refresh=false；测试 prepare/execute 同池。
2. B2'：网关按 `result.proposals[]` 提取 preview；blocked/info/`pendingId=null` 不按 ready；`superseded` 单独映射；更新 v2 3.3 示例。
3. B6'：`ProposalTarget` 名称/ID 二选一改成真实可表达（推荐 names nullable）；加 `ProposalRequest` 条件 validator；补 schema/测试。
4. 实施中必须同时修：legacy 重校验 gate（M1/M6）、review sourceVersion/失败 code（B5 残项）、prepare dataValue `commandType/volunteerIds/kind` 落点（B3 残项）、`RepairProposalTaxonomy` add strategy、`FixProposalDTO.affectedItems`、`targets` 兼容面。

## 六、测试补充（在 v2 第五节基础上）

- 契约：ID-only/names-only/both/neither；add with empty targets；non-add with targets；add with `target_count/requirements/priority_rules/target_scopes`；`targets` required 对所有 proposal；names/ID 冲突。
- prepare：`result.proposals[0]` 形状；`pendingId=null`（blocked/info）不生成按钮；`superseded/preparing`；sourceVersion mismatch；`PrepareResultDTO.status=prepared` 不直接当卡片状态。
- 候选：`resolveEffectiveCandidates` 与 execute 同池；prepare 后 overlay/硬约束变化 → execute 409；无候选池/`statusCode=not_generated` 与 `candidate_source_unavailable` 的区分。
- 名称：学校/专业精确名、方向括号、别名（若承诺）；`displaySchoolName` 优先；同名多组/同校多专业 ambiguous。
- apply：早分支不调用 proposalApply/canonical；`commandType/volunteerIds` 来自 dataValue；`rerun_review` 全链；legacy add_units 不带 flag 行为不变（尤其重校验）。
- review：review 失败回滚（A）；失败 code/文案；成功重读 version；`planningState` 为 post-review；`reviewState.sourceVersion` 与 result version 的关系。
- 回执：actualChanges/reviewState 成功/失败两路；`as_dict`/`_action_result_payload`/v1 事件/前端白名单/卡片；replay 保留。
- 兼容：既有 proposalRequest fixture/模型 schema 加 `targets: []`；`test_turn_output_schema`/`test_gateway_contracts`/`test_gateway_output_repair`/`test_shadow_gateway`；legacy `prompt.py` 不动。
- e2e：六条 + 反例；真实候选文件；`reviewState.sourceVersion` 按实际语义断言，不要写“与最终版本一致”。

## 七、关键证据索引

- `resolveEffectiveCandidates` private：`zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java:9426`；prepare raw：`:847-851`；select 用 effective：`:2218-2220`；generate 用 true：`:2391`。
- prepare result shape：`PlanningStateService.java:866-927`；`FixProposalStateDTO.java:9-17`；现有 proposal 分支取 proposals：`zhiyuan-agent/app/gateway/service.py:2889-2902`。
- prepare hardcoded kind/actionFamily：`PlanningStateService.java:908-916`；dataValue 无 commandType/volunteerIds：`:885-906`。
- review sourceVersion：`PlanningStateService.java:2801`、`:2835`；review 重读范式：`:1254-1262`。
- add_units 分支：`PendingPlanningCommandBizService.java:171-186`；结果字段：`:214-237`；compact：`:294-327`。
- 早分支现状：`zhiyuan-agent/app/gateway/conversation_actions.py:778-937`；client 签名：`zhiyuan-agent/app/util/internal_client.py:1830-1847`。
- 回执：`conversation_actions.py:68-76`；`server.py:1083-1105`；`conversationEvents.mjs:43`；`ProposalCard.tsx:101`。
- schema：`service.py:57-75`、`:259-295`；`contracts.py:11-19`；`test_turn_output_schema.py:47-64`。
- taxonomy：`RepairProposalTaxonomy.java:43-58`、`:96-103`、`:187-188`、`:266-283`；`RepairProposalApplyPolicy.java:76`。
- Java 名称匹配：`UserGoalProposalBuilder.java:2709-2714`（containsLoose）、`:2469-2475`（matchesAny OR）；`CatalogService.java:73-94`（lookup exact）、`:170-182`（search keyword）。
- 候选池状态：`CandidatePoolStateDTO.java:14-15`；`CandidatePreviewService.java:50`（candidate_source_unavailable 仅预览侧）。
- 旧 pending：`zhiyuan-agent/app/zhiyuan_agent/tools.py:7112-7129`、`:7203-7306`、`:7451-7454`；网关 operationId：`conversation_actions.py:813-817`。
