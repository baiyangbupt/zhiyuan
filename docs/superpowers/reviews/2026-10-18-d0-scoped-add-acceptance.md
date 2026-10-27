# Batch D 第一刀：按范围加入（add_units_by_scope）验收（2026-10-18）

## 目标

把“再加 N 条，限定地区/学费”从“当前契约不支持，先拆约束再点名”变成
**一个受支持的原子动作**：服务端从候选池确定性筛选、预览列明具体条目、
确认后走既有 add_units 执行链，零删除。

## 实现

- **Agent 契约**：`ProposalRequest.goal_type` 新增 `add_units_by_scope`，
  新增 `addCount`（>0）；允许 `targetScopes/negativeScopes/context/guards`，
  禁止 `exactTargets/targetCount/requirements/priority/tierQuota`。
- **ChangeSet**：`add_units_by_scope` 归一为 `add_by_scope`，直接 `ready/atomic`；
  模型把主动作写进 `additionalMutations=["add"]` 时忽略；只有其他额外结构变更
  才要求拆步。
- **网关守卫**：ready/atomic 草稿允许同轮 `proposalRequest`；`responseType`
  误标为 recommendation/review 且无 artifactRefs 时，预览回合降级为 text，
  不再整轮失败。
- **Java**：`UserGoalProposalBuilder.buildAddUnitsByScopeProposal`
  - 过滤：未选、未屏蔽、补偿安全、已确认硬约束合格、targetScopes 命中、
    negativeScopes 排除、min/max 学费；
  - 选择：group 模式按**专业组**去重取前 N 组（每组一条代表），major 模式取前 N 条；
  - 复用 `dryRunAddUnits`、`addExactAction`、目标数/回执字段；
  - 不足 N 条 → `add_units_by_scope_insufficient` 阻断，不拿别的学校凑数；
  - `prepareUserGoalProposal` 把该 goalType 与 `add_units` 同路冻结
    （pending kind=plan_action / actionFamily=add_units）。
- **提示词/技能**：按范围加入用 `add_units_by_scope`，明确“筛选只作用于本次新增，
  不改写整个方案”；任何 proposalRequest 预览用 `responseType=text`。

## 真栈读数（900058，10041984 状态克隆）

- 请求：“在当前方案基础上再加三条安徽的院校，学费不超过6000元；先看预览。”
- 预览：`strategy=add_units_by_scope`、`status=ready`；
  summary 列出 3 个专业组（安徽建筑大学法学、铜陵学院审计学、淮南师范学院会计学），
  学费均 ≤6000；“总数 45→48；不删除任何现有条目”；
  impact：“范围/学费条件只用于本次筛选，不会改写整个方案”。
- 确认：pending `applied`；planningState 45→48 组、111→114 条，零删除。
- 不足场景（单测）：只找到 1 条时返回
  `add_units_by_scope_insufficient`，提示放宽范围或点名补充。

## 测试

- Java：`UserGoalProposalBuilderTest` 新增 scoped add 成功/不足两例，整类通过。
- Agent：`test_intent_draft`（ready atomic / 缺数量澄清）、
  `test_turn_output_schema`（goalType/addCount/预览 responseType 降级）、
  `test_gateway_contracts` 全绿。
- Python 全量：2844 passed / 33 skipped。

## 未完成（Batch D 后续）

- replace/move/remove/fill 的按动作规划器与严格分步复合（先约束→再加入）
  仍未全部收口；本轮只打通“按范围加入”。
- group 模式下“每组只取一条代表”是 MVP 口径；若用户要求每组加入多个专业，
  需要下一刀扩展 addCount 的粒度（条 vs 组）。
- `objectiveDelta` 的 `CompiledActionDTO` 仍是 `executable=false`；审查修复
  走既有修复提案链，不直接执行。
