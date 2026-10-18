# J5.3 Solver 设计评审（独立四视角）

- 日期：2026-10-18
- 对象：`docs/superpowers/specs/2026-10-18-j53-solver-design.md`
- 方法：四路独立评审，各自读设计 + 代码；不共享结论。视角分别为
  算法/MILP、产品语义/契约、迁移/测试/运维、红队反例。
- 结论：**设计方向成立，但不能按初稿直接实现**。首轮识别 8 个 P0、
  16 个 P1；第二轮复审又补 2 个 P0（`time_suffice` 预算、P3 固定
  utility 时误钉 stable）及若干 P1（完整冻结负载、digest 细节、
  ADD override、单元模式 REPLACE）。修订已写回设计；仍有 3 项需要
  产品/架构拍板（Q1 层序已建议、Q13 本省排除、Q14 单元模式加专业）。
- 状态：修订后仍是 **Draft for review（未实现、未切流）**。
  第三轮 §八 的 4 个 P1 已在设计稿处置，回应见 §九；实现仍未达到
  设计状态（单次 `minimise()`、apply 重新生成、精确 `solverVersion`），
  本轮未运行测试或真栈验收。

---

## 一、四路评审的共同结论

四路评审独立收敛到同一组风险：

1. **保底不能排在 churn 之后**。`safety_guard` 是 hard/hard
   （`EvaluationProbeRegistry.java:46`）；churn-first 会保留“零本省保底”
   的旧方案，即使换 1 条就能过审，最后仍被 review 硬拦。
2. **预览≠确认的缺口在 FILL/PRIORITIZE**。当前 user-goal apply 会
   `generateUserGoalFixProposals` 重新求解（`PlanningStateService.java:1130-1157`），
   没有像 add/replace/remove/move 那样冻结 selected/ordered。
3. **候选帽不是“无损降维”**。初稿的保护集 + precheck + 2×cap 既超过
   solver 硬帽（600），也不能保证缩减集保留全量池的可行解/最优解。
4. **摘要口径会误杀正常 pending**。整池 digest + 精确 `solverVersion`
   相等（`RepairProposalApplyPolicy.java:95-117`）会在 overlay/候选池
   正常刷新或部署时把用户刚预览的卡判 stale。
5. **Ojalgo 不是“设个权重再重解”这么简单**。`mip_gap` 默认 1e-6、
   `time_abort` 每阶段独立计时、旧目标 weight 不清零会累加、
   `getValue` 读的是混合目标而不是层值。

---

