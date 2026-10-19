# J5.5b：prepare → pending → 冻结回放验收（概率倒挂 Direct 切片）

日期：2026-10-19。基线：`ccf2417`。本批仅本地代码与自动测试；未部署、未重启、
未开放生产默认开关。

## 交付边界

- 只打通**普通专业模式、probability_inversion → sort_by_probability** 这一条
  Direct 冻结链；其他策略仍走旧逻辑 / preview_only。
- 只读 `/session/fix-proposals/preview` 在开关打开时返回可确认的冻结 proposal
  （ready/requiresConfirmation=true）；开关关闭时保持 preview_only，行为不变。
- 新增 `/session/fix-proposals/review/prepare`：
  - 重新计算同一份审查与 proposal，校验 proposalId / previewDigest /
    commandDigest / evaluationVersion / sourceVersionGuard；
  - 冻结整份 proposal + FrozenReviewPlan（working/ordered/selected/factsDigest）
    + planContentDigest + 三个摘要；
  - 落 pending：kind=plan_change_proposal、
    actionFamily=apply_plan_change_proposal；
  - 同 requestId 重放返回同一 operationId，不生成第二份 pending。
- apply 只回放冻结内容：
  - 校验 pending 顶层摘要、当前 planContentDigest、选中事实 factsDigest；
  - 原样写回 working/ordered，不重排、不重新生成；
  - 写入前和写入后各按原 probe 复算一次；不满足抛 40905，事务回滚；
  - 直连 `/fix-proposals/apply` 且无冻结 pending → 409
    `review_fix_requires_pending`。
- Python 侧：
  - `preview_review_fix_proposals` 读取新只读预览；
  - 倒挂排序的预览改走新端点，不再创建本地 pending；
  - 用户一次确认时先 `prepare_review_fix_proposal`，再复用
    claim→execute→complete；
  - `_proposal_apply_payload` 透传 commandDigest/previewDigest/evaluationVersion。
- 灰度开关：`review.fix.command.enabled`（默认 false）。关闭时 prepare 拒绝，
  apply 保留旧“重新生成”路径作为回滚位。

## 验证

- Java：`mvn -o clean test` → **1356 tests / 0 failures / 0 errors / 10 skipped**。
- Python：`pytest -q tests/unit` → **2923 passed / 32 skipped**。
- 定向：
  - `DirectReviewPreviewPlannerTest`：开关开 → ready/requiresConfirmation/
    executable/frozen/previewDigest；开关关 → preview_only。
  - `PlanningStateServiceReviewFixPrepareTest`：冻结字段齐全、32 hex operationId、
    同 requestId 重放、digest 不匹配/版本漂移/开关关闭均 409。
  - `PlanningStateServiceReviewFixApplyTest`：冻结顺序逐字回放、篡改摘要 409、
    方案漂移 409、事实漂移 409、原 probe 后置失败回滚、无 pending 409。
  - Python：预览只读不建 pending、确认先 prepare 后执行、三摘要透传、
    历史压缩保留候选。
- 清理：删除已无引用的 `PlanSolver410AdrBenchmarkTest` 配套 fixture
  `release-4.1.0/plan-solver-adr-cases.json`，并从 4.1.0 baseline manifest 移除
  对应条目；`test_release_410_m0_contract.py` 恢复通过。

## 真栈验收（2026-10-19）

环境：Java 18290 以 `-Dreview.fix.command.enabled=true` 重启（新 jar）；
agent 18291 未改。fixture：900700（普通专业 major、80 条、无组/无锁/无优先规则），
先备份 planningState/userScoreDetail，再在夹具中构造：

- 2 条浙江条目改为保档（满足本省保底 2）；
- 候选比例设为 90/10，其余 100，形成可修复倒挂（修复后 10,90,100...）。

结果：

1. 只读 preview：`status=preview_only`（信封）、proposal `status=ready`、
   `requiresConfirmation=true`、frozenReviewPlan/factsDigest/previewDigest 齐全，
   preflight `satisfied=true`。
2. prepare：`prepared`，pendingId/operationId 正常；pending 顶层含
   proposalId/commandDigest/previewDigest/evaluationVersion/planContentDigest、
   frozenProposal/frozenReviewPlan/frozenRequestDigest。
3. claim：active→applying（claimToken）。
4. execute `apply_plan_change_proposal`：完成步骤
   `proposal_applied / ordered_plan_regenerated / review_rerun /
   postcondition_verified`，版本 1→2；最终 80 条、倒挂 0、本省保底 2；
   postcondition satisfied=true。
5. complete：applying→applied。
6. 恢复：planningState/userScoreDetail 回滚到原 HEX，版本 1、80 条、
   比例全 1.0、档位全冲；删除 pending/command/proposal-request 测试行。
