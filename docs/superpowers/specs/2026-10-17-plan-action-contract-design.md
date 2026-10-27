# 方案原子动作进入 codex 写闭环设计（v6：ProposalRequest.add_units）

日期：2026-10-17（v6：2026-10-18 产品口径拍板）。代码基线：`616464c`
（`wip/2026-09-28-p2-write-loop-green`）。
状态：**v6，已按三轮独立审查 + 执行层审查修订，并纳入 2026-10-18 产品口径；待最终确认后
进入实现/部署。**

## 〇、产品口径拍板（2026-10-18）

1. **点名加入默认 EXPAND（扩总数）**：用户说“加进去 / 补几条”且方案已在目标数时，默认
   `total = 当前实际数 + 新增数`（如 45→51），预览明确展示总数变化、**零删除**；
   不静默替换。
2. **REPLACE 是显式语义，不是默认**：用户明确说“总数不变 / 必须有这几条 / 换掉几条”时，
   走“加入 + 等量替换”：预览必须同时列出**新增与移出**的完整集合；未确认不得删除任何
   原条目。纯加入语义含糊时问一次封闭问题（扩总数 / 保持总数替换 / 先看替换清单）。
   第一期只实现 EXPAND；REPLACE 作为下一纵切，当前不得用 add_units 静默代替。
3. **scope / 学费类意向默认持久**（`persist=true`）：应用后进入 ConstraintState/ProfileState，
   后续重新生成仍生效；只有用户明确说“这次 / 仅本次 / 先看看”才 `once`，卡上必须写明。
4. **风险姿态 = 稳健 / 均衡 / 进取 + 目标优先级排序**：用户可用“保专业 / 保学校 / 保录取 /
   城市优先”等表达优先级；系统内部映射为安全 floor、结构目标与软效用权重，面向用户只讲
   取舍（“更稳但上限低 / 学校更好但保底少”），不甩系数/权重。

审查记录：
- v1：`docs/superpowers/reviews/2026-10-17-plan-action-contract-review.md`（6 blocker）
- v2：`docs/superpowers/reviews/2026-10-17-plan-action-contract-review-v2.md`（3 blocker + major）
- v3/v4：`...-review-v3.md` / `...-review-v4.md`（apply/回执/40907/40905；请求校验与
  targetCountOverride 口径）
- 执行层审查（2026-10-17 追加）：数量/配额冲突、成功状态、确认内容绑定、review 版本、
  target 契约；已并入本稿执行完整性节。

**进度口径更正**：`616464c` 的 prompt/技能调整**没有**形成 codex 的点名加入可执行闭环；
它只是修正了指令引用。真正的闭环由本设计定义，未实现前不能说“点名加入已支持”。

## 一、问题与断层

用户要把六条“具体院校+专业”加入现有方案。codex 运行时做不到，原因是新写闭环只迁了
“用户目标”，没迁“方案原子动作”：

- legacy 有 `add/remove/move/replace/sort/generate/regenerate_order/pin_lock`
  （`app/zhiyuan_agent/tools.py:211`）；Java 有 `ADD_UNITS`/`REPLACE_UNITS`
  （`PendingPlanningCommandBizService.java:42/171`）；
- codex 工具面只有只读 MCP（`app/mcp_server/server.py:43`），`preview_plan_action` 不可见；
- `ProposalRequest` 只有六个 goalType（`app/gateway/contracts.py:305-312`），没有 add/targets；
- 网关 prepare 只走 user-goal / score / career（`app/gateway/service.py:2871` 等）；
- 网关 apply `_command_for_goal` 只认 fill/priority/scope（`conversation_actions.py:742-775`）。

`must_include_scope` 不能替代：它按 scope **OR** 匹配（`UserGoalProposalBuilder.java:2469-2475`），
方案未命中时最多补 **1 条**（`:1297-1347`），不能表达“学校 A 且专业 B”的多条精确加入。

## 二、目标与非目标

### 目标（第一期）

1. 模型用 `proposalRequest(goalType="add_units", exactTargets=[{schoolName, majorName}])`
   表达点名加入；不新增第四种草稿，不暴露写工具。
2. Java prepare 用**与 execute 相同的 effective candidates**解析 targets，校验唯一/歧义/
   已在方案/资格/banned/locked；生成 `status=ready` 的加入预览 pending（Java 产出 operationId）。
3. **纯加入保证**：用户在卡上确认“加入 N 条 + 总数/必要的约束调整”后，执行结果必须满足：
   全部新增项在最终 working/ordered plan 中；未确认删除任何原条目；数量/配额与预览一致；
   不满足整笔回滚。不能出现“确认加入 6 条，实际被重生成挤掉或被替换”。
