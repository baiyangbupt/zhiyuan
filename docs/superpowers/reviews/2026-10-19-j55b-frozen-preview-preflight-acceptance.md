# J5.5b 前置：冻结预览与原问题预检

日期：2026-10-19。基线：`487e6ec`。本批仅本地代码与自动测试；不部署、不重启、不提交。

## 当前交付

- 新增共享 `FindingPostconditionEvaluator`：只消费重新计算的审查结果，要求原 finding
  为 pass、所有 hard probe 与已确认 count/coverage/显式配额满足；缺评价版本、未知原问题、
  缺硬证据、probe 数量不符或重复 probe 均拒绝。不能用 solver ready 代替修复达成。
- 只读 `/session/fix-proposals/preview` 在普通专业模式下增加显式作用域的概率排序。
  先物化内存后态，再跑同一审查流程；通过后冻结完整 workingPlan、orderedPlan、
  selectedEntityIds、orderedEntityIds、选中事实与 factsDigest。
- proposal 补充 findingCode、evaluationVersion、commandDigest、planContentDigest、
  canonicalObjectiveDigest、previewDigest 与 preflight 结果；摘要绑定真实冻结后态、
  actions、dry-run，不伪造 solverResult，不在预览创建 pending 或推进版本。
- 新排序引擎按录取率稳定升序，只移动 command.reorderTargets 授权的槽位。
  若作用域内排序仍无法消除全方案倒挂，则返回 repair_goal_unreachable，无冻结后态。
- 所有新 proposal 保持 preview_only、requiresConfirmation=false；typed command
  仍 executable=false。冻结预览不是可确认卡，不构成新执行入口。

## Golden 根因与修复

1. 原 Golden 手工构造的 context 丢失 J5.4 输入；替换为生产 EvaluationContextBuilder，
   legacy 翻译项继续严格对比历史状态，派生项独立核对事实、阈值、严重度、affected refs。
   同时校验原始 state 到 context 的事实投影，不只验证 mapper 与自身输入一致。
2. 完整输入首次暴露五份快照的合作办学 false-pass：六个仍被选中的专业名包含“中外合作”，
   分布在四个专业组，但组级投影丢失成员名称且无风险标签，导致 derivedEntryMatches=0。
   这不是合理历史差异，也不是风险已解决；已在候选风险投影中从名称补 canonical
   cooperative_program 标记，保持其他风险谓词不变，不写回原候选。
3. 评价模型升级至 objective-compiler-v3，避免旧结论复用同一模型版本。
   修复后上述快照恢复 fail，命中四个专业组；历史选中专业与组级粒度的差异仍显式报告。
4. 十份快照只有八份包含 review；900016、900047 显式跳过。
   无 review 的两份不算验收通过；不能宣称十份业务对照全部通过。

## 审查补强

- 独立审查复现 ID-only 硬约束缺身份字段时旧 eligibility 回退空名称约束、误放行的问题。
  新预览在可确认资格之前检查硬事实完整性；缺专业 ID（包括 0）、区域身份/名称、专业分类
  字段时拒绝冻结，不修改共享旧 eligibility 语义。
- 初期保守拒绝专业组、pin/lock、已确认优先排序，以及尚不能可靠验证的学校分类硬约束。
  可解释但不可冻结；以后补完对应事实与校验后再逐项开放。
- 独立审查还要求 Golden 不信任丢失的 coverage 或被篡改的 safety floor，必须回到源 state
  核对目标投影；两个 mutation regressions 均 RED→GREEN。独立复审确认两项 P2 均关闭，
  本范围内未发现新的 P0/P1/P2；这不等于尚未实现的确认/执行链已被审查通过。

## 尚未切换

- PlanProposalPlanner/LegacyReviewAdapter 的统一接口与全策略适配。
- review prepare、pending 冻结保存、FrozenPlanExecutor、apply 的原 probe 复算与 scoped hard-fact guard。
- Python tools/gateway 的一次确认链与开关。
- fill/count 的冻结执行、显式专业配对、专业组排序/替换；Search/safety/ratio/coverage planner。
- 旧 generate/prepare/apply/Python 路由继续原逻辑，未删除回滚分支。

本批不宣称 J5.5b 完整闭环或真栈验收完成。下一批应接 prepare → pending → 冻结回放 →
同一原 probe evaluator → gateway，具备完整守卫后才开放确认。

## 定向验证证据

- 原 probe/排序/预览边界：`/tmp/j55b-evidence-green.log`，33 项零失败。
- 合作办学根因 RED：`/tmp/j55b-cooperation-red.log`；修复后 builder/version/harness
  30 项零失败：`/tmp/j55b-cooperation-green.log`。
- ID-only 硬事实问题 RED：`/tmp/j55b-review-hardfacts-red.log`；修复后 planner/controller
  21 项零失败：`/tmp/j55b-review-hardfacts-green.log`。独立复审确认原复现拒绝冻结。
- 合作办学修复后 Golden：`/tmp/j55b-golden-repaired.log` 与
  `/tmp/j55b-golden-repaired.report`，22 项零失败；8 份快照可评价、2 份无 review 跳过，
  historicalDifference=true 计数为 0。该结果不替代最终源目标投影补强后的复跑。
- Golden 源目标投影补强：`/tmp/j55b-golden-context-red.log` 复现两条篡改漏检；
  `/tmp/j55b-golden-context-green.log` 的 22 项普通回归通过。

## 最终验证

- `cd zhiyuan-server && mvn -o clean test`：**1341 项，0 failures、0 errors、10 skipped**。
  日志 `/tmp/j55b-full-test-final-verified.log`；默认跳过的可选快照测试不计作快照已覆盖。
- 显式设置 EVALUATION_GOLDEN_FILES，执行 EvaluationGoldenHarnessTest、
  EvaluationGoldenShadowTest、ReviewCommandGoldenTest：**24 项，0 failures、0 errors、0 skipped**。
  日志 `/tmp/j55b-golden-final-verified.log`；报告 `/tmp/j55b-golden-final-verified.report`。
  两套快照均 **8 evaluated / 2 显式文件级跳过 / 0 failed**，历史状态差异计数为 0。
  JUnit 的 0 skipped 与文件级两份不具备 review 的跳过是不同口径，不混用。
- `git diff --check` 通过；未修改无关前端工作，未提交、未部署、未重启环境。
