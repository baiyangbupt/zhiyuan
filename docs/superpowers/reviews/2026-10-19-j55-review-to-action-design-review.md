# J5.5 审查→动作设计评审（2026-10-19）

评审对象：`docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md`
评审方式：3 路独立只读评审（架构语义 / 执行契约 / 测试与清理），
对照 `zhiyuan-server` 与 `zhiyuan-agent` 实现，不修改代码。
首轮结论：**首版设计不通过；P0 已在本轮修订中收敛，需二次复审确认。**

最新结论（第三轮，见 §7）：**主架构认可，但不能沿用无条件 SIGN-OFF READY。
可先推进 J5.5a 的模型/纯计算部分；预览入口切换及 J5.5b/c 切流前，需关闭
下列分片依赖、求解粒度、修复可达性、确认协议与目标持久化问题。**

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

## 7. 第三轮复核：对话闭环与分片可执行性

- 日期：2026-10-19。
- 设计稿快照 SHA-256：
  `480bc61b9ca688ee449cc08707866bedbf8b0d7f998144fed4b8c4ef73913864`。
- 基线提交：`487e6ec`。本轮为单路静态复核，对照设计、既有评审、Java
  solver/快照/回放/评价与 Python 网关确认实现；未执行运行时测试。
- §6 的 SIGN-OFF READY 是上一轮历史结论；本节补充的前置条件尚未关闭，
  因而不能据此直接开放 b/c 的写路径。

### 7.1 P1：冻结回放分片仍缺前置能力

**依据**：设计 §9 的 J5.5b（818–828 行）开始接管 review apply，并要求
fill/安全/倒挂/组内真栈通过，但 `FindingPostconditionEvaluator` 到 J5.5c
（835 行）才交付。§4.4（414–426 行）又要求新执行链按原 probe 复算，
而不是依赖旧 checks/RepairReport 的通过标记。

此外，Legacy proposal 不等于完整的冻结后态：`FixProposalDTO` 当前的排序
载体是 `solverResult.orderedEntityIds`；旧 review builder 不填 solverResult，
`FixProposalDryRunResultDTO` 保存的是集合/计数，没有最终顺序。只把旧 proposal
存入 pending，不能自动满足 Direct reorder 的“原样回放最终顺序”。现有
`RepairProposalTaxonomy` 仍将 safety/ratio 标为 preview_only，也不能直接作为
b 的 executable 验收能力。

**建议**：把冻结后态物化和最小原 probe 后置校验移到 b 的前置/交付范围。
Legacy adapter 必须在预览阶段补齐最终 selected/ordered/专业级动作与事实
摘要；无法物化或验证的策略保持 preview_only，不能只为进入执行器而伪造
solverResult。b 的安全用例若仍依赖 c 的 Search，明确后移验收。

同一问题还影响 a：§9-a（815 行）删除旧 pending 生产，而新 review prepare
与 gateway 路由到 b 才接入。可以先交付纯读计算接口，但不要在 b 可用前
切换现有可确认卡片的生产入口，否则会出现“显示预览但无法确认”的中间版本。

### 7.2 P1：组内专业替换不能直接回退到 unit-level Search

**依据**：设计 §5.3/§5.4 与案例 G（511、524–526、703–709 行）把“无显式
专业配对”交给 Search forcedRemove/forcedAdd。当前
`CandidateSnapshotBuilder`（234–243、315–317 行）按 unitId 聚合一个 fact，
组内 volunteerIds 是同一 fact 的成员，不是独立的求解变量；
`StagedDeterministicPlanSolver`（132–149、427–445 行）只选择/删除整个实体，
且拒绝同一 entityId 同时 forcedRemove 和 forcedAdd。

**反例**：同组 u1 的 majorA→majorB。映射到 unit 后两边都是 u1；保留 unit
不会换专业，同时强制换出/换入 u1 会冲突。改换整个专业组则改变了用户授权
的动作范围。PlanCommand 示例也未给出可承载这类补丁的 forcedAddTargets。

**建议**：首批仅开放已物化的专业级配对回放；没有配对时明确保持 preview_only，
或单独设计组内 planner/组内选择模型，冻结专业级后态。不要把“转 Search”
视为现有 unit solver 已支持的能力。该决定应与 J5.3 §5 的 unit/volunteer
边界一起更新。

### 7.3 P1：solver ready 不等于修复目标已经可达

**依据**：设计案例 A（653–661 行）承诺补足 2 个本省保底，候选不足则 blocked；
但 §5.5.3/§5.5.4（591–610 行）未要求在产出可确认 proposal 前复算原 probe，
原 probe fail→pass 只写在 apply 后置（418 行）。J5.3 的 safety 是软目标；
当前 `StagedDeterministicPlanSolver`（170–194、385–398 行）允许最优
safetyDeficit 大于 0，仍返回 ready；objectiveResults 也不包含 safety 结果。

**反例**：44 个名额有足够普通候选，但本省保底最多 1 个。solver 可成功选满
44 个并返回 ready，实际安全缺口仍为 1。若按 solver status 出确认卡，用户
确认后才因原 probe 未通过而整笔回滚；这不是数量 candidate_shortage。

**建议**：对候选后态先做纯内存 preflight，复用同一 finding/probe evaluator；
只有修复目标满足且硬约束校验通过才 requiresConfirmation=true。不满足时
返回 blocked/preview_only 及可达缺口，例如 repair_goal_unreachable。新增
“solver ready 但目标 safety probe 仍 fail”的独立回归用例。

### 7.4 P1：两次用户确认与 active-pending 协议未闭合