7. 运行时已用**开关关闭**重启（pid 12344），健康 200；900040 5/80、
   900045 14/44 未受影响。

真实问题与修复：`assistant_conversation_proposal_request.result_json` 仍是
TEXT 量级，prepare 回填整份 preview 会 `Data too long`。现改为只回填轻量摘要
（proposalId/digests/status/summary），完整冻结负载只放 pending.dataValue；
真栈 prepare 已通过。后续如需在 request 表存完整结果，应单独迁移 MEDIUMTEXT。

## 首个 Search 切片：count_target → fill（2026-10-19）

- 新增 `SearchReviewPreviewPlanner`：普通 major 模式、`count_target` fail、
  `fill_missing_count`；复用 `UserGoalProposalBuilder.build` 的 staged solver，
  再通过 `applyFrozenSelection` 物化后态并跑原 probe 预检。
- `preview`/`prepare` 共享 helper：先 Direct（倒挂），再 Search（count_target）；
  apply 接受 Direct 倒挂 + fill(count_target/count_validation_hard)。
- 目标数量：本切片要求 `selectionTargetCount` 已存在且为目标值；apply 只回放
  冻结方案，不修改目标/档位/覆盖。`persistTargetCount=true` 仅用于让
  user-goal builder 产出 80→82 的补齐动作，review 冻结链本身不落目标。
- 真栈 900700 夹具：required/selectionTarget=82、2 条浙江保档、当前 80 条；
  preview `ready`、`selected=82/add=2/remove=0`、preflight satisfied；
  prepare→claim→execute 后版本 1→2、82 条、保底 2、postcondition true；
  已恢复 planningState/userScoreDetail 到原 HEX（v1/80/全冲），清
  pending/command/proposal-request 测试行。
- Java 全量 **1368 / 0 / 0 / 10**；Python unit **2925 passed / 32 skipped**。

## 第二个 Search 切片：coverage → fill（2026-10-19）

- `SearchReviewPreviewPlanner` 增加 coverage 模式：finding `coverage:<i>` fail、
  command `must_include_scope`/apply fill；把 command.coverageRequirements 转成
  `RequirementDTO{kind:include}` 交给同一个 `UserGoalProposalBuilder` staged solver。
- 允许 target == current（等量替换）；空 coverage 集 fail closed
  `review_fix_coverage_unavailable`。
- apply 接受 `fill_missing_count + coverage:*`，仍只回放冻结方案；coverage
  要求必须已在 state 中确认，冻结链不写 durable patch。
- 真栈 900700 夹具：required=80、当前 80、浙江覆盖 min=16、2 条浙江保档；
  候选池仅 16 个浙江（选中 15 + 可换 1）。preview `ready`、
  `selected=80/add=1/remove=1`、preflight coverage pass；prepare→claim→execute
  后版本 1→2、80 条、浙江 16、保底 2、postcondition true；已恢复 v1/80，
  清 pending/command/proposal-request 测试行。
- Java 全量 **1375 / 0 / 0 / 10**；Python unit 定向 297 passed / 32 skipped。

## 第三个 Search 切片：safety_guard → fill（2026-10-19）

- 新增 `SafetyReviewPreviewPlanner`：`safety_guard` fail → `add_safety_items`，
  在 enrichV2 后直接 patch `StructureTarget.minLocalProtect`，走 staged solver
  的 safety 阶段；物化后态、原 probe 预检、冻结回放与 Search 切片同构。
- 普通 major 模式；不可冻结路径返回 null（不把旧预览变成 blocked 占位）。
- apply 接受 `fill_missing_count + safety_guard`，只回放冻结方案；保底由
  state 派生，不写 durable 字段。
- 真栈 900700 夹具：required=80、当前 80、1 条已选浙江保档 + 1 条可换浙江保档，
  安全下限 2（实际 1）。preview `ready`、`selected=80/add=1/remove=1`、
  safety preflight pass；prepare→claim→execute 后版本 1→2、80 条、保底 2、
  postcondition true；已恢复 v1/80。
- Java 全量 **1388 / 0 / 0 / 10**；Python 定向 299 passed / 32 skipped。

## 第四个 Search 切片：ratio_distribution → fill（2026-10-19）

- 新增 `RatioReviewPreviewPlanner`：`ratio_distribution` fail → `rebalance_tier_ratio`，
  在 enrichV2 后 patch `tierAllocationConstraint` 与 `StructureTarget.tierAnchor`
  （由 `TierStructureProjection.project` 按当前档位计数与目标数计算），再走
  staged solver 的硬档位约束/soft anchor 阶段。
