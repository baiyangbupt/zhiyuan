# Batch B3 真栈验收记录（2026-10-18）

环境：Java 18290（新 jar，13:35 起）、Agent 18291（真 codex，pid 随重启变化）、
MySQL `zhiyuan-codex-local-mysql-1`、Redis db9（TaskDraft）。验收会话：
900047（合成 e2e，备份/已恢复）、10041984（属 900002，planningState 与
userScoreDetail 已按测试前快照恢复，测试消息已清理）。

## 一、部署中发现并修复的阻断

1. **模型侧 schema 含无属性对象**：`IntentDraft.requirements/priorityRules` 原为
   `list[dict]`，生成 `{"type":"object","additionalProperties":true}`，DeepSeek
   `/responses` 直接拒绝（`An object with no properties is not allowed`），
   所有回合秒失败。修为具体模型 `DraftRequirement` / `DraftPriorityRule`
   （与 Java `RequirementDTO` / `PriorityRuleDTO` 同形），并加
   `test_turn_output_schema_has_no_propertyless_objects` 守卫。
2. **`sourceTurnId` 不可得**：模型侧 schema 必填，但当前回合号此前没有进上下文，
   模型只能编或省略草稿（实测连续多轮不产出 `intentDraft`）。修法：内部状态新增
   【本轮标识】块（`turnId` + "必须原样使用"），模型随后稳定产出 `intentDraft`。
3. **卡片看不到生命周期文案**：`_proposal_preview_payload` 白名单没有 `impact`，
   A2 的“确认后写入本会话并重新生成”到不了卡面。已加白名单 + `ProposalCard`
   渲染 `data-testid="proposal-impact"`，并补 payload 单测。

## 二、A2 卡面真栈读数

- 安徽只保留预览（900047）：`proposal.preview.diff.impact =
  "确认后这条范围要求会写入本会话的报考要求，并重新生成方案；还有 41 个专业组
  暂时没有合适补位，剩余部分需要放宽条件或后续再补。"`（ready 卡 ✓）
- 学费上限预览（10041984）：`impact = "确认前不会改动当前方案；确认后学费上限会
  写入本会话的报考要求，并按它重新生成、刷新方案。"`（ready 卡 ✓）
- 无命中 info 卡文案走 Java 单测（尚未在真栈构造无命中会话）。

## 三、B3 读数

### 3.1 复合草稿与阻断（900047）

- 请求：“再加六条安徽的院校，同时每年学费不超过两万；先整理要求”。
- 模型输出 `intentDraft`（`action=add_units`，`scopes=[region,tuition]`，`count=6`，
  `unresolved` 两项），`proposalRequest=null`，未先执行任何子动作。
- 用户答复后，系统正确识别“按范围加六条”不可由 `add_units`（只支持点名目标）
  执行，并因方案有 6 条失效条目**明确阻断**，给出 A/B/C 处理选项；
  未生成错误的全量 only_keep 卡。✓ “不可执行时明确阻断”。

### 3.2 点名加入 + 学费检查（10041984）

- 六条点名目标（均 ≤6000 元/年）→ `add_units` 预览 → 确认。
- `conversationAction.result`：`applied`，`addedCount=6`、`removedCount=0`、
  `targetCountBefore=45`、`targetCountAfter=51`、`addedUnitCount=6`；
  库内 `orderedPlanState.items` 111→117，零删除。✓
- 自动续接核实六条位置并写回消息。✓

### 3.3 学费约束（10041984）

- 预览：24 个专业组超 6000，ready；确认后 `applied`，版本 8→11。
- 自动续接**如实报告未达标**：51 组/117 条 → 36 组/71 条（少 15 组/46 条），
  并列出隐性收费与结构变化，给出 A–D 下一步。✓ “失败/部分成功如实转述”。

## 四、验收发现（P1，已修并复验，2026-10-18 下午）

`apply_constraint_and_regenerate` 的 postcondition 只看“方案中每条是否违反已确认
硬约束”，不看数量是否达到目标：

- `postconditionReport`：`actualCount=36`、`targetCount=45`、`satisfied=true`；
- `assistant_planning_pending_command.status=succeeded`；
- 网关回执 `actualChanges={}`（约束类没有数量增量/缺口字段）。

于是“执行成功”与“总数未保住”同时成立，只能靠自动续接再读方案才发现。
建议：按目标类型区分 postcondition——纯学费/替换类在 `actualCount < 目标` 时
不得 `satisfied=true`；回执补 `targetCountBefore/After`、`actualCount`、
`shortage`（only_keep 这类**允许**收缩的目标不套用数量判据）。

