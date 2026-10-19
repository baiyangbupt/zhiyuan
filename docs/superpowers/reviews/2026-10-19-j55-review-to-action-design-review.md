# J5.5 审查→动作设计评审（2026-10-19）

评审对象：`docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md`
评审方式：3 路独立只读评审（架构语义 / 执行契约 / 测试与清理），
对照 `zhiyuan-server` 与 `zhiyuan-agent` 实现，不修改代码。
结论：**首版设计不通过；P0 已在本轮修订中收敛，需二次复审确认。**

---

## 1. P0（必须在落地前解决）

| # | 问题 | 证据 | 处置 |
|---|---|---|---|
| P0-1 | delta 语义自相矛盾：`targetCountDelta` 既被当“新增条数”又被当“目标变化”，42/45 与 safety 2/0 两案例算错 | `PlanningObjectiveCompiler:124-129`；Case A/B | **改为绝对目标**：`targetCount`/`tierTargetCounts`/`safetyMinLocalProtect`/coverage 集合；delta 只做展示 |
| P0-2 | 先 patch 后 `enrichV2`，safety/tier 补丁被 state 重算覆盖；solver 优先读 `structureTarget.tierAnchor` | `PlanningObjectiveCompiler:93-101`；`StagedDeterministicPlanSolver:840-846` | `enrichV2` 后应用绝对补丁，重算 anchor/resolution 并重冻 digest；单测断言 solver 输入 |
| P0-3 | Direct 的 replace/remove 仍由 `RepairRiskActionBuilder`/`RepairCandidateSelector` 选候选，形成第二套选择链 | `RepairRiskActionBuilder:86-90`；`PlanningStateService:12592-12641` | Direct 只做**全显式动作**（sort、组内调整、已给出 replacement pairs）；remove/replace 需要候选时走 Search + `forcedRemoveIds`/`replacementPairs` |
| P0-4 | 首批 executable 的 `add_safety_items`/`rebalance_tier_ratio` 在 taxonomy 是 PREVIEW_ONLY，apply 无分支；review FILL 冻结分支只对 user_goal 生效 | `RepairProposalTaxonomy:101-115`；`PlanningStateService:1613-1640` | 新增统一 `FrozenPlanExecutor`：任何带 frozen solverResult 的 proposal 都走 `applyFrozenSelection/Ordering`；Search 对 apply 层归一为 `fill_missing_count`，原策略放 `sourceStrategy` |
| P0-5 | 用户目标仍走 `UserGoalProposalBuilder` 独立编译，不是同一 PlanCommand/planner | `UserGoalProposalBuilder:89` | 明确范围：J5.5b 先统一 **proposal/freeze/apply**；用户目标保留 `UserGoalPlanner` 适配器实现同一 `PlanProposalPlanner` 接口；J5.5d 再评估是否合并编译 |
| P0-6 | review apply 实际不冻结：`applyFixProposal` 重新生成；`assertRequestMatchesFrozen` 对 apply 直接返回；canonical 校验只对 user_goal | `PlanningStateService:1139`；`PendingPlanningCommandBizService:502-504`；`RepairProposalApplyPolicy:66-87` | review 走 frozen replay；apply 请求必须带 `proposalId/commandDigest/previewDigest`，与 pending 比对；canonical 校验对所有带 solverResult 的 proposal 生效 |
| P0-7 | 版本 off-by-one：runReview 记录 `sourceVersion=v` 后把 state version +1；用整数 sourceVersion 做 apply guard 必 409 | `PlanningStateService:3301,3337`；现网 900045 v14/review13 | guard 改为 `evaluationVersion + planContentDigest`；`expectedPlanVersion` 用 prepare 时的当前版本；review-only 写不触发计划内容 stale |
| P0-8 | Search 补丁不持久化：apply 后 target/tier/coverage/safety 只在本次 solver 生效，后续 refill/review 回退 | 无 `applyUserGoalTargetToPlanningState` 等价物 | pending 冻结 `ObjectivePatch`；apply 同事务写约束/目标/档位/覆盖；postcondition 读写入后的 state |
| P0-9 | 预览非只读：`generateFixProposals` 懒执行 `runReview` 并保存、version+1；review 工具还会创建 legacy pending | `PlanningStateService:858-865,3277-3291,3337`；`tools.py:9558` | 预览改为纯内存评价（`persist=false`），禁止 pending；prepare 才冻结。补 `codex_readonly` 端点级拒绝测试 |

---

## 2. P1（同批判定，允许分片修）