- 真栈 900700 夹具：required=80、tierQuotaGoal exact 40/20/20、当前 79 冲 +
  1 保、可用候选 20 稳 + 20 保（其中 1 条浙江保档）；安全下限 2。
  preview 同时产出 safety 与 ratio 两条 ready 提案；选择 ratio：
  `selected=80`、`resolvedTierCounts=40/20/20`、postcondition ratio pass；
  prepare→claim→execute 后版本 1→2、档位 40/20/20、保底 2、
  postcondition true；已恢复 v1/80。
- apply 接受 `fill_missing_count + ratio_distribution`，只回放冻结方案；
  档位目标已在 state 确认，不写 durable patch。
- Java 全量 **1400 / 0 / 0 / 10**；Python unit **2931 passed / 32 skipped**。

## 第五个 Search 切片：风险条目替换/移除（2026-10-19）

- 新增 `RiskReplaceReviewPreviewPlanner`：high_tuition / cooperative_program /
  admission_limit / special_enrollment → `replace_risk_items`/`remove_risk_items`；
  把 forcedRemoveTargets 写进 `MutationPolicy.forcedRemoveEntityIds`，用 staged
  solver 选替代条目；targetCount 缺省时按当前条目数保持数量。
- 物化后态、原 finding probe 预检、冻结回放与其余 Search 切片同构；
  额外确认所有 forced 目标已不在最终方案。
- apply 接受 `fill_missing_count + 上述四类 finding`，只回放冻结方案；不写
  durable patch。
- 真栈 900700 夹具：required=80、2 条浙江保档、1 条已选高收费（25000）；
  preview `ready`、`selected=80/add=1/remove=1`、high_tuition preflight pass；
  prepare→claim→execute 后版本 1→2、80 条、无高收费、保底 2、
  postcondition true；已恢复 v1/80。
- Java 全量 **1415 / 0 / 0 / 10**；Python unit **2933 passed / 32 skipped**。

## 专业组模式：Direct 概率倒挂（2026-10-19）

- `DirectReviewPreviewPlanner` 增加 unit 模式：按 ordered units 的
  `admissionRatio`（缺省 schoolEnrollRatio）排序，授权 reorderTargets 的
  unit 可动、其余 pinned；用 `applyFrozenOrdering(..., unitMode=true)`
  物化 units+items；冻结 unit facts 摘要；apply 端按 unit facts 校验并原样回放。
- 兼容线上稀疏位置：unit position 只要求严格递增且唯一，回放时统一重排 1..n。
- 工作台可能只存 draft items、无 working units：unit 模式下以 ordered units
  作为当前选中集。
- 真栈 900045 夹具：44 组、unit1/2 比例 90/10、其余 100、2 条江西保档；
  preview `ready`、`selected=44`、inversion preflight pass；
  prepare→claim→execute 后版本 14→15、44 组、倒挂 0、保底 2、
  postcondition true；已恢复 v14/44。
- Java 全量 **1427 / 0 / 0 / 10**；Python unit **2933 passed / 32 skipped**。

## 专业组模式：count_target → fill（2026-10-19）

- `SearchReviewPreviewPlanner` 增加 unit 分支：targetCount 按**单元**计；
  复用 `UserGoalProposalBuilder` 的 group 模式 fill，物化 working items+
  ordered units/items，unit facts 摘要与冻结回放。
- apply 接受 fill_missing_count + count_target 的 unit 冻结方案。
- 真栈 900045 夹具：required/selectionTarget=46、当前 44 组、2 条江西保档；
  preview `ready`、`selected=46/add=2`；prepare→claim→execute 后版本
  14→15、46 组/166 条、保底 2、postcondition true；已恢复 v14/44。
- Java 全量 **1434 / 0 / 0 / 10**；Python unit **2933 passed / 32 skipped**。

仍未覆盖：gap/edge 等 Search probe；Safety/Ratio/Risk 的专业组模式；
目标/档位/覆盖的 durable patch 持久化。

## 尚未完成

- 其余 Direct 策略（remove/replace/group-inner）与 Search planner 尚未接入。
- 专业组模式、pin/lock、已确认优先规则仍拒绝冻结。
- 已做一条真栈 prepare→claim→execute→complete 验收；仅 900700 夹具，
  不代表其他策略/会话已验收。
- 旧 generate/apply 分支仍保留，供灰度回滚；J5.5d 再删。
- 生产默认开关仍关闭（验收后已重启为关闭）。

## 下一批门禁

1. 在真栈打开 `review.fix.command.enabled`，用 900040/900045 做一条倒挂修复
   prepare→claim→execute→postcondition，并恢复快照。
2. 再决定是否扩展 Direct remove/replace；Search 按 J5.5c 单独开。
3. 在真栈验收前不得宣称 J5.5b 全闭环或已上线。