4. **确认内容绑定**：执行时 Java 以 pending 中冻结的命令为准，不接受调用方换内容；operationId、
   commandType、volunteerIds、targetCountOverride、rerunReview 都纳入冻结摘要。
5. **显式成功**：只有后置条件通过后才返回 `applied`（status + postconditionReport）；
   网关不得把 HTTP/业务码成功直接当执行成功。
6. 预览卡逐条显示 Java 解析出的加入项、总数/配额变化、**不删除既有条目**；确认后显示实际
   加入项、后置条件结果与审查摘要（`actualChanges`/`reviewState` 全链贯通）。
7. 不改变 fill/priority/scope、score、career 三条写入路径；legacy add_units 行为不变。

### 非目标

- 不实现 remove/replace/move/sort/pin/generate 的 codex 契约；后续另立设计。
- 不暴露 legacy `preview_plan_action` 给 codex；不把写工具塞进只读 MCP。
- 不改 Java solver / 候选池生成 / 录取率 / 审查规则。
- 不改 legacy `app/zhiyuan_agent/prompt.py` 20c。
- 不做完整“确定性变更/审查回执”系统；第一期只做 add 的 actualChanges/reviewState。
- 不做多 worker / 分布式 pending。
- 第一期不支持“加入并同时调整已确认的冲稳保精确配额”（见 4.2），该场景阻断并提示；
  未来用组合动作/替换动作处理。

## 三、契约

### 3.1 ProposalRequest 扩展

字段名用 **`exact_targets`**（camel `exactTargets`），与既有 `target_scopes`/`requirements`
明确区分：

```python
class ExactTarget(_ContractModel):
    school_name: str | None = Field(default=None, max_length=80)
    major_name: str | None = Field(default=None, max_length=120)
    volunteer_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _require_identifier(self):
        names = bool((self.school_name or "").strip() and (self.major_name or "").strip())
        vid = bool((self.volunteer_id or "").strip())
        if not names and not vid:
            raise ValueError("exactTarget requires schoolName+majorName or volunteerId")
        return self

class ProposalRequest(_ContractModel):
    goal_type: Literal[..., "add_units"]
    exact_targets: list[ExactTarget] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _validate_exact_targets(self):
        is_add = self.goal_type == "add_units"
        if is_add and not self.exact_targets:
            raise ValueError("add_units requires exactTargets")
        if not is_add and self.exact_targets:
            raise ValueError("exactTargets is only supported for add_units")
        if is_add and (self.target_count is not None or self.tier_quota_goal is not None
                       or self.requirements or self.priority_rules or self.target_scopes
                       or self.negative_scopes or self.quality_guards
                       or self.tradeoff_guards or self.source_review_issue_codes):
            raise ValueError("add_units cannot mix with count/requirements/priority/tier/scopes/guards")
        return self
```

- 支持 names-only / ID-only / both；both 时 Java 必须交叉校验（ID 对应的学校/专业与名称一致，
  不一致 → `target_mismatch`，不静默以 ID 为准）。
- 第一期不设 unit_id；`add_units` 只消费 volunteerIds。
- **第一期 `add_units` 只表达 EXPAND**（默认扩总数）；REPLACE（总数不变、必须有、换掉）
  需要后续 `addPolicy=replace` 纵切，当前不得用 add_units 静默替代。纯加入语义含糊时先问
  一次（扩总数 / 保持总数替换 / 先看清单）。
- `max_length=20`；字符串 strip + 长度上限。
- **严格 schema**：`exact_targets` 及 `ExactTarget` 字段全部 required（nullable 可为 null）；
  非 add_units 的提案必须输出 `exactTargets: []`。S1 同步 `TURN_OUTPUT_SCHEMA`、
  `test_turn_output_schema.py`、`test_gateway_contracts.py`、`test_gateway_output_repair.py`、
  `test_shadow_gateway.py`、`.write.md`、三个 SKILL。schema description 写明“非 add_units
  传 []，不要写进 targetScopes/requirements”。
- **版本守门**：`source_version_guard == snapshot_version`；检查放进
  `validate_turn_output`/`_validate_round`（`stale_state` 可修复），新增
  `_PROPOSAL_VERSION_REPAIR_HINT`，可走一次修复回合。
- `responseType=text`、`executionStatus=partial`（预览已生成、写入待确认）；`.write.md` 写明。

### 3.2 Java 解析与纯加入预检

#### 3.2.1 同池解析