**修复与复验（克隆会话 900048，同一份 10041984 状态）：**

- `validateConstraintApply(..., countBefore, enforceCountPreserved)`：纯学费
  （无 `constraintUpdate`、有学费上下限）以**执行前规模**为数量下限；短缺即
  `40905` 回滚，`reasonCode=constraint_count_shortfall`。only_keep/exclude 不启用。
- 回执补 `countBefore/actualCount/shortage`；`PendingPlanningCommandRes` 带
  `targetCountBefore/After/shortage`；网关合成 `type=constraint` 的 `actualChanges`；
  `ProposalCard` 渲染“总数 before→after / 还差 N”；40905 卡面映射为中文兜底。
- 真栈复验：45 组方案、学费上限 6000 → 确认返回
  `failed / 40905 / constraint_count_shortfall (before=45 actual=30 shortage=15)`，
  `workspaceVersion=5`、`orderedPlanState` 45 组/111 条、`userScoreDetail` 均未变；
  自动续接用中文说明“只能排出 30 条、差 15 条、系统不会生成既不合预算又不够条数的
  方案”，并给出降总数/补候选/放宽上限三条路。✓
- 克隆会话测试后已删除；10041984 因用户连接中途接入，测试消息/预览已清理并恢复快照
  （后续不再使用该会话做脚本验收）。

## 四之二、新发现：模型动作名与 ChangeSet 过严

模型会输出自由动作名（`set_tuition_cap_and_preview`、
`replace_over_budget_keep_total`）并带 `additionalMutations=[replace,fill]`。
原实现把它们当未知动作 + 多个结构变更 → `needs_negotiation` → 带提案时被
`composite_request_requires_staged_preview` 整轮拒绝（用户只看到“引擎暂不可用”）。

修法（已落地）：

- `normalize_action`：`over_budget` / `tuition_cap` / `tuition_budget` /
  `tuition_limit` → `constrain`，并保留既有 goalType 别名。
- 纯约束（无 `targets`）的 `replace/fill/remove` 视为
  `apply_constraint_and_regenerate` 的执行机制，不再当第二个结构变更；
  带点名目标的约束仍走 `needs_constraints_first`。
- 新增 3 个 ChangeSet 单测；真栈复验：同一句“学费上限 6000”能正常出 ready 预览
  （修复前三次被整轮拒绝）。

仍待观察：模型若在 `unresolved` 非空时仍附带提案，仍会被 B1 守卫整轮拒绝
（守卫正确，但用户拿到的是“引擎暂不可用”而非可读的澄清话术）——后续可把该守卫
降级为“丢弃本轮提案 + 文本澄清”，而不是整轮失败。

## 五、A3 旧卡/重复确认真栈验收（已完成）

克隆会话 900049（同 10041984 状态，测试后已删除）：

1. 点名加入 → ready 预览 → 确认：`applied`，`addedCount=1`、45→46 组、
   111→112 条、零删除；operation 台账仅 1 条 `add_units/succeeded`。
2. 再次文字“确认”：模型识别“已经生效，不需要再确认”，未发起执行；
   方案仍 46 组/112 条，台账仍 1 条。✓
3. 模拟旧卡点击（`type=pendingConfirmation` + 旧 `proposalRef`）：服务端直接回
   `actionStatus=stale_state`、`code=proposal_reference_mismatch`，
   `actualChanges={}`，方案与台账均未再变。✓
   卡面文案映射为“这张确认已经失效…请用最新预览重新确认”。

## 六、守卫 UX 修正（同日）

模型在 `unresolved` 非空（把“候选名单工具不可用”也写进去）时仍附带 add 提案，
原守卫整轮抛 `composite_request_requires_staged_preview` → 用户只看到
“引擎暂不可用”，正文里的澄清说明丢失。

已改为：**丢弃附带草稿、保留正文**，并在正文末尾追加“本轮没有生成可确认的卡片”；
`unresolved` 的提示词口径也收紧为“只放用户意图本身的歧义，工具不可用不算”。
真栈复验：同一句点名加入在目标明确时能正常出卡；旧卡点击/重复确认均不双写。

## 七、未完成

- 严格“先约束预览→确认→再加入预览→确认”链未在单一复合请求里复现：
  模型把“点名六条 + 学费检查”拆成可执行动作；范围型加入被正确阻断。
  待 Batch D 的按动作规划器提供 add-scope 事务后再验。