| # | 问题 | 处置 |
|---|---|---|
| P1-1 | 预览→prepare 只绑定 proposalId/commandDigest，不绑定 selected/ordered/actions；overlay 刷新不标 stale | 预览返回 `previewDigest`（evaluationVersion + planContentDigest + proposal 内容 + solver selected/ordered/actions）；prepare/apply 校验 |
| P1-2 | “apply 只回放”不成立：sort 重排、ordered plan 强制重生成、rerunReview 再 bump | FrozenPlanExecutor 回放 selected/ordered；禁止对冻结 proposal 重新生成 ordered；review 重跑只在 apply 事务后按显式开关 |
| P1-3 | review apply 跳过 canonical/frozen 校验；直连 `/fix-proposals/apply` 是第二入口 | 统一走 pending command；直连端点降级/标记 legacy；所有 solver proposal 走 canonicalMetadataMatches |
| P1-4 | 后置条件仍信旧 checks；coverage 无 check 时真空通过；Direct 无后置 | 新增 `FindingPostconditionEvaluator`：按 finding code/probe 复算；Search 校验 frozen objectiveResults；Direct 校验原 probe fail→pass；无评价输入 fail-closed |
| P1-5 | delta 映射用 strategy 名称泛化，safety/ratio/coverage 的 targets 语义错；unknown/missing input 也挂 delta | 逐 probe typed builder；`needs_input`/unknown 不产 delta/command；coverage 按 identity 合并（max/去重） |
| P1-6 | 确定性未定义：未含 candidateSourceVersion/dataVersion/overlay；map 顺序、target 排序、proposalId 公式未定 | 固定 canonical JSON：key 排序、target 按 level+id 排序；digest 含 evaluationVersion+candidate/data version；proposalId 含 commandDigest/previewDigest |
| P1-7 | Python 触发缺失：ProposalRequest source 只有 user_goal；gateway 只 prepare user-goal；review 工具写 legacy pending 无 operationId | 新增 `prepare_review_fix_proposal`；`ProposalRequest` 增加 review_check source；tools/gateway 确认链改 prepare→claim→execute；readonly 层拒绝 prepare |
| P1-8 | ObjectiveDelta/Command 字段缺 safety/coverage/level/digest；`sourceReviewVersion` 无来源 | DTO 增字段；`PlanCommandDTO.level`（unit/item）；`sourceReviewVersion` 改为 `evaluationVersion`（已有字段） |
| P1-9 | 测试矩阵缺自动 apply 不调 planner、evaluation unavailable→checks fallback、旧 pending、user-goal 回归、候选刷新、并发 claim/replay、重叠 proposal、409 e2e | 全部补入 §8；现有 ratio preview_only 断言随策略迁移更新 |
| P1-10 | 真栈会话不满足案例：900045 全冲、无 selectionTargetCount/tierConstraint、safety 2/0、倒挂 pass；备份不完整 | 用 900058/10041984 克隆或临时约束 fixture；全行备份 extra_data/pending/command/request；唯一 requestId；恢复 `UNHEX USING utf8mb4` |
| P1-11 | 清理清单误删：candidateShortages 被 Web/agent 读；targetCountAfter 进 FrozenSelectionDigest；RepairDryRunSimulator 仍供 Direct dry-run；checks 未退场 | 保留 candidateShortages/targetCountAfter；Direct 先产出 dryRunResult 再删 simulator；checks fallback 保留到 J5.5d |
| P1-12 | 分片/回滚矛盾：J5.5b 需要 planner 但 c 才建；b 删重新生成而回滚依赖；flag 未实现 | b 先接 Legacy adapter + 保留旧分支（双开关 `review.fix.command.enabled`、`review.fix.search.enabled`）；c 稳定后 d 删 |
| P1-13 | 案例 C/D/G/H 不具体：候选可用性、replacement pairs、tier 总和/上下界、后置预期、只读层未写 | 每案例补 fixture、输入/输出 JSON、expected actions/selected/postcondition |
| P1-14 | 删除 4 参 buildBaseProposal/PlanPreviewCalculator 的测试影响未验证 | 已执行：全量 clean test 1268/0/0/9；保留记录 |
| P1-15 | 执行异常时 command 行回滚、claim 过期可被重领，缺失败码 | 定义 `review_fix_stale/changed/frozen_required` 等码；失败留 failed 行审计；claim 过期重领需新 token 且通知 |

---

## 3. 已确认保留/不删

- `candidateShortages`、`addedCount/removedCount`（Web/agent 读）。
- `targetCountAfter`（FrozenSelectionDigest）。
- `RepairDryRunSimulator`、`RepairProposalStateBuilder` 旧 check 路径：J5.5b 期间作为 Legacy adapter；J5.5d 前不删。
- checks 字段：旧会话只读回退；删除按 J5.2 三段式。
- `PlanPreviewCalculator`（无生产调用）与 4 参 `buildBaseProposal`（仅测试）已删除/折叠，全量 clean test 通过。

---

## 4. 复审前必须完成的修订