- 新增包内 `PlanningStateService.resolveEffectiveCandidatesForProposal(state)`：
  `return resolveEffectiveCandidates(null, state.getSessionId(), state, false);`
  （`refreshOverlayIfNeeded=false`，与 `selectWorkingPlanItems` 一致）。
- 仅在 `goalType=add_units` 分支传给 `UserGoalProposalBuilder.buildAddUnits(...)`；
  fill/priority/scope 的 `resolveCandidateFactsForProposalAnalysis` 路径不变。
- 解析：学校名+专业名必须同时命中（规范化/别名/方向括号）；ID 必须在 effective candidates；
  both 时交叉校验；结果表同 v3（ok/already_selected/ambiguous/no_match/not_in_pool/
  target_mismatch/banned/locked/no_plan/candidate_source_unavailable）。
- 全有或全无（already_selected 例外）；不覆盖已确认硬约束；专业组按 volunteerId。
- `no_plan` / `candidate_source_unavailable` 的 Java 判定来源必须写死：
  - `no_plan`：`workingPlanState.items` 与 `orderedPlanState.items` 都为空（或 working plan
    缺失）；提示“当前没有正式方案，先补方案再加”。
  - `candidate_source_unavailable`：`candidatePoolState` 为空/`items` 为空，或
    `candidatePoolState.statusCode` 表示尚未生成（`not_generated`）；与 `no_match` 分开，
    不能把“候选源不可用”报成“没有这个专业”。

#### 3.2.2 数量/配额：预检 + 冻结（P1-1 核心）

`add_units` 不是“只往 working plan 塞几条”那么简单：`generateOrderedPlan` 会执行
`CanonicalPlanningRuntime.enforceSelection`（`CanonicalPlanningRuntime.java:40`），按已确认的
总数/档位配额重新求解，可能把新增项挤掉或替换原条目（`PlanningStateService.java:2338-2410`）。
因此 prepare 必须把“数量/配额变化”作为**提案的一部分**冻结，并做纯加入预检：

**数量口径必须先定**：`CanonicalPlanningRuntime` 的 `countMode` 在院校专业组模式下是
`unit`（单元数），其余是条目数（`CanonicalPlanningRuntime.java:50-54`、`:65-78`）。
`targetCountOverride` 只能取 **当前 working plan 实际数量 + 本次新增数量**，且两个数量必须
用同一个 mode：

- `countMode == "unit"`（专业组）：
  `currentCount = 当前 working plan 单元数`；`addedCount = 新增单元数（distinct unitId）`；
  `targetCountOverride = currentCount + addedCount`。同组多专业（6 条落 2 个组）只加 2 个单元，
  **不能**按 6 条算。
- `countMode == "entry"`（专业+大学）：
  `currentCount = 当前 working plan 条目数`；`addedCount = 新增条目数`；
  `targetCountOverride = currentCount + addedCount`。

分场景：

- **无已确认总数/配额**：加入后总数自然增长（`resolvedSelectionTarget` 用 current.size()）；
  预览显示 `当前 currentCount → currentCount+addedCount`，无 override。
- **有已确认总数**（`hardPlanningObjectives.selectionTargetCount`）：
  - **先校验一致性**：若 `currentCount != confirmedTarget`（如当前 40、目标 45），
    **阻断**，预览明确“当前方案实际 40，与已确认目标 45 不一致；请先补齐/调整目标，再加入”，
    不能静默用 45+addedCount 把用户意图放大；
  - 一致时：`targetCountOverride = currentCount + addedCount`，预览明确写
    “总数 45 → 51（按当前 45 + 新增 6 计算）”；用户确认卡即同时确认总数变化；
  - 执行前把它写入已确认目标（同一事务），再 enforceSelection，避免按旧目标裁剪；
  - 若用户不想改总数，应改用替换动作（第一期不支持）；预览阻断并说明。
- **有已确认的精确档位配额**（冲/稳/保 exact_counts/range/ratio）：
  - 第一期**阻断**，预览明确“加入会改变已确认的冲稳保配额；请先调整配额或改用替换”；
  - 不静默改配额、不静默替换原条目。
- **纯加入预检（dry-run）**：用当前 state 的副本 + frozen command（含 targetCountOverride）
  跑一次选择求解（不落库），验证：
  1. 全部请求新增项在解中；
  2. 全部原 working plan 条目仍在解中（**零删除**）；
  3. 解的总数 = targetCountOverride（按 countMode）、档位分布符合 override/预期。
  任一条不满足 → 预览 blocked，给出会删除/替换的条目与原因，不生成可确认卡。
  - 若 `CanonicalPlanningRuntime.hasSelectionObjectives(state)` 为 false（没有选择目标，
    enforceSelection 不执行）：纯加入天然安全，可不跑 dry-run；
  - 有选择目标但 dry-run 在该环境不可用 → **一律阻断 add 预览**（不能出“ready 但可能
    执行后 40905”的卡）；目标环境必须支持 dry-run，E2E 要验证。