**依据**：设计 §3.2（240–246 行）写成“预览→用户确认→prepare→再次确认→
claim/execute”，但 262 行又只允许确认当前 active proposal。§4.1 的只读
预览不创建 pending，第一次确认不能直接复用现有 confirm_proposal 通道。
当前 `conversation_actions.py`（156–162、180–192 行）要求 active ref、
pendingId/revision，缺失时会拒绝；网关 user-goal 则在展示可确认卡前 prepare
（`service.py:3020`）。

**建议**：显式区分“查看修复建议”“生成待确认动作”“执行确认”三种意图，
而不是把后两者都叫确认。推荐：只问审查时纯读；用户明确要求处理某 finding
时 prepare 并展示冻结卡；用户对卡一次确认后 claim/execute。若必须保留
两次确认，第一步需独立的 preview reference/动作类型，不能冒用 active pending
的确认协议。补“修复保底→冻结卡→确认→实际执行”的对话级验收。

### 7.5 P1：评价版本与执行失效范围需要分开定义

**依据**：设计 §3.3（279–282 行）把整池 candidateSourceVersion/dataVersion
纳入 evaluationVersion，并要求 prepare/apply 都校验 evaluationVersion；
§8.3（757 行）笼统要求候选/overlay 刷新触发 409。J5.3 §3.4 与当前
`FrozenSelectionGuard` 则明确：冻结之后只比较选择相关事实，未选候选刷新
不应使 pending 失效。

这不是已验证的运行时错误，而是两个可导向不同实现的 guard 契约：如果 apply
重算当前整池 evaluationVersion 并与冻结值相等比较，新增一个未选候选也会
误杀正常确认；若只比较请求与 pending 中的版本，则只是来源绑定，不表示
当前评价全局新鲜。

**建议**：preview→prepare 允许按当前评价重算并比较 previewDigest；prepare
之后，evaluationVersion 用于请求/pending 的来源绑定，真正失效依据是当前
计划内容、硬目标/动作契约及选择/显式动作涉及的硬事实，不重跑规划。分别测试
“未选候选刷新允许回放”和“选中/替换实体资格变化拒绝执行”。Direct 无
solverResult 时也应覆盖动作涉及实体，不能直接沿用现有 guard 的 early return。

### 7.6 P1：修复现有目标不等于永久改写用户目标

**依据**：设计 §5.3 把 ratio/safety 评价阈值编成绝对目标；§5.5.1
（550–558 行）又一律持久化为 confirmed tier goal 和优先于默认计算的 safety
字段。当前 `ReviewEvaluationMapper.mapTierRatio`（260–315 行）支持上下界
范围目标，而不是只有单点配额。

**反例**：用户原目标为“冲≤5、保≥2、总数10”，修复时选出的 3/5/2 是一个
可行后态，不代表用户把目标改成了精确 3/5/2。若把该向量写回 confirmed goal，
后续 refill 被无声收紧。类似地，把本次分数派生的保底阈值 2 持久化成最高
优先级显式值后，成绩/生源省/范围变化时是否失效，设计没有定义。

**建议**：区分命令的有效求解目标与真正授权的持久目标变更。修复既有范围时
保留原 bounds，必要时只用软 anchor 表达本次倾向；派生 safety 保留来源和
失效规则，不自动升级成永久用户硬目标。ObjectivePatch 只写明确授权的
durable change，并在卡面说明。补“范围修复后仍是范围”与“成绩更新后派生
safety 重新计算”的回归。

### 7.7 P1：普通 FILL 与可换项 REVIEW_FIX 的保留语义混用

**依据**：设计 §5.5.2（576–589 行）对 count fill 与 safety/ratio 都使用
FILL + lockExisting=false，只有 churn 抑制删除；案例 B 又预期 add=3、
remove=0。J5.3 §5（833–835 行）规定 FILL 中不在 removableEntityIds 的
合规存量项必须硬保留，不能交给 churn，因为 safety 层优先于 churn。

**影响**：数量补齐也获得了替换任意未锁定存量项的权限。遇到新增槽位不足以
同时改善 safety 并满足覆盖约束时，solver 可以通过额外换项获得更优 safety，
即使用户只要求补齐数量。反过来，safety/ratio 修复确实可能需要换项，不能
简单把所有行都改成 lockExisting=true。

**建议**：数量补齐保留 FILL 的硬保留规则；结构修复使用 REVIEW_FIX 或明确
的 removableEntityIds 授权范围，由 solver 在范围内选择最小改动。不要为了
允许结构修复换项而放宽所有 FILL。加入“count fill 不删合规旧项”和
“safety repair 允许最小必要替换”的成对测试。

### 7.8 其他口径与推进建议

- §3.1 的 `/review/run` 标为“读”（224 行），§3.3 又定义其 persist=true
  写 reviewState（267 行）。应区分“不改方案”和“零数据库写入”：只读实例
  使用内存评价端点，显式保存审查应标写并受服务端权限约束。
- §2.1 示意图仍让 user-goal 经过 PlanCommand，与 §0 明确的 b 期适配器范围
  不一致；更新图示，避免实现时提前合并两套编译。
- 本轮不要求推翻绝对命令、patch-after-enrich、冻结回放和 probe 后置这些
  已收敛方向；也不把尚未实现的 J5.5 能力当成现有代码缺陷。
- 建议顺序：a 先交付模型/typed delta/纯读计算；b 先具备冻结后态物化、
  preflight/后置 evaluator 和明确的单次执行确认协议，再原子切换卡片生产与
  确认链；c 按粒度/保留策略/目标来源逐项开放 Search；d 等兼容窗口结束后清理。
- 本轮仅修改评审记录；没有修改设计稿、业务代码或运行环境，没有执行测试、
  重启服务或提交。