## 二、P0 发现与处置

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| P0-1 | safetyDeficit 排在 churn 后；零保底旧方案会压过“换 1 条即可过审” | `EvaluationProbeRegistry.java:46`；`PlanningStateService.java:11203-11265` | 层序改为 **硬可行 → safety → churn → tierAnchor → utility → diversity → stable**；safety 只作为第一软层，不硬约束整单 |
| P0-2 | `churn*=optimum` 按初稿读取混合目标值不安全；`mip_gap=1e-6` 可能让 optimum 差 1 | 设计 §4.2；`OjalgoDeterministicPlanSolver.java:101-102,146`；Ojalgo 48.4.2 实测 | 每阶段用**纯层表达式**求 optimum；`mip_gap=0`；`Math.round`；只接受 `isOptimal()`（OPTIMAL/DISTINCT）；旧目标 `weight(0)` |
| P0-3 | FILL/PRIORITIZE 没有冻结 selected/ordered；apply 重新求解，预览≠确认 | `PlanningStateService.java:1130-1157`；`PendingPlanningCommandBizService` 只冻结 add/replace/remove/move | S0 把 selected/ordered/objective/version/digest 写进 pending；apply 用 `applyFrozenSelection/Ordering` 回放；未完成前不宣称“预览=确认” |
| P0-4 | REPLACE 初稿让 solver 选换入，但 J4a 已冻结换入+换出 | `UserGoalProposalBuilder` replace 预览；`PendingPlanningCommandBizService.java:631-710` | REPLACE 只校验/排序冻结集合；solver 结果与冻结不一致 → `solver_frozen_selection_mismatch`；不通过 solver 改选 |
| P0-5 | 2×cap 扩张直接违反 `MAX_CANDIDATES=600`；保护集 + precheck 不足以证明缩减集可行 | 设计初稿 §4.7；`OjalgoDeterministicPlanSolver.java:34,54-60,189-207` | 帽内替换，绝不扩到 600 外；witness best effort；`capLimited/globalOptimal=false` 明示；不可行报 `candidate_cap_infeasible` |
| P0-6 | 整池 digest + 精确 `solverVersion` 相等会 409 正常 pending；digest 检查在约束前，不合格选择可能靠 ID 检查通过 | `OjalgoDeterministicPlanSolver.java:477-508`；`RepairProposalApplyPolicy.java:95-117` | 改 **selection-scoped digest**；版本用 `solverObjectiveVersion` major + digest；apply 后必须过统一后置并失败回滚 |
| P0-7 | `time_abort` 是每阶段独立计时；3–4 阶段各 2s 会到 6–8s，且求解在写事务内持锁 | `OjalgoDeterministicPlanSolver.java:101`；pending 执行链 | 全局 2s deadline，每阶段传剩余预算；求解在写事务/行锁外完成，apply 只回放冻结结果 |
| P0-8 | 安全口径不一致：`userScore=null` 时 review 仍要求本省保底；明确排除本省时 review 仍硬失败；solver 初稿写成 `<580` 才要求 | `PlanningStateService.java:11214`；设计初稿 §4.3 | `SafetyFloorSupport` 统一 null/province/excluded 语义；`not_applicable` 必须等 J5.4 同步 review，否则保持旧口径 |

---

## 三、P1 发现与处置（摘要）

| # | 发现 | 处置 |
|---|---|---|
| P1-1 | 初稿 `safetyWeight` 未定义，1 点保底与 1 点档位偏差等权 | 改为独立 P1 safety 阶段；churn/tier 的 `Wchurn > maxTierDeviation`，用实际 `anchorSum` 推导 |
| P1-2 | utility 缺失按中性 50 会奖励缺数据（已知 40 输给“只有 preference、质量未知按 50”） | 缺失=0（保守）；`utilityCoverage` 只作诊断；数据补齐后自然回升 |
| P1-3 | 初稿把 diversity 与 utility 放同一加权阶段；多分组累计会让 1 utility 点被 3n 个 excess 压过 | utility 与 diversity 分阶段：P3 固定 utility*，P4 再优化 diversity |
| P1-4 | 单元模式 tier 取法不一致（首个 vs 代表）会让 fill 与 enforceSelection 数出不同档位 | 统一 `Entity.tier()`/`FillOption.representative` 的 canonical 排序；unit 内 tier 冲突直接 409 |
| P1-5 | 资格只做“硬约束+学费”，漏 `isCompensationSafeCandidate` 与单元 allMatch | Candidat​eFact 增 `compensationSafe/unitAllSafe`；fill/scope 复用既有谓词 |
| P1-6 | 单元内部分专业不合格时整组放行，apply 才失败 | unit 默认组原子；任一专业不合格则不可选，除非 policy 显式允许部分组 |
| P1-7 | 显式精确档位下 ADD 目标数增长会在 compiler 抛错，初稿却称 solver 处理 | compiler 二选一：重解配额 `tier_quota_rescaled` 或 `tier_quota_add_conflict` |
| P1-8 | 单元模式“向已有组加专业”会产生重复 entityId | 走专门组内补齐路径或 compiler 拒绝，不进 solver |
| P1-9 | FILL 保留项没有硬 lower bound，新 tier/safety 目标可换掉合规旧项 | 未列入 `removableEntityIds` 的 current 一律 `lower(1)`；零删除用硬约束，不用 churn 权重 |
| P1-10 | priority 是否影响选择未定；初稿“共用目标”表述过强 | J5.3 只保持排序；J5.4 再决定是否进选择；只统一 safety floor 支持类，不宣称 15 probe 同源 |
| P1-11 | 初稿 S0“旧路径逐字一致”不可验证：golden 依赖环境变量、无仓库内 fixture、`durationMs` 不稳定 | 仓库内放脱敏小 fixture；大池夜间跑；对比排除 `durationMs` |
| P1-12 | 候选帽保护集不看 tier upper=0，precheck 把不可用候选计入 available | precheck 排除 ineligible/tier 不可用；保护集按 coverage+tier+safety 代表；witness 优先保护 |
| P1-13 | 梯度/倒挂不在 solver 内，初稿“结构最优”容易被误读 | 明确非目标：梯度仍由 within-tier 排序 + review；精确配额下边界断层不可避免 |
| P1-14 | 静态 `@Value` flag 没有 `@RefreshScope`，回滚需重启 | 设计写明重启；要热回滚先引入配置中心/DB 开关 |
| P1-15 | S0 没有 per-path golden 门槛，回归会静默 | 每个路径单独 golden + 阈值 + 指标；`ADD/REFILL` churn=0、safety 硬失败不增 |
| P1-16 | 设计初稿“全仓 0 命中 CandidateSnapshot”表述不实（测试方法名命中） | 改为“无类型/实现”；修正失效行号引用 |