- 预览卡固定包含：新增条目、`removedCount=0`、`countMode`、`currentCount`、
  `addedCount`、`targetBefore`（已确认目标或当前数）、`targetAfter`、档位 old→new、
  “不删除任何现有条目”与后置校验说明；条目数与单元数同时展示时，override 只用 countMode
  对应的那个。

#### 3.2.3 prepare 结果与 dataValue

`PrepareResultDTO.result` 是 `FixProposalStateDTO`（含 `proposals[]`），不是单 preview：

```json
{
  "status": "prepared", "pendingId": "...", "operationId": "...",
  "result": {
    "status": "ready", "sourceVersion": 5,
    "proposals": [{
      "proposalId": "ugp_...", "title": "加入志愿预览",
      "summary": "将加入 6 条；总数 45→51；不删除现有条目",
      "status": "ready", "strategy": "add_units", "requiresConfirmation": true,
      "affectedItems": [{"schoolName": "...", "majorName": "...", "tier": "冲"}],
      "addedCount": 6, "removedCount": 0,
      "targetCountBefore": 45, "targetCountAfter": 51
    }],
    "total": 1
  }
}
```

- 网关复用现有 proposal 分支（`service.py:2889-2902`）取 `result.proposals[0]`；不要按 score
  prepare 的单一 preview 形状读。
- 状态映射：`pendingId != null && proposal.status==ready` → 卡片 ready 出按钮；
  `pendingId == null` 或 proposal 非 ready → blocked/info 无按钮；`duplicate` → 同一 pending；
  `superseded` → blocked“已被新预览取代”；`preparing` → info“生成中”；`prepared` 不透传。
- pending dataValue 必须落 **frozenCommand**（见 4.1）、`commandDigest`、`kind=plan_action`、
  `actionFamily=add_units`、`commandType=add_units`、`goalType=add_units`、`volunteerIds`、
  `targetCountOverride`（可空）、`tierQuotaOverride`（第一期恒空）、`sourceVersion`、
  `operationId`、`summary`、`affectedItems`。
- `prepareUserGoalProposal` 按 goalType 分支写 kind/actionFamily/commandType/goalType/
  volunteerIds；非 add_units 保持现有值。
- 幂等 digest 只覆盖模型输入（goalType、exactTargets 稳定排序、rawText、sourceVersionGuard），
  不覆盖解析结果；同 requestId 重试即使候选池变化也返回同一 pending。
- 单槽/applying/supersede 沿用 `prepareOnce` + `PendingConfirmationBizService.upsert`。

### 3.3 prompt / 技能

- **不改** `app/zhiyuan_agent/prompt.py` 20c（legacy direct agent 的 `preview_plan_action`
  真实存在）。
- codex 侧改四处：
  - `skills/codex/developer_instructions.md`：点名加入 →
    `proposalRequest(goalType="add_units", exactTargets=[{schoolName, majorName}])`；
    `must_include_scope` 不是点加入；**先调 `recommendation.preview_candidates` 复制候选里的
    准确学校/专业名称**（Java 侧没有 Python legacy 那套别名 resolver，名称必须来自候选行）；
  - `skills/codex/developer_instructions.write.md`：goalType 列表加 add_units；三者互斥不变；
    `responseType=text` + `executionStatus=partial`；非 add 输出 `exactTargets: []`；
    对象数组示例，禁止字符串数组；
  - 三个 SKILL（planner-routing / candidate-recommendation / plan-construction）：同规则，
    删除 `preview_plan_action` 引用。
- 开关：部署后默认 on；回滚 = 关闭 `PLAN_ACTION_CONTRACT_ENABLED` **并回退 plugin/prompt
  版本**（两步），避免模型继续教用户一个已禁用能力。
- plugin cachebuster + `codex plugin add` + 重启 18291。

## 四、执行完整性（v5 核心）

### 4.1 冻结命令与确认内容绑定（P1-3）

prepare 成功后，pending dataValue 写入规范化的 frozen command：

```json
{
  "commandType": "add_units",
  "operationId": "java-prepare-operation-id",
  "volunteerIds": ["...", "..."],
  "targetCountOverride": 51,
  "tierQuotaOverride": null,
  "rerunReview": true,
  "sourceVersion": 5
}
```