1. §2/§5 改为**绝对目标**模型（targetCount/tierTargetCounts/safetyMinLocalProtect/coverage set）。
2. §5.4.1 改为“enrichV2 后打补丁，重算 anchor，重冻 digest”。
3. §5.3 Direct 规则收紧：仅全显式动作；remove/replace 走 Search。
4. 增加 `FrozenPlanExecutor`，Search 统一归一为 fill apply，原策略进 `sourceStrategy`。
5. §4.2/4.3 补 `previewDigest`、evaluationVersion、planContentDigest；版本 off-by-one 明确。
6. §4.3 明确 review apply 只读 frozenProposal，禁止重新生成；canonical 校验对所有 solver proposal 生效。
7. §5.5 逐 probe typed delta/command；unknown/needs_input 不给修复。
8. §8 补 P1-9 测试；§7 案例 A/B/D 改为可复现数字，C/G/H 补 expected。
9. §6 清理清单按 P1-11 修正；§9/§10 双开关与保留旧分支。
10. Python/agent 触发与契约写入 §3/§4。

---

## 5. 首轮评审结论

- 首版设计方向正确（评价/命令/冻结回放统一），但 **P0 语义与执行可行性不足**，不能直接落地。
- 修订版需再次做架构/执行两路复审；复审通过后从 J5.5a（纯命令模型+delta，不改执行）开始。

---

## 6. 二次复审（修订版）

复审对象：修订版设计（绝对目标、patch after enrich、FrozenPlanExecutor、
previewDigest、typed delta）。两路复审结论：**仍未 ready**，但只剩 1 个 P0
（架构）与 4 个执行 P0，均为局部修订，不需要推翻框架。

### 6.1 架构复审

| # | 问题 | 处置 |
|---|---|---|
| P0 | `applyStrategy` 归一与 `FixProposalDTO.strategy` 保留原语义冲突；safety/ratio 仍被 taxonomy/apply 拒绝 | 已改为 **proposal.strategy=applyStrategy**（fill），`sourceStrategy` 只做审计；apply 按 solverResult 分派 |
| P1-1 | policy 表与 Case A 矛盾（safety/ratio lockExisting=true 不可行） | 已改为按 sourceStrategy 配置；safety/ratio `lockExisting=false + forcedRemove` |
| P1-2 | `count_missing` 误判 needs_input | 已改：空 reason+passed/warn=缺官方数→needs_input；count_missing=低于官方→fill |
| P1-3 | group-inner Direct 仍自己挑专业 | 已改：必须显式 replacementPairs；否则 Search forcedRemove/Add |
| P1-4 | pending/apply 比对依赖不存在的 frozenCommand；直连 apply 第二入口 | 已改：顶层 proposalId/commandDigest/previewDigest/evaluationVersion 比对；直连 review apply 409 |
| P1-5 | proposalId/previewDigest 循环 | 已改：proposalId 不含 previewDigest；previewDigest 含 proposalId |
| P1-6 | 回滚依赖旧分支，但 J5.5b 又删 | 已改：旧分支保留到 J5.5d；失败状态 REQUIRES_NEW |
| P1-7 | user-goal 统一措辞过强 | 已改：J5.5b 只统一 proposal/freeze/apply；J5.5d 再议编译合并 |

### 6.2 执行复审

| # | 问题 | 处置 |
|---|---|---|
| P0-1 | digest 循环；canonical digest 与 compileConfirmed 口径不一致 | 已改：proposalId/previewDigest 公式分离；canonical 存 enrich 前，solverObjective 存 patch 后 |
| P0-2 | patch 持久化不可行（HardPlanningObjectives 无 safety、coverage 不能删） | 已补：DTO/ SafetyFloorSupport / CoverageRequirementSupport 的持久与移除设计 |
| P0-3 | review-only bump 导致 expectedPlanVersion/sourceVersionGuard 409 | 已改：review 写不推进 plan version；用 evaluationVersion+planContentDigest |
| P0-4 | apply 要求 regenerate/rerun=true，与 frozen 回放冲突 | 已改：true 语义=按冻结顺序同步；rerun 在提交后；不再 force regenerate |
| P1-1 | 预览 resolveEffectiveCandidates 会写 overlay | 已改：in-memory refresh；stale 则 409，不写 |
| P1-2 | Java 无 readonly 机制 | 已补：header `X-Assistant-Mode` + `planning.write.enabled`，Java 端点拒绝 |

### 6.3 复审后状态

- 上述 P0/P1 已回填设计 §2–§6、§9、§10；剩余为产品/数据侧确认（coverage
  identity、组内展示粒度、fixture 会话），已在设计 §11.1 列出。
- 终审只发现一处文字矛盾：`mutationPolicy` 的 key 应为 `sourceStrategy`，
  已修正；其余项均通过。
- **最终结论：SIGN-OFF READY**（执行复审明确通过；架构复审确认无 P0，
  P1 修正后关闭）。
- 建议下一步：只做 J5.5a（命令模型 + typed delta + 纯读预览），
  **不改 apply**；b/c 在 a 的测试与 review 通过后启动。