---

## 四、需要拍板的决策（修订后）

| ID | 决策 | 建议 | 备注 |
|---|---|---|---|
| Q1 | safety/churn/tierAnchor 层序 | **safety → churn → tierAnchor** | 四路评审一致；churn 只压档位锚，不压保底 |
| Q3 | safety 软/硬 | **软目标 + 第一软层 + review 硬诊断** | 硬约束会整单不可行 |
| Q4 | utility 缺失值 | **0（保守）** | 中性 50 会奖励缺数据；需影子对比 |
| Q5 | diversity 默认/层序 | **off；utility 之后单独 P4**；显式上限类需求另立 hard-cap schema | coverage 只能表达“至少 N 个”，表达不了“不超过 X%” |
| Q6 | 候选帽 | **witness + 保护集 + 帽内替换 + `capLimited`** | 不承诺全量池最优；不扩到 600 外 |
| Q10 | 冻结摘要 | **selection-scoped + 版本 major 兼容 + apply 后置** | 整池 digest 会误杀 overlay 刷新 |
| Q13 | 明确排除本省时 safety | **not_applicable，但必须 J5.4 同步 review** | J5.4 前按旧口径，避免双口径 |
| Q14 | 单元模式向已有组加专业 | **专门路径或 compiler 拒绝** | 进 solver 会重复 entityId/破坏组原子 |

---

## 五、修订后仍存在的风险

1. **Q13 未落地前**，solver 不能对“排除本省”的会话自行放行 safety；
   J5.4 前保持旧口径，可能继续出现“用户只看北京但 review 硬失败”。
2. **候选帽是启发式**，即使有 witness，也可能选不到全量池最优；
   golden 只能证明“不劣于基线/可解释”，不能证明全局最优。
3. **数据缺失=0** 会让数据不完整的候选系统性吃亏；需在影子期观察
   是否影响院校类型覆盖，必要时按省份/批次做数据补齐，而不是回退中性值。
4. **多阶段性能**仍是最大工程风险：必须用 600/64 的真实规模压测，
   再决定是否保留三阶段/四阶段或退化两阶段。
5. **FILL 冻结**是新增写链改动，需单独真栈验收（预览→确认→执行
   selected/ordered 完全一致），不能与 solver 切流混在一批。

---

## 六、第二轮复审（修订后）

对修订稿再做两路聚焦复审（算法 / 契约与迁移），结论：