- 计算 canonical JSON 的 SHA-256 作为 `commandDigest`，一并写入 pending。
- 执行时 Java **从已认领的 pending 读取 frozenCommand**，不信任调用方传入的
  volunteerIds/commandType/targetCountOverride/rerunReview；调用方只提供
  `commandType=add_units`、`pendingId`、`operationId`、`claimToken`、`expectedPlanVersion`。
- **请求校验顺序必须改**：当前 `PendingPlanningCommandBizService.validate` 要求 add_units
  的 `volunteerIds` 非空（`:381-384`），而客户端总是发 `volunteerIds: []`
  （`internal_client.py:1848-1856`）——会在读 frozenCommand 前 40001。实现必须：
  1. add_units 允许请求层 `volunteerIds` 为空/省略；`commandType` 仍必填；
  2. **先**锁定 pending、读取 frozenCommand，再校验/比较请求字段；
  3. 请求带了 volunteerIds/rerunReview/targetCountOverride 时，与 frozen 逐项比较；
     不一致 → `40908 command_content_mismatch`；
  4. 客户端 add_units **不要发送** volunteerIds/rerunReview（只发 5 个字段），避免把
     “未提供”与“空列表”混为一谈。
- **篡改优先级**：40908 比较必须发生在 `getByOperationId`/replay 的 requestDigest 40903
  **之前**；否则篡改字段会先被 replay 判成 40903，不是承诺的 40908。
- `operationId` 必须与 pending 一致，且已纳入 frozenCommand/digest；`rerunReview` 纳入冻结
  摘要，不能由调用方在确认时切换。
- 这一条同时覆盖“重复确认不换内容执行”：replay 只按同一 operationId + 同一 digest 返回。

### 4.2 执行步骤（Java `add_units`）

1. 校验 pending/claim/revision/operationId/expectedPlanVersion；读取 frozenCommand。
2. 用 effective candidates 重校验 volunteerIds（新路径才做；legacy 不 gate 到这条逻辑）。
3. **应用冻结的数量变化**：若 `targetCountOverride != null`，在同一事务中更新已确认目标
   `hardPlanningObjectives.selectionTargetCount`（这是用户在卡上确认过的变化；预览必须展示）。
   override 是 **当前 working plan 实际数量（按 countMode）+ 本次新增数量（同 countMode）**，
   不是“已确认目标 + 条目数”；unit mode 必须用 addedUnitCount。`tierQuotaOverride` 第一期
   恒空；有精确档位配额时 prepare 已阻断。
4. `selectWorkingPlanItems(volunteerIds)`；记录 select 前后的 working plan volunteerId 集合；
   按 countMode 计算 before/after 的条目数与单元数。
5. `generateOrderedPlan(force=true)`；`enforceSelection` 以 override 目标求解。
6. **后置条件校验（新路径必须，先于成功返回）**：
   - **仅新路径执行**（`rerunReview=true` 或 pending `kind=plan_action`）；legacy add_units
     保持原行为，不因新增后置条件而从“静默成功”变成 40905；
   - 请求新增 volunteerIds 全部在最终 working plan 和 ordered plan；
   - 执行前 working plan 的所有 volunteerIds 仍在最终 working/ordered plan（零删除；
     执行前已不存在的旧项不计）；
   - 最终 working/ordered 数量（按 countMode）= `targetCountOverride`；条目数与单元数分别
     记录，不用错口径；
   - 档位分布符合 override/预期；
   - 任一条不满足 → `40905 add_postcondition_failed`，抛异常整笔回滚，不返回 applied。
7. 审查（`rerunReview=true`）：
   - 语义 A：同事务；`runReview` 失败 → **必须抛出 `BusinessException(40907 review_failed)`**
     （或 `setRollbackOnly()` 后抛出），**不得 catch 后正常 return**——catch-return 会让
     `@Transactional` 提交已经加入的方案，出现“卡说未生效、方案已加入”的静默分叉；
     整笔回滚（含 add 与数量 override），卡片“未生效（审查失败）”；
   - 成功后 `getPlanningState` 重读，`result.planningState`、`resultPlanVersion` 均用重读值；
   - `reviewState.sourceVersion = N`（被审版本），`resultPlanVersion = N+1`；验收按此语义，
     不把 sourceVersion 改成最终版本。
8. **显式成功**：后置条件 + 审查通过后，`explicitStatus="applied"`，
   `postconditionReport.satisfied=true`，`actualChanges`（addedVolunteerIds/addedItems/
   addedCount/addedUnitCount/targetCountBefore/After/removedCount=0），
   `reviewState`（summary + top checks）一并返回；网关 `_status` 才能判 applied。