| 项 | 状态 | 补充修订 |
|---|---|---|
| safety 层序/null/580/not_applicable | 已修 | 无新增 |
| 15 probe 边界 | 已修 | 无新增 |
| 混合阶段权重 | 已修 | `maxTierDeviation` 改为 `targetCount + anchorSum`（原 `max(3T, anchorSum)` 在 anchorSum>2T 时低估） |
| P3 固定 utility 时误钉 stable | 已修 | `fix_utility` 只钉纯 utility 表达式，不钉 stableOrder；否则 P4 diversity 无法交换 |
| Ojalgo 超时 | **P0 已修** | 只设 `time_abort` 不够；找到可行解后改用 `time_suffice`/`iterations_suffice`，必须每阶段同时设置 |
| 确定性 | **部分修** | `Σ stableOrder` 只是最小和，不是完整字典序；Ojalgo 并行 B&B 可能选不同等价解。要求 stableOrder 由总比较器分配 + 5 次重复测试；漂移时固定单线程/加 canonicalization |
| FILL/PRIORITIZE 冻结 | **部分修** | 除 selected/ordered 外，还必须冻结 `proposalId/strategy/targetCountOverride/tierQuotaChange/actions`；apply 要拿到 `pendingId` 并读 claimed pending，不能继续 `generateUserGoalFixProposals` 重新生成 |
| selection-scoped digest | **部分修** | 去掉“最终候选数”（取决于未选中候选）；去掉 per-entity 版本（当前不存在）；把 `compensationSafe/unitAllSafe` 纳入 digest；软权重变化只进 `solverConfigDigest`，用 `hardObjectiveVersion` 做失效判据 |
| 动作策略 | **部分修** | ADD override 必须 `>= current+added`；单元模式 REPLACE/加专业保持 J4a 路径，不能 volunteer/unit 混套；pinned 取消要有明确入口 |
| 候选帽 | 已修（诚实降级） | witness best effort、帽内替换、`capLimited`；无法证明时用 `solver_infeasible_after_cap`，不误报 `candidate_shortage` |

第二轮仍不建议直接实现：**FILL/PRIORITIZE 的完整冻结负载 + claimed
pending 读取**是下一道硬门槛；它涉及 gateway/apply 接口，不只是 solver
内部改动。实现前还必须先过两条工程门：
（1）Ojalgo 每阶段同时设 `time_abort/time_suffice`，否则 2s 预算不成立；
（2）600/64 规模 5 次重复求解的确定性测试，漂移时固定单线程或加
canonicalization。

## 七、评审结论

- 初稿的“单一入口 + 字典序 + 快照/目标/结果契约”方向正确，保留。
- 初稿的层序、候选帽、摘要、FILL 冻结、Ojalgo 数值细节、安全口径
  均需修订；修订已写回设计（见同目录 spec 的 §0/§3/§4/§5/§6/§7/§9）。
- **不建议在 J5.1 快照、FILL 冻结、S0 fixture 三项完成前进入实现切流**；
  可以先做 shadow 和单元测试。
- 实现顺序建议：S0（快照+冻结+摘要+fixture）→ S1（fill shadow/切流）
  → S2（initial）→ S3（scope/add/refill）→ S4（清理）。每步单独
  flag、单独 golden、单独回滚演练。

## 八、第三轮复核（契约与切流边界）

复核时间：2026-10-18。设计稿 SHA-256：
`ad23c4be746e242ba25afdb9ca60959a76b407974142ea62bdd8612ed4e4e70d`。
本轮只追加评审意见，不改设计稿。

| 优先级 | 发现 | 依据 | 建议处置 |
|---|---|---|---|
| P1 | S0 标题/退出条件写“不改行为、旧路径逐字不变”，但同一阶段要求 FILL/PRIORITIZE 从“apply 时重新求解”改为“回放预览冻结选择”。两者无法同时作为同一个验收口径。 | spec §6 S0（822、831-846）；§3.4 冻结要求（422-430）。 | 拆成 S0a（只做 snapshot、shadow、fixture，不改变 apply）与独立的冻结写链迁移；冻结写链用“预览选择 == apply 回放”验收，不要求旧的重新求解行为逐字相同。solver 切流仍等冻结链通过。 |
| P1 | 快照刷新与 pending 失效语义有歧义：§3.1 说 `sourceVersion/dataVersion` 变化必须使旧快照失效；§3.4 又说全局版本变化只记诊断、冻结 pending 可继续。若不区分“快照缓存可否复用”与“已冻结选择是否可 apply”，实现可能错误复用旧候选池，或反过来把正常刷新全部 409。 | spec §3.1（228-234）；§3.4（416-429）。 | 明确两个判定：版本变化必须重建用于新求解的 snapshot；pending apply 不比较整池版本，而重算 selection-scoped digest 并验证被选实体/当前项的硬事实。只有后者完全相同才允许回放。 |
| P1 | 候选帽保护集是多个独立 bucket 的 top-N 并集，可能在存在 ≤600 的可行 witness 时仍超过 600；此时按现文报 `candidate_cap_infeasible`，容易把“保护策略过度保守”误报成“问题本身不可解”。 | spec §4.7（696-727），尤其 coverage/tier/safety 分别保护后再判保护集大小。 | 先用完整硬约束验证 witness；可行 witness 是必保核心。其余替代候选应竞争剩余保护预算，而不是每个 bucket 独立全量保护；无法满足保护预算时用能说明“候选缩减策略受限”的诊断，不声称原问题不可行。加入“重叠 coverage + 可行 witness + 独立 top-N 并集超过帽”的回归用例。 |
| P1 | 稳定性层目前最小化 `Σ stableOrder`，不是 `(stableOrder, entityId)` 的完整字典序；文档已承认存在不同子集同和以及并行 B&B 等价解漂移，但把单线程/canonicalization 留作“测试漂移后”的降级措施。五次重复通过不能证明该目标本身形成全序。 | spec §4.2（520-525）；§4.6（678-688）。 | S1 前把稳定性契约二选一写清：实现确定性 canonicalization/逐位平局消解；或将承诺限定为固定 solver 版本、固定运行环境下的经验可重复性，明确不保证跨环境同解。避免仅靠 `Σ stableOrder` 声称全序。 |

### 当前实现对照（非设计稿缺陷）

- `OjalgoDeterministicPlanSolver` 当前仍是单次 `minimise()`，只设置
  `time_abort`（代码 101、144 行）；尚未实现设计中的分阶段、全局 deadline、
  `time_suffice`、`mip_gap=0` 和候选缩减器。
- `PlanningStateService.applyUserGoalFixProposal` 当前会重新调用
  `generateUserGoalFixProposals`（1138 行）；FILL/PRIORITIZE 的冻结回放仍是
  前置工作，不是现有能力。
- `RepairProposalApplyPolicy` 当前对 `solverVersion` 做精确相等校验
  （107-110 行），与设计提出的 hard-objective major 兼容策略不同。
- 因此本评审结论只针对设计合理性；不能据此认定实现、性能或真栈验收已通过。

### 更新后的判断

- 主架构与目标层序可保留；当前适合继续做 S0 设计收口、fixture 和 shadow，
  不适合直接开始 S1 切流。
- 在 S0 进入开发前，先修清上表前两项；候选帽的“保护集超限”语义和稳定性
  契约应在 S1 前拍板并加入回归用例。
- Q13（排除本省与 review 同步）和 Q14（单元模式向已有组加专业）仍是明确
  的跨模块决策；对应路径未定前不要开放相关 solver flag。

---

## 九、第三轮反馈处置（设计侧回应，2026-10-18）

本节只记录设计侧对 §八 四条 P1 的处置；不改前文评审意见。
§八 的设计稿 SHA 对应**第三轮评审时**的版本；本节处置后设计稿已变化。