9. `compactResultForReplay` 保留 frozenCommand、actualChanges、postconditionReport、
   reviewState；replay 返回同一结果。
10. `PendingPlanningCommandRes` 增加 actualChanges/postconditionReport/reviewState；
    `RepairProposalTaxonomy` 增加 ADD_UNITS strategy/action type；`FixProposalDTO` 增加
    affectedItems/addedCount/removedCount/targetCountBefore/After。

### 4.3 网关 apply 早分支（P1-3 配套）

`_execute_claimed_command` 最前面、构造 proposalApply/canonical/region/major 解析之前：

```python
if command_type == "add_units":
    # 只传 commandType/pendingId/operationId/claimToken/expectedPlanVersion；
    # volunteerIds/targetCountOverride/rerunReview 由 Java 从 pending 读取。
    # internal_client 对 add_units 不要再拼 volunteerIds/rerun_review（当前会发 []），
    # Java validate 对 add_units 允许请求层 volunteerIds 为空/省略。
    response = await execute_pending_planning_command(
        ..., command_type="add_units", expected_plan_version=...,
    )
    # 直接走 status/回写/结果返回，不进入 proposalApply 分支
```

- 早分支必须独立返回/独立函数，不能只 `if` 后继续走 proposal 分支。
- 旧 `plan_mutation`（无 operationId）检测先于 `operation_id_missing`，明确
  “旧预览不支持，请重新生成”。
- 重复确认：不双写；已生效后 activeProposal 消失，返回 stale/已生效提示，不承诺同一结果。
- 网关仍传 expectedPlanVersion（来源 frozenCommand.sourceVersion）做版本守门。

### 4.4 回执链路

- `ConversationActionResult.as_dict` 增加 reviewState（当前只有 actualChanges）；
- `server._action_result_payload` 增加 actualChanges/reviewState（成功/失败两路）；
- 前端 `conversationEvents.mjs` 白名单、ProposalCard 类型/reducer/渲染同步；旧前端忽略新字段。
- 卡片：预览显示 addedCount/removedCount=0/targetCountBefore→After/affectedItems；确认后显示
  实际加入、后置条件结果、审查摘要；失败显示“未生效（审查失败/后置条件失败）”。

## 五、架构与长期演进

执行骨架固定为：

**结构化意图 → Java 编译并冻结变更预览（含数量/配额变化）→ 用户确认 → 执行冻结命令 →
后置条件校验 → 持久化回执。**

- 第一期 `goalType=add_units` 是**兼容入口**：复用 `ProposalRequest`/user-goal prepare 的
  幂等、单槽、operationId、确认链；语义上仍是一个精确动作，不是“用户目标”。
- 长期不要把 remove/move/replace 继续塞进 `goalType` 枚举；Java 内部应保留清晰的
  **动作命令类型**（add_units/remove_units/replace_units/move_unit/sort_order/pin_lock），
  每个命令有自己的 frozen command、预览 DTO、后置条件与回执：
  - `add_units`：零删除 + 全新增入；
  - `remove_units`：精确移除集合，其他不动；
  - `replace_units`：移出+加入成对冻结，旧项替换必须显式确认；
  - `move/sort/pin`：只改顺序/位置，集合不变；
  - 统一执行器校验 frozen digest + 后置条件 + 回执。
- `ProposalRequest` 继续承载“目标型”提案（fill/priority/scope）；精确动作走动作命令类型。
  第一期用 `goalType=add_units` 只是最小落地，后续迁移到动作命令时保留同一冻结/确认/执行
  骨架与卡片协议。

## 六、兼容、发布与回滚

- **无 DB migration**：pending / prepare 幂等表已存在；新增字段是 JSON/响应字段。
- **legacy pending**：新 pending `kind=plan_action`；legacy `plan_mutation`（无 operationId）
  在 codex 下明确拒绝；检测先于 operation_id_missing。row kind 与 dataValue kind 以 dataValue
  为准。
- **部署顺序**：Java（resolver/builder + frozenCommand + target override + 后置条件 +
  status/receipt + 40907/40908）→ agent（契约/schema/网关/prompt/技能）→ 前端（回执）。
- **开关**：`PLAN_ACTION_CONTRACT_ENABLED` 只拦 prepare；apply 始终保留，已存在的
  plan_action pending 可确认。关闭时 prepare 返回 plan_action_disabled。
- **legacy 回归**：无 rerunReview 的 add_units 不重校验、不跑 review、不应用 frozen 后置条件；
  版本只推进一次。