| 反馈 | 设计稿处置 |
|---|---|
| S0“不改行为”与冻结写链冲突 | 拆成 **S0a（快照/shadow/fixture，明确不改行为，旧 apply 逐字不变）** 与 **S0b（冻结写链，行为变更，验收=预览 selected/ordered/digest == apply 回放）**；S1 前置为 S0a+S0b 都通过。见 spec §6。 |
| 快照刷新 vs pending 失效语义 | 明确两个判据：①用于**新求解/新预览**的快照要求 `sourceVersion/dataVersion` 一致，否则重建；②**已冻结 pending** 不比较整池版本，只重算 selection-scoped digest，验证选中/当前项硬事实；整池刷新只记 `snapshot_refreshed`。见 spec §3.1/§3.4。 |
| 候选帽 bucket 并集超 600 误报 | 改为 **mandatory（current/locked/pinned/forcedRequired）+ witness 先行**；witness 必须满足全部硬约束并包含 mandatory。mandatory/witness 超帽报 `candidate_cap_core_over_limit`；其余 coverage/tier/safety 代表竞争剩余 budget，放不下只记 `protection_budget_truncated`，不 block；witness 缺失且缩减集不可行报 `solver_infeasible_after_cap`。加入“重叠 coverage + 可行 witness + 独立 top-N 并集 >600”回归用例。见 spec §4.7/§7.1。 |
| `Σ stableOrder` 非完整字典序 / 跨环境 | 稳定性契约选 **B：固定部署内确定性**（单线程 Ojalgo + 唯一 stableOrder + 5 次重复）；**跨部署不承诺同解**，pending 靠冻结回放，跨环境只比较层值/结构向量；明确 `Σ stableOrder` 只是标量平局，不宣称完整字典序。严格字典序另立 canonicalization 里程碑。见 spec §4.6/§7.1/Q15。 |

### 实现状态确认

当前实现确实仍是：单次 `minimise()`、user-goal apply 重新生成提案、
`RepairProposalApplyPolicy` 精确比较 `solverVersion`；本次只改文档，
未运行测试或真栈验收。Q13/Q14 未拍板前不开放相关 solver flag。

---

## 十、第四轮实现复审与修复（2026-10-18 晚）

两路只读复审（路径正确性 / 迁移与 legacy 风险）针对当时工作区代码，
不回看设计稿。下面只列**已确认并已修**的项与**明确延后**的项。

### 10.1 已修（P0/P1）

| 发现 | 修复 | 验证 |
|---|---|---|
| freeze flag 会杀掉无 canonical 三件套的范围类提案（only_keep/exclude/tuition 为 READY 但 apply 必 409） | `frozenUserGoalProposal` 改为 pending+frozenProposal 优先回放；canonical 元数据只在没有冻结负载时才作为错误提示判据 | 真栈 900045 `only_keep 浙江` READY、无 canonical 元数据、apply 成功 |
| staged FILL 精确配额报 `tier_range`，后置校验按 `tier_exact` 比对 → 40905 | `StagedDeterministicPlanSolver.populateObjectiveResults` 与旧 solver 同口径：`exact_counts/ratios → tier_exact` | 单测 `exactTierAllocationReportsTierExactObjectiveType`；真栈 fill apply 通过 |
| 请求未重复已确认覆盖时，报告侧漏 `coverage:0` → 40905 | `UnifiedPlanPostconditionValidator` 按生成侧同一 `confirmed coverage + request include` 合并/排序重建报告要求 | 单测 `shouldReportPersistedCoverageRequirementWhenRequestOmitsRequirements` |
| initial staged 快照含 banned/compensation-unsafe 候选，apply 只认 available → `solver_candidate_missing` | snapshot 改用 `candidateFacts`，policy `requireCompensationSafe=true`，非 current 且不在 available 的 fact 标记 ineligible | 单测 + 编译 |
| 候选帽降维丢掉 current 行 → `removeEntityIds` 漏报，apply 后总数悄悄变多 | reducer 把所有 current 加入 keep（不强制选中）；solver 的 remove 名单按原始快照计算 | 单测 `currentFactsStayVisibleWhenLockExistingIsFalse`、`reducedPoolStillReportsRemovalOfCurrentFact` |
| `BeanUtils.copyProperties` 浅拷贝导致 `enrichV2` 改写原 `TierAllocationResolutionDTO` 的 digest/solverVersion | remove/add/replace/initial 统一 JSON 深拷贝 `copyObjectiveSet` | 编译 + 全量测试 |
| FILL staged 快照用全量池、additions 映射用 capped eligible → >600 时静默丢弃/假不足 | 快照池过滤为 capped eligible + retained | 单测 + 全量测试 |
| 预览摘要 `refreshOverlay=false`、apply `true`，且摘要 hash admissionRatio → 正常刷新误判 stale | 预览摘要先刷新 overlay；摘要去掉 admissionRatio（软数据，保留学费/省/档位/资格等硬事实） | `FrozenSelectionGuardTest` |
| 冻结只覆盖 proposal，不覆盖 apply 会持久化的 request → 同 proposalId 换请求可执行 | preview 落 `frozenRequestDigest`，apply 校验（排除 apply 时才补的 sourceVersionGuard） | 真栈改 scope 请求 → `409 user_goal_request_changed` |
| 负 tierAnchor 低估 churn 权重；null targetCount 拆箱 NPE；锁定项不合格时预览 ready/确认 409 | anchor 计数 clamp ≥0；targetCount null guard；`mustSelect && !eligible` 预览阶段 fail-closed | 单测 `addPolicy...` 等 + 全量测试 |

### 10.2 已记录、暂不阻塞切流

- pending 无 TTL：apply 仍有 digest/选择复核，过期 pending 只会 409，不会错写；
  TTL 与清理策略放到 S4/运维批。
- `RepairProposalApplyPolicy` 仍精确比较 `solverVersion`；freeze 模式下请求与
  proposal 同源，部署/回滚不会打断已冻结 pending；非 freeze 旧预览失败即要求重预览，
  fail-closed。S4 再改 major+digest。
- 单元档位冲突在无 tier 目标时也会 409：这是对既有脏数据的显式 fail-closed，
  等 J5.4/数据侧确认后再放宽。
- 2s 全局预算在 600 候选/3 阶段下实测约 472ms，余量充足；未调大。

### 10.3 真栈验收（2026-10-18 晚，flag 临时开启）

- 运行时：`-Dsolver.v2.shadow=true -Dsolver.v2.paths=fill
  -Dplanning.user-goal.freeze-apply.enabled=true`。
- 900045 staged fill + freeze：移除 2 个专业组制造缺口（44→42），
  preview selected=44 / remove=4 / add=6，pending 带 frozenProposal +
  selection digest；apply 后 44 组、version 18，后置校验通过（无 40905）。
- 900045 `only_keep 浙江`：READY、无 canonical 三件套，apply 成功
  （44→4 组），验证 P0 冻结回放。
- 同 proposalId 改请求：`409 user_goal_request_changed`。
- 验收后恢复 900045 version 14/44、900040 version 5/80；运行时已回到
  shadow-only（`solver.v2.paths`/freeze flag 关闭）。
- 全量 Java 测试：**1231 tests / 0 failures / 0 errors / 8 skipped**。

### 10.4 切流前收尾补验（2026-10-18 深夜）

- **scope（最终代码）**：900040 `add_units_by_scope` 浙江 80→82，
  `staged dry-run scope: session=900040 status=ready selected=82 remove=0 add=2`。
  验收中发现 `requireCompensationSafe` 被错误地套到 current 项上：900040
  有一个 current 单元不在补入安全口径内，导致 ADD 的 lockExisting 强制项
  被判不合格、整个范围加入被 block。已修为**只约束新增**（current 豁免，
  reducer 同口径），并补单测 `compensationSafeGateOnlyAppliesToNewAdditions`。
- **refill（最终代码）**：900045 制造 42/45 缺口后走真实
  `apply_constraint_and_regenerate` pending command；日志
  `refill staged solver applied: session=900045 target=45 current=42 added=16`，
  steps 含 `working_plan_refilled`，postcondition=true，version 15→19，
  ordered 45；随后恢复 14/44。
- **golden 回归**：新增 env-gated `StagedSolverGoldenTest`，10 个真实会话
  （900018/28/38/900040/900045/900016/900047/10041981/10041983/10041984）
  全部 ready，selected 两次运行一致；10041983（12,510 候选）走
  `candidate_cap_applied`，239ms。
- 切流检查单/回滚手册：`docs/superpowers/reviews/2026-10-18-j53-cutover-readiness.md`。
- 全量 Java：**1227 tests / 0 failures / 0 errors / 9 skipped**（含默认
  skip 的 env-gated golden）。