- **观测**：prepare/execute 一行结构化日志（requestId、pendingId、operationId、goalType、
  target 数、targetCountBefore/After、解析结果、后置条件、review、耗时、错误码）；
  不记录完整正文/画像。

## 七、测试与验收

### Python

- 契约/schema：name-only/ID-only/both/neither；names+ID 冲突；add 空 targets；非 add 带
  targets；add 带 target_count/requirements/priority/target_scopes；`exactTargets` required
  对所有 proposal；nullable 归一化；>20 拒绝。
- 版本守门：不符 → stale_state 可修复回合；专用提示；修复后成功。
- prepare 映射：`result.proposals[0]`；pendingId=null blocked/info 无按钮；duplicate/
  superseded/preparing；prepared 不透传。
- apply 早分支：不调用 proposalApply/canonical/region/major；只传 pending/operation/claim/
  expectedVersion；旧 plan_mutation 拒绝先于 operation_id_missing；重复确认。
- 请求校验：add_units 只带 5 个字段（commandType/pendingId/operationId/claimToken/
  expectedPlanVersion）→ 通过；请求带空 volunteerIds → 通过（Java 读 frozen）；
  带篡改 volunteerIds/rerunReview → 40908；该 40908 必须先于 replay 的 40903。
- 回执：actualChanges/reviewState/postconditionReport 成功/失败两路；as_dict/
  _action_result_payload/v1 事件/前端白名单；replay 保留。
- legacy：无 flag 的 add_units 不重校验、不跑 review。
- 安全：跨会话/跨租户 volunteerId；篡改 frozenCommand/volunteerIds/rerunReview →
  40908。

### Java

- resolver：prepare/execute 同池（effective, refresh=false）；unique/ambiguous/no_match/
  not_in_pool/target_mismatch/banned/locked/no_plan/source_unavailable；部分已选。
- 数量/配额：无目标自然增长；有总数且 current==confirmed → override=current+added
  （45→51）预览+执行；current!=confirmed（40 vs 45）→ prepare 阻断；
  unit mode 同组多专业 → override=currentUnitCount+addedUnitCount（6 条落 2 组只 +2）；
  entry mode 用条目数；有精确档位配额 → prepare 阻断；dry-run 删除既有项 → blocked；
  有选择目标但 dry-run 不可用 → 一律 blocked（不出 ready 后 40905 的卡）。
- frozenCommand：digest 稳定且含 operationId；执行只认 pending；请求只带 5 字段成功；
  请求带空 volunteerIds 成功；篡改 volunteerIds/commandType/targetCountOverride/
  rerunReview → 40908（先于 replay 40903）；replay 不换内容。
- add_units：select 前后 diff；generate 后置条件（全新增入、零删除、总数/档位）；
  失败 40905 回滚；**review 失败必须 40907 且事务回滚（回读方案确认没有加入，不能只断言
  状态码）**；成功后显式 applied + postconditionReport；reviewState.sourceVersion=N、
  resultPlanVersion=N+1；planningState 为 post-review；compact replay；
  **legacy add_units 不触发 40905/review/重校验，行为与基线一致**。
- 专业组：同组多专业；addedCount/addedUnitCount。
- taxonomy/FixProposalDTO 字段。

### 前端

- 预览卡：addedCount/removedCount=0/targetCountBefore→After/affectedItems；ready 才出按钮；
  blocked/info 无按钮。
- 确认后：实际加入、后置条件、审查摘要；失败“未生效（审查失败/后置条件失败）”。
- 冷加载/刷新去重；旧前端忽略新字段。

### E2E（真实栈）

- 六条点名 + 当前总数 45 → 预览“总数 45→51、不删除”；确认 → working/ordered +6、
  零删除、总数 51、review sourceVersion=N/result=N+1；卡片显示实际加入+审查摘要。
- 反例：有精确档位配额阻断；陈旧版本；重复确认；歧义；部分已选；候选失效；
  review 失败回滚；后置条件失败回滚；篡改 frozenCommand；开关关闭；旧 pending。
- 使用有真实候选文件的会话；避免 candidate_source_unavailable 假阴性。

## 八、风险与待审问题

1. **总数变化需用户明确确认**：override 用 **当前 working plan 实际数量 + 新增数量**（unit
   mode 用单元数）；若当前数与已确认目标不一致（40 vs 45），先阻断，不能静默用 45+新增。
   卡上必须显示 current→target；用户不接受时应改用替换（第一期不支持）。
2. **精确档位配额阻断**：第一期不做“加入+配额调整”组合；后续动作命令/替换动作处理。
3. **dry-run 必须可用**：有选择目标时 dry-run 不可用 → 一律阻断 add 预览，不出“ready 但
   可能 40905”的卡；需观测 prepare P95。
4. **请求层校验顺序**：add_units 只带 5 个字段；Java 必须允许请求层 volunteerIds 为空并
   先读 frozenCommand；内部 client 不得再拼 `volunteerIds: []`；篡改比较先于 replay 40903。
4. **review 语义 A**：审查失败回滚加入；40907 文案必须区分“加入失败”和“审查失败”。
5. **exactTargets 对所有 ProposalRequest 必填**：非 add 也要 `[]`；S1 同步全部 fixture/prompt。
6. **exactTargets vs targetScopes**：schema description + prompt + Java 拒绝混用。
7. **冻结命令与旧 pending**：旧 plan_mutation 无 operationId，必须明确拒绝。
8. **开关/prompt**：默认 on；回滚两步（flag + plugin/prompt 回退）。

## 九、实施拆分（最终确认后）

- **S1 契约/schema**：ProposalRequest add_units + ExactTarget + 条件 validator + strict schema +
  version guard repair + 全部 fixture/示例；不发布。
- **S2 Java resolver/预检**：effective candidates 包内方法、add_units builder、数量/配额预检、
  dry-run、frozenCommand/digest、FixProposalDTO 字段、prepare dataValue、prepareOnce 幂等测试。
- **S3 Java apply**：target override、select/generate、后置条件、显式 applied、review A/40907、
  40908 content binding、compact、taxonomy、测试。
- **S4 网关 wire**：早分支、prepare 结果提取、expectedPlanVersion、回执透传、
  旧 plan_mutation 拒绝、测试。
- **S5 卡片/前端**：预览/回执字段与渲染、旧前端兼容。
- **S6 prompt/技能/发布**：codex 四处 + plugin 重装 + 18291 重启；legacy 回归。
- **S7 验收**：真实栈六条 + 全部反例 + 回滚演练。

## 十、修订记录

| 审查项 | v4 处理 |
|---|---|
| 执行层：数量/配额冲突 | prepare 预检 + targetCountOverride 45→51 预览；精确档位配额阻断；dry-run 零删除；执行后置条件 40905 回滚 |
| 执行层：成功状态 | 后置条件+审查通过后显式 `applied` + postconditionReport；网关 _status 才判成功 |
| 执行层：确认内容绑定 | frozenCommand + commandDigest；Java 只认 pending；篡改 40908 |
| 执行层：review 版本 | reviewState.sourceVersion=N，resultPlanVersion=N+1；不改全局语义 |
| 执行层：target 契约 | v3 已修：names nullable + ID-only + both 交叉校验 target_mismatch；v4 保留 |
| v2 复审 B1'/B2'/B6' | v3 已修；v4 保留 effective candidates、result.proposals[]、exact_targets |
| M1/M6 legacy gate | rerunReview flag；重校验/后置条件仅新路径；legacy 不变 |
| 架构建议 | 固定“意图→冻结预览→确认→执行冻结命令→后置条件→回执”；goalType=add_units 为兼容入口，长期独立动作命令类型 |
| v3 终检：40907 事务 | review 失败必须抛 `BusinessException(40907)`（或 setRollbackOnly 后抛），禁止 catch-return；测试回读证明未提交 |
| v3 终检：40905 legacy gate | 后置条件/重校验仅 `rerunReview=true` 或 `kind=plan_action` 执行；legacy add_units 保持基线行为 |
| v3 终检：其余 | add_units 拒绝 negative_scopes/quality_guards/tradeoff_guards/source_review_issue_codes；no_plan/source_unavailable 判定来源写死；prompt 要求从 preview_candidates 复制准确名称 |
| v4 终检：请求校验冲突 | add_units 请求只发 5 字段；Java validate 允许请求层 volunteerIds 空/省略，先读 frozen；client 不再拼 []；篡改 40908 先于 replay 40903 |
| v4 终检：targetCountOverride | 用当前 working plan 实际数量 + 新增数量；unit mode 用单元数/addedUnitCount；current!=confirmed 阻断；不固定用已确认目标 + N 条目 |
| v4 终检：dry-run | 有选择目标但 dry-run 不可用 → 一律阻断 add 预览；无选择目标才可跳过 dry-run |
| v4 终检：frozenCommand | 纳入 operationId；请求/冻结分离；replay 不换内容 |
| 进度口径 | 616464c 只是 prompt/技能修正，不构成点名加入闭环；以本设计为准 |
