# J5.3 Solver 设计：统一目标下的选择搜索

- 状态：**Draft for review（未实现，未切流）**
- 日期：2026-10-18
- 范围：方案选择/补齐/范围调整/点名加入/重补共用的 canonical solver
- 上游：J5.0 评价影子基线、J5.2 目标与评价（已完成）
- 下游：J5.4 后置条件/审查同源、J5.5 审查→动作、J6 风险姿态
- 关联：`docs/superpowers/reviews/2026-10-17-plan-generation-and-fill-analysis.md`
  §八（目标架构）、`docs/superpowers/reviews/2026-10-18-evaluation-golden-shadow-report.md`

> 本文只定契约、目标语义、算法与迁移路径；**不改运行时代码、不切流**。
> 文中出现的任何内部权重/分数/效用值都不得进入面向用户的文本、卡片、
> 工具返回或 prompt；用户侧只允许出现“更稳/更省/更匹配”这类直观结论。

---

## 0. 结论摘要（建议）

1. **一个入口**：所有“从候选里选哪些”的动作都走
   `CandidateSnapshot → IntentModel → ObjectiveCompiler → SelectionSolver`。
   solver 只做选择，不做排序后处理、不做持久化、不做审查。
2. **字典序目标**（评审后修订）：
   硬可行 → **保底缺口** → 改动成本（churn）→ 档位锚偏差 →
   软效用 → 多样性 → 稳定序。`GENERATE` 没有存量方案，churn 层自然为空。
   保底必须是第一软层：`safety_guard` 是 hard/hard，若排在 churn 之后，
   “零改动但零本省保底”会压过“换 1 条即可过审”，最终被审查硬拦。
3. **三到四阶段精确求解**，而不是把六层压成一个巨大权重：
   - P1 最小化保底缺口（不适用则跳过）；
   - P2 最小化 `Wchurn * churn + tierAnchorDeviation`
     （`Wchurn > max tierDeviation`，保证 churn 先于档位锚）；
   - P3 最大化软效用；
   - 多样性开启时，P4 在 utility 最优集合内最小化集中惩罚；
   - 稳定序只做各阶段的同值平局。
   每阶段记录目标值，可审计、可回归；避免 1e12 以上权重导致数值/容差问题。
   `mip_gap=0`、`isOptimal()`、全局 2s 预算，防止“间隙停止仍报 OPTIMAL”。
4. **J5.1 是硬前置**：当前没有 `CandidateSnapshot`，候选资格/覆盖键/效用
   分散在各路径。J5.3 先落一个最小快照契约（可先做适配器），否则 solver
   只是把现有 `stableOrder` 排序包装得更复杂，不会真正“选得更好”。
5. **候选帽统一**：600/64/2s 保留，但截断从“只有 fill 截”改为所有路径的
   `CandidatePoolReducer`；截断必须保留覆盖/档位/保底代表，并在截断后
   不可行时按确定规则做**帽内替换**（不扩到 600 外），最终仍不可行
   才 fail-closed。
6. **默认不改审查口径**：solver 的结构目标与 review probe 共用同一份
   `StructureTarget`/`SafetyFloorSupport`，但 J5.3 不删除/不改写 15 个 probe；
   `ratio_distribution` 与 `tierQuotaGoal` 的口径统一放 J5.4 前置项。
7. **软效用/多样性默认隐藏**：效用分只用于内部求解与影子对比，不进 API；
   多样性默认关闭，用户明确要求时优先编译成 coverage 硬约束，而不是
   只给一个“看着更分散”的软分。

**实现状态（必须诚实标注）**：旧 solver 仍是单次
`minimise()`、user-goal apply 默认仍会重新生成提案、版本检查仍是
`solverVersion` 精确相等。S0a 已落 shadow 切片（快照/效用/分阶段
solver/候选 reducer/`solver.v2.shadow` 默认关）；S0b 第一刀已落
（`planning.user-goal.freeze-apply.enabled` 默认关，冻结
`frozenProposal` + `frozenSelectionDigest` 并优先回放；flag 开启后
不再回退 legacy 重新生成）。**diversity、真栈/性能验收尚未完成**；
本文所有验收
结论只针对设计，不代表实现、性能或真栈已通过。

---

## 1. 现状：solver 能做什么、不能做什么

### 1.1 现有链路

```
PlanningStateDTO + effectiveCandidates
  → PlanningObjectiveCompiler.compileConfirmed()      // 只编硬目标
  → CanonicalPlanningRuntime.enforceSelection()        // 当前/可用实体
  → PlanSolverInputDTO{ objectiveSet, candidates }     // 无效用/无资格原因
  → OjalgoDeterministicPlanSolver.solve()
  → applySelection() / applyOrdering()
```

关键事实（均以当前代码为准）：

| 事实 | 位置/证据 |
|---|---|
| 目标编译器只承接 `fill_to_count` / `prioritize_within_tier` | `PlanningObjectiveCompiler.java:43` |
| `compileConfirmed` 只编 selectionTarget/coverage/tier/priority | `PlanningObjectiveCompiler.java:65-75` |
| solver 权重只有 churn `1e12` 与档位偏差 `1e6` | `OjalgoDeterministicPlanSolver.java:38-39` |
| 候选质量只通过 `stableOrder` 影响结果 | `OjalgoDeterministicPlanSolver.java:103-119`、`CanonicalPlanningRuntime.java:648-655` |
| 没有软效用、没有多样性、没有梯度目标 | 同上；`StructureVectorDTO` 只用于评价 |
| 没有 `CandidateSnapshot` 类型/实现 | 仅测试方法名 `should...SyncCandidateSnapshot` 命中；无 DTO/Builder |
| 资格在 solver 输入里恒为 `true` | `CanonicalPlanningRuntime.java:721`、`UserGoalProposalBuilder:4565/4636` |
| coverage 在调用方现算 | `CanonicalPlanningRuntime.java:723-731` |
| 只有 fill 做了 600 候选截断 | `UserGoalProposalBuilder.java:2244-2261` |
| `enforceSelection` 把全部 available 直接送 solver | `CanonicalPlanningRuntime.java:51-59` |
| 大池 + 已确认目标时 initial 等路径可能直接 blocked | 同上 + `OjalgoDeterministicPlanSolver.java:54-60` |
| priority 是求解后的 within-tier 重排，不是搜索目标 | `OjalgoDeterministicPlanSolver.java:310-337` |
| `hasSelectionObjectives` 只看 target/coverage/tier | `CanonicalPlanningRuntime.java:35-38,609-617` |
| 初荐、refill、scope、add/remove 大量走启发式 | `PlanningStateService` 的 initial/refill/scope 生成段（见 10-17 分析 §三/§四）；`UserGoalProposalBuilder` 的 move 启发式 |
| `StructureVector` 不持久、不回流 solver | `ReviewEvaluationMapper.java:312-374`；`PlanningStateService.java:3269-3275` |
| FILL/PRIORITIZE 预览没有冻结 selected/ordered；apply 会重新生成提案并再求解 | `PlanningStateService.java:1130-1157`、`UserGoalProposalBuilder` 预览段 |
| pending 的 canonical 元数据比较 `solverVersion` 精确字符串；整池 digest 在 overlay 刷新时可误杀 | `RepairProposalApplyPolicy.java:95-117`；`OjalgoDeterministicPlanSolver.java:477-508` |
| J5.0 golden 已覆盖 8 个真实会话（含 32MB 池 10041983） | `docs/superpowers/reviews/2026-10-18-evaluation-golden-shadow-report.md` |
| 现有 ADR benchmark：400 候选/16 约束、120/8、pinned 不可行 | `PlanSolver410AdrBenchmarkTest.java:31-66` |
| 实测 2026-10-18：400 候选/20 约束单次 OPTIMAL ≈146ms；120/12 ≈4ms | `mvn -Dtest=PlanSolver410AdrBenchmarkTest test` 输出 |

### 1.2 结论

当前 solver 是**约束满足 + 最小改动 + 历史档位锚定**器，不是“整体最优”器：

- 能保证：数量、覆盖下限、显式档位区间、锁定项、优先级重排；
- 不能保证：在合规前提下选到更匹配/更稳/更省/更分散的候选；
- 各动作的候选源、过滤、排序键、后置校验仍不统一（3 套候选源、
  4 套过滤、5 套排序键、2 套求解、4 套后置）。

J5.3 只解决“**选择**”这一层：把“什么算好”变成可度量、可复现、可审计的
目标，并让所有动作共用同一求解入口；排序、后置、审查、修复仍归各自层。

---

## 2. 目标与非目标

### 2.1 目标

1. **单一选择入口**：生成/补齐/范围调整/点名加入/重补的“选哪些”都由
   `SelectionSolver` 给出；启发式只保留候选预排序、稳定序与显式降级。
2. **目标可解释**：每份 solver 结果带分层目标值（churn/结构/效用/多样性）
   与诊断；预览/回执能说清“为什么换/为什么没换”，但不出现系数。
3. **硬约束不放松**：资格、数量、覆盖、显式档位、锁定、动作冻结集合
   仍然是不可违反的约束；solver 不得用软效用交换硬约束。
4. **最小必要变更**：对已有方案的动作，先比“少改”，再比“结构/更好”；
   `ADD/REFILL` 的“零删除”是硬策略，不是软偏好。
5. **确定性（固定部署内）**：同一部署环境 + 同一输入（含目标模型版本/
   权重/候选事实）→ 同一选择；跨部署只保证冻结回放不变，不承诺
   新预览同解。时间中止/不可行必须显式失败，不静默返回次优解。
6. **可回滚**：新旧 solver 可并存；按路径灰度；冻结命令仍按预览时的
   选择与摘要执行。

### 2.2 非目标（明确不做）

- 不重写审查规则，不删除 `ReviewStateDTO.checks`（J5.0 已审计，另分三段）。
- 不把梯度/倒挂线性化成 solver 硬约束（非线性、易不可行）；仍由
  within-tier 排序 + review 诊断处理。精确档位（如 5/5/5）在分数边界
  上必然出现跨档位断层，solver 不承诺 `probability_gap` 软失败为 0；
  golden 只要求不劣于基线，不把“梯度完美”当验收条件。
- 不实现 J6 的风险姿态/目标优先级层；J5.3 只预留 `StructureTarget` 的
  扩展点。
- 不统一 repair/fix 的选择器（J5.5）；J5.3 只保证 repair fix 将来能
  调用同一 solver 契约。
- 不把效用/权重/概率暴露给用户，也不在 prompt 里出现“权重/打分”。
- 不在本阶段做数据库迁移；快照/效用都是内存派生。

---

## 3. 契约

### 3.1 `CandidateSnapshot`（J5.1 最小切片）

```java
class CandidateSnapshot {
    String snapshotVersion;        // candidate-snapshot-v1
    Integer sourceVersion;         // 候选池来源版本
    String dataVersion;            // 数据新鲜度
    String volunteerModel;         // majorGroup | major
    String countMode;              // unit | volunteer
    String sourceProvince;         // 生源省（safety floor / 地域多样性）
    String normalizationDigest;    // 效用归一化/分位数的摘要
    List<CandidateFact> facts;
}

class CandidateFact {
    String entityId;               // unitId 或 volunteerId
    List<String> volunteerIds;     // 单元模式下组内专业
    String unitId;
    String schoolId;
    String majorId;
    String provinceId;
    String provinceName;           // 本省保底/地域多样性
    String cityId;
    String cityName;
    String schoolLevel;
    String schoolNature;
    String schoolCategory;
    String majorCategoryId;
    String majorSubCategoryId;
    Integer tuitionPerYear;
    Double admissionRatio;
    Double schoolEnrollRatio;
    Double intentScore;
    Double finalScore;
    Double futureDevelopmentScore;
    List<String> riskFlags;
    String tier;                   // 冲/稳/保（canonical key: sprint/stable/protect）
    String tierSource;             // explicit | school_ratio
    boolean eligible;              // 对已确认硬约束 + 学费的资格
    List<String> eligibilityReasonCodes;
    List<String> coverageKeys;     // "region:浙江" "major_category:计算机" ...
    Map<String, Integer> utilityComponents; // preference/quality/safety/future/cost，0..100
    int utilityScore;              // 0..100，整数，隐藏
    int utilityCoverage;           // 有值分量权重占比，0..100
    boolean compensationSafe;      // 复用 RepairCandidateSelector 的补入安全谓词
    boolean unitAllSafe;           // 单元模式：组内全部专业都 compensationSafe
    Boolean priorityMatched;       // 已确认同档优先规则是否命中（排序/诊断用）
    boolean current;
    boolean locked;
    boolean pinned;
    int stableOrder;               // 由统一排序键生成，唯一且 0..n-1
}
```

规则：

- **eligibility 与 visibility 分开**：候选池查询仍可看到不合格候选，但
  `eligible=false` + 原因码；solver 对不合格项直接 `upper(0)`。
- `coverageKeys` 必须由 `CoverageRequirementSupport` 同一匹配函数派生，
  不允许调用方各写一套“按名字/按 ID”的匹配。
- `CandidateFact.eligible` 只表示**已确认的会话硬约束 + 学费**；动作本轮
  新增的 requirements/scope 是 objective delta，由 compiler 写进
  `eligibilityConstraints`，solver 选择时再做一次
  `fact.eligible && matches(fact, objectiveSet.eligibilityConstraints)`。
  这样同一版快照可服务 fill/scope/add，不会因为“本轮要求”不同而改变
  snapshot digest。
- **资格有动作剖面，不要压成一个 boolean**：`eligible`（硬约束+学费）、
  `compensationSafe`（fill/scope 的补入安全谓词）、`unitAllSafe`（单元
  模式下组内全专业安全）。fill/scope 必须延续
  `RepairCandidateSelector.isCompensationSafeCandidate` 与“单元内
  allMatch”语义，否则 v2 fill 会选到现行路径明确排除的候选。
- **单元 tier 必须一致**：同一 unit 的 candidates 若 canonical tier 不同，
  直接 `409 tier_fact_conflict`；unit tier 的取法必须与
  `CanonicalPlanningRuntime.Entity.tier()` 和 `FillOption.representative`
  同源（按同一 canonical 排序取首），不能一边取首个、一边取代表，
  否则 fill 与 enforceSelection 会数出不同档位。
- **单元内专业资格**：unit 模式下 fact 保留组内每个专业的
  `eligible/compensationSafe`；只要有一个专业不满足当前硬约束，unit
  默认不可选（组原子性），除非动作 policy 显式允许“组内部分专业”。
  不能因为代表专业合格就整组放行，否则 applySelection 会在写入时
  才失败（`solver_candidate_apply_failed`）。同一 unit 内 canonical
  tier 不一致 → `409 tier_fact_conflict`，不允许按代表专业静默取档。
- **current 来源（过渡期）**：`CandidateSnapshotBuilder.CurrentSource`
  区分 `WORKING`（enforceSelection/refill 旧口径）、`ORDERED_FIRST`
  （fill/add/remove/replace 旧口径）、`UNION`（shadow/diagnostic）。
  这是为了切流期与旧路径对齐；全量统一后应收敛为一个 canonical 来源。
- **补入安全**：FILL/SCOPE staged 路径必须设置
  `MutationPolicy.requireCompensationSafe=true`，与旧 fill/scope 的
  `isCompensationSafeCandidate` 过滤同源；ADD 精确点名不强制。
- `utilityScore`/`utilityComponents` 只存在于 snapshot 与内部求解路径；
  不得序列化到 agent 工具结果、WS 事件、Web 卡片或 prompt。
- `stableOrder` 的来源：
  - S1 兼容期：沿用各路径现有顺序（initial/fill/scope 各自的 comparator），
    只保证“同一路径同一输入稳定”；
  - S3 统一切换：所有路径使用同一个 canonical 排序键
    `intentScore ↓ → finalScore ↓ → admissionRatio ↓ → schoolRank ↑ → id ↑`，
    切换必须过 golden diff（见 §7）。
- 快照不落库。候选池/推荐 overlay/学费更新后重新构建；`sourceVersion`/
  `dataVersion` 变化必须使旧快照**不能用于新的求解/预览**。
  注意：这不等于“所有 pending 立刻失效”——已冻结选择是否可 apply
  由 §3.4 的 selection-scoped digest 单独判定。两个判定不要混用：

  | 判定 | 输入 | 变化后果 |
  |---|---|---|
  | 快照能否复用（新求解） | `sourceVersion`/`dataVersion`/objective | 重建快照，旧快照丢弃 |
  | 冻结选择能否 apply | 选中实体硬事实 + 硬目标/policy | 事实变了才 409；整池刷新只记诊断 |
- **构建时机**：必须沿用 J4a 的顺序——先 `resolveEffectiveCandidates`
  刷新 overlay，再构建快照；不能在 apply 中途或 overlay 回填前构建，
  否则未落盘的 scope/学费会被旧 overlay 覆盖（J4a 已踩过）。
  预览求解用快照 A；apply **不重解**，只按 §3.4 重建
  selection-scoped digest 验证冻结选择（验证的是选中实体硬事实，
  不是拿新快照再解一遍）。不允许一边预览用 A、确认时重建 B 重新
  求解。
- **单元模式的实体语义**：entity=专业组/单元；utility 分取该单元内
  `stableOrder` 最前（预览代表专业）的分量，不对组内专业求和/取最大；
  coverage 仍按“单元内任一专业命中”计 1 个单元。该口径与现有
  `FillOption.representative`/`matchedCoverageIds` 一致，不在 J5.3 改变
  覆盖计数单位；单元内专业排序归 Ordering 层。
- 分位归一化只在 `eligible=true` 的候选上计算，避免不可选候选拉偏
  效用分布；不合格候选仍保留 utility 值（可用于解释/影子），但不参与
  选择。
- **工作草案里的存量项即使不在候选池，也必须有 fact**（
  `source=working_plan`，事实可缺失但 `current=true`）；否则 solver
  无法“保留旧项”，会把它当不可见而删除。这类 fact 的 utility 缺失按
  §4.4 的缺失规则处理，且不参与分位基准。

**最小 J5.1 交付**：`CandidateSnapshotBuilder` + `CandidateFact` +
`CandidateUtilityScorer`，先服务 fill 与 enforceSelection；其他路径在
S3 接入。若 J5.1 延期，J5.3 只能进 shadow，不得切流。

### 3.2 `IntentModel` 与 `SolverObjectiveSet`

J5.3 不新建第二套目标模型；在 `CanonicalPlanningObjectiveSetDTO` 上做
**向后兼容扩展**（新字段可空，旧路径忽略）：

```java
class CanonicalPlanningObjectiveSetDTO {
    // 现有：schemaVersion/sourceVersion/countMode/targetCount/
    //       eligibilityConstraints/coverageConstraints/
    //       tierAllocationGoal/tierAllocationConstraint/
    //       tierAllocationResolution/orderingConstraints/objectiveDigest

    // J5.3 新增（全部可空）
    StructureTarget structureTarget;
    UtilityModel utilityModel;        // 只存版本与分量权重，不存候选值
    DiversityPolicy diversityPolicy;  // 默认 null/off
    MutationPolicy mutationPolicy;
    String hardObjectiveVersion;      // solver-hard-objective-v1
    String solverObjectiveVersion;    // solver-objective-v1（含软权重，诊断）
}

class StructureTarget {
    TierCountsDTO tierAnchor;         // 目标档位分布（非硬约束）
    Integer minLocalProtect;          // 0/1/2；null=不适用
    String safetyFloorMode;           // applicable | not_applicable | unknown
    String safetyFloorReasonCode;     // score>=580 | province_missing |
                                       // province_excluded | ...
}

class UtilityModel {
    String utilityModelVersion;       // utility-model-v1
    Map<String, Integer> componentWeights; // 内部；不进 API
}

class DiversityPolicy {
    String mode;                      // off | soft
    List<DiversityGroup> groups;      // region/major_category/school_level
    Integer maxGroups;                // 默认 16，上限 32
}

class MutationPolicy {
    String action;                    // GENERATE|FILL|ADD|REPLACE|REFILL|SCOPE|REVIEW_FIX
    boolean allowAdd;
    boolean lockExisting;             // true: 所有 current 默认不可删
    Set<String> forcedRemoveEntityIds; // REPLACE: 必须删（upper=0）
    Set<String> removableEntityIds;    // FILL/SCOPE: 允许删但不强制
    Set<String> frozenRequiredEntityIds; // ADD: 必须选（lower=1）
    Set<String> forcedAddEntityIds;      // REPLACE: J4a 冻结的换入（lower=1）
    boolean countAsChurn;              // 显式“重新生成/优化”可置 false
}
```

约束语义：

- `tierAllocationConstraint` 存在 → 档位是**硬区间**；`structureTarget.tierAnchor`
  只是软锚定，不得放松硬区间。
- `minLocalProtect` 是**结构目标**（可欠账），不是硬约束：候选不足时
  solver 仍要能出方案，并报 `safety_floor_unmet`；硬判据仍由 review 的
  `safety_guard` 给出。
- `mutationPolicy.frozenRequiredEntityIds` → 变量 `lower(1)`；
  `forcedRemoveEntityIds` → 变量 `upper(0)`；
  `removableEntityIds` → 这些 current 变量不锁，其余 current 在
  `lockExisting=true` 时 `lower(1)`。
- 任何动作的“零删除/只补不删”都是硬策略，不靠 churn 权重表达。
- **policy 归一化**（compiler 出口统一做，solver 不再猜）：
  - ADD/REFILL：`lockExisting=true`、`forcedRemove/removable` 为空；
    若调用方同时给出可删集合，编译期 `mutation_policy_conflict`；
  - REPLACE：`forcedRemoveEntityIds` 与 `forcedAddEntityIds` 都必填且来自
    J4a 冻结；其余 current `lower(1)`；solver 结果必须与冻结集合一致，
    否则 `solver_frozen_selection_mismatch`；
  - FILL：`removableEntityIds` 只放“不满足本轮硬要求”的 retained；
    其余 current `lower(1)`；
  - SCOPE/REVIEW_FIX：`removableEntityIds` 为空且 `lockExisting=false`
    表示允许替换任意 current；若只想删范围违规项，显式填集合；
  - `frozenRequiredEntityIds` 必须属于 eligible，否则编译期
    `required_entity_ineligible`，不允许 solver 静默忽略；
  - `forcedRemove` 与 `frozenRequired` 不得相交。
- **schema 版本**：兼容模式继续用 `4.1.0-m2`；v2 模式用
  `4.2.0-j53`，新字段只在 v2 编译时写入。旧 pending 预览以
  `hardObjectiveVersion` 缺失判定为 legacy，不因新字段导致 digest 漂移。

### 3.3 `SolverRequest` / `SolverResult`

```java
class SolverRequest {
    CandidateSnapshot snapshot;
    CanonicalPlanningObjectiveSetDTO objectiveSet;
    // 兼容：现有 PlanSolverInputDTO 由 request 适配而来
}

class SolverResult {
    String status;                    // ready|no_change|blocked
    String solverVersion;             // 实现版本（诊断）
    String hardObjectiveVersion;      // 硬目标/层序/policy 语义
    String objectiveModelVersion;     // 完整目标模型（含软权重，诊断）
    String inputDigest;               // apply 失效判据：硬事实/硬目标/policy/层序
    String solverConfigDigest;        // 软权重/多样性配置；诊断，不做 apply 失效
    List<String> selectedEntityIds;
    List<String> orderedEntityIds;
    List<String> removeEntityIds;
    List<String> addEntityIds;
    List<ObjectiveLevelResult> levels; // 内部可审计；不进 FixProposalDTO/WS/工具
    List<Diagnostic> diagnostics;      // 只放原因码 + 人类可读结论
    TierCountsDTO resolvedTierCounts;
    Long durationMs;
    SolverTrace trace;                // 仅日志/测试，不序列化到 API
}
```

`levels` 与 `trace` 只允许出现在服务端测试/日志；`FixProposalDTO.solverResult`
只保留 `solverVersion/hardObjectiveVersion/inputDigest/status/diagnostics`
（沿用现有字段），不得把 utility 分值、权重、分量写成 JSON 下发。
实现上优先用独立的内部 `SolverTrace` 返回，再由 adapter 映射到
`PlanSolverResultDTO`；若图省事把字段加进 DTO，必须
`@JSONField(serialize=false)` 并加序列化白名单契约测试（见 §7.1）。

`ObjectiveLevelResult`：

```java
class ObjectiveLevelResult {
    String level;        // safety|churn|tier_anchor|utility|diversity|stability
    long value;          // 该层实际目标值
    long optimum;        // 该阶段求得的最优值（已取整）
    String unit;         // deficit_points|removed_entities|deviation_points|utility_points
    boolean optimal;
}
```

**禁区**：`utility` 的原始分值、`utilityComponents`、权重系数只能出现在
`SolverTrace`（`@JsonIgnore`/不进 DTO 序列化白名单）与测试日志中。API
只允许返回 `safety_floor_unmet`、`candidate_cap_applied` 这类原因码和
用户能懂的中文结论。

### 3.4 版本与摘要

- `solverVersion`：实现版本，例如 `ojalgo-48.4.2-j53-phase3`；只作诊断，
  **不做跨部署的硬相等条件**。
- `hardObjectiveVersion`：硬目标/层序/动作 policy 的语义版本
  （`solver-hard-objective-v1`）；这些变化才可能让冻结选择不再成立。
  `solverObjectiveVersion`：完整求解配置版本，包含软效用权重/多样性；
  变化只进 `solverConfigDigest`，不应让 pending 失效。apply 只要求
  **`hardObjectiveVersion` 同一 major**；软权重调整不应 409。
  这样部署/回滚时旧 pending 不会因实现版本字符串变化而全部 409
  （现有 `RepairProposalApplyPolicy` 是精确相等）。
- `inputDigest` = 以下四部分的 canonical JSON（键排序、整数/定点格式化）：
  1. `objectiveDigest`（现有，但**必须扩展**覆盖硬目标与 policy：
     eligibility/coverage/tier/priority/StructureTarget 的 safety 口径/
     MutationPolicy/**`hardObjectiveVersion` 的 major 段**；现有
     `PlanningObjectiveCompiler.digest` 只覆盖旧字段）。
     **UtilityModel 权重与 DiversityPolicy 只进 `solverConfigDigest`
     （诊断/版本），不进 apply 失效判据**——调软权重不应让用户刚确认的
     卡失效；冻结的是选择，不是解释分数；
  2. **selection-scoped facts**：selected/ordered 实体 + 当前方案实体 +
     forced/removable/required 实体的
     `entityId/volunteerIds/tier/eligible/compensationSafe/unitAllSafe/
     coverageKeys/current/locked/pinned`，以及每个实体的**硬事实**
     （province/tuition/admissionRatio/major 资格）。不存
     “该实体的数据版本”——当前只有池级版本，没有 per-entity 版本；
     直接 hash 硬事实本身，事实没变就不失效；
  3. **截断上限**（cap=600）+ 层序（safety→churn/tier→utility→
     diversity→stability）；**不存截断结果**
     （`droppedCount/candidateCountSolved`）——它取决于未选中候选，
     正常刷新会变化；
  4. 动作 policy（forced/removable/required/countAsChurn）。
- **为什么不是整池 digest**：推荐 overlay/候选池刷新会改变未选中候选的
  顺序/分数，整池 digest 会让“预览后正常刷新”也 409。selection-scoped
  digest 只在“用户看到的选择或其硬事实变化”时失效；新增未选中候选
  不影响。**全局 `candidateSourceVersion`/`dataVersion`/normalizationDigest
  只进诊断，不作为 pending 失效条件**——它们是数据新鲜度，不是选择
  一致性；选中实体的硬事实变化才进 digest。
- **与快照复用分开**：全局版本变化时，**新求解/新预览必须重建
  snapshot**（§3.1）；但已确认的 pending 不因整池刷新自动失效，
  只重算 selection-scoped digest。实现上这是两个函数/两个判据，
  不允许用一个 `sourceVersion` 同时决定“快照缓存”和“pending 可否
  apply”。
- **“用户已确认的选择”优先于“重新求解更优”**：apply 不重跑 solver；
  即使新候选会让结果更好，也按冻结结果执行。避免用户确认的卡在
  确认瞬间变样。
- **apply 重建**：apply 时用当前状态重建同一 digest：
  - 选中实体缺失、资格/tier/coverage/学费/province 等硬事实变化、
    objective/policy 变化 → `409 solver_input_stale`；
  - 仅新增/刷新未选中候选、全局 sourceVersion/dataVersion 变化 →
    允许继续，按冻结结果执行；诊断里记录 `snapshot_refreshed`。
- **apply 后置**：应用冻结选择后必须再跑
  `UnifiedPlanPostconditionValidator`；冻结选择在“预览时合法、应用时
  因并发/覆盖已不合法”的情况下必须整笔回滚，不能因为 ID 检查通过就落盘。
- **FILL/PRIORITIZE 的冻结缺口**：当前 user-goal apply 会重新
  `generateUserGoalFixProposals` 再按 strategy 应用，FILL 并没有像
  add/replace/remove/move 那样把 selected/ordered 冻结进 pending。
  J5.3 S0b 必须补：
  - pending `frozenCommand` 存**完整回放负载**：
    `proposalId/strategy/targetCountOverride/tierQuotaChange/actions/
    selectedEntityIds/orderedEntityIds/solverVersion/hardObjectiveVersion/
    objectiveDigest/inputDigest`；
  - apply 请求带 `pendingId`（或由网关把 pending 句柄透传），
    `applyUserGoalFixProposal` **按 claimed pending 读取冻结负载**，
    不再 `generateUserGoalFixProposals` 重新生成；
  - 回放仍走 `applyFrozenSelection`/`applyFrozenOrdering` +
    统一后置；未补之前不得宣称“预览=确认”。
  - 若 pending 句柄在当前网关协议里拿不到，先把 `pendingId` 加进
    `FixProposalApplyReq`/gateway 透传；这是 S0b 的接口改动，不是
    solver 内部可以绕过的问题。
  - 兼容旧客户端：请求未带 `pendingId` 时走既有“重新生成再应用”路径，
    回执/诊断标 `preview_recomputed=true`，**不得声称冻结回放**；
    新客户端默认带 `pendingId`。

---

## 4. 目标函数

### 4.1 层序（推荐）

```
L0 硬可行      eligibility / count / coverage / tier bounds / locked /
                pinned（除非动作显式解除）/ forced required / forced remove /
                zero-remove policy
L1 safety      本省保底缺口 safetyDeficit（0..minLocalProtect）
L2 churn       当前实体被移除的数量（GENERATE/ADD/REFILL 为 0 或跳过）
L3 tier anchor |count_t - anchor_t| 之和（没有 anchor 则跳过）
L4 utility     Σ utilityScore(x)
L5 diversity   软惩罚（默认关闭）
L6 stability   (stableOrder, entityId) 全序平局
```

**为什么 safety 在 churn 前**：

- `safety_guard` 在 `EvaluationProbeRegistry` 是 hard/hard
  （`EvaluationProbeRegistry.java:46`），不是“软偏好”；churn 先会保留
  “零本省保底”的旧方案，即使换 1 条就能过审，最终审查硬失败。
- 保底缺口只有 0..2 点，先最小化它不会显著增加改动；它是“能不能兜住”
  的底线，高于“少改”。
- 若某会话明确排除了生源省（如“只去北京”），`SafetyFloorSupport` 返回
  `not_applicable`，L1 跳过；不能让用户既被排除本省又被要求本省保底
  （见 Q13，需 J5.4 同步 review probe）。

**为什么 churn 在 tierAnchor 前**：

- 产品原则是“最小必要变更”；用户已确认的档位目标已经是硬约束，
  软锚定只是“像原来一样”的偏好，不应为了更像历史分布而多换条目。
- 生成场景当前方案为空，churn 层自然为 0，档位锚直接生效。
- safety 是唯一例外：它是硬审查底线，必须先于 churn。除此之外，
  若评审要求“显式结构修复”压过 churn，走 `countAsChurn=false` 的
  GENERATE/optimize policy，而不是改全局层序。

**safety 仍是软目标**：候选池没有本省保底时，方案不能整体不可行；
欠账通过 `safety_floor_unmet` 诊断与 review 硬失败暴露。若 `userScore`
为 null，按“未证明安全”处理（与 review 一致）；`score>=580` 时
`minLocalProtect=0`，但 `ratio_distribution`/`group_inner_safety_guard`
仍由 review 独立判断，solver 不宣称已覆盖全部安全审查。

### 4.2 求解方式：三阶段（+可选多样性阶段）字典序

不采用“单目标大权重”把所有层压成一个数。原因：

- 六层 × 最多 600 候选，严格分隔需要 1e13–1e16 量级权重；Ojalgo 的
  MIP/LP 容差与 double 有效位会让低层目标被高层吃掉（现有 1e12 已是
  可接受上限）。
- 分层求解让每层最优值可记录、可断言、可解释；回归差异能定位到层。

推荐流程（每阶段的“目标表达式”必须是**纯层表达式**，不能拿带
1e12/稳定序的旧 target 当 optimum）：

```
stage0: 建模型（变量/硬约束/动作策略）
stage1: if safety applicable:
          minimize safetyDeficit                     // 纯表达式
          safety* = round(optimum); fix_safety.upper(safety*)
stage2: if churn or tierAnchor applicable:
          minimize Wchurn * Σ removed + Σ tierDeviation
          Wchurn = maxTierDeviation + 1
          mixed* = round(optimum); fix_mixed.upper(mixed*)
          // 该混合阶段保证 churn 先于 tierAnchor；若没有 churn，
          // 退化为纯 tierDeviation；若两者都没有，跳过。
stage3: maximize utility（stable 仅作同值平局）:
          minimize -(maxStableTotal+1) * Σ utilityScore + Σ stableOrder
          utility* = round(optimum); fix_utility.upper(utility*)
stage4: if diversity enabled:
          minimize (maxStableTotal+1) * Σ excess + Σ stableOrder
          （utility 已固定，diversity 只在其最优集合内比较）
```

细节：

- **P1 的 optimum 必须来自纯 safetyDeficit 表达式**，不能从旧目标的
  `getValue()` 读（旧目标含 churn/stable，值不是层值）。P2 的混合目标
  同理；`fix_phaseK` 只约束该层语义的加权和，不逐分量钉死（多个最优解
  可能在 safety/tier 分量间互换）。
- **P3 的 `fix_utility` 只钉纯 utility 表达式**（只含 utilityScore 的
  负系数），**不能把 stableOrder 一起钉死**；stage3 目标里的 stable 只是
  同值平局。否则 P4 的 diversity 无法用 stable 做次级交换，字典序
  utility→diversity→stable 会被破坏。
- **`mip_gap=0`**：Ojalgo 默认 `mip_gap=1e-6`，间隙停止仍可能报
  `OPTIMAL`，使 `churn*`/`safety*` 相差 1，后续阶段就不再是字典序。
  `Options.mip_gap` 显式置 0，目标值用 `Math.round` 取整后固定；
  取整前校验 `|optimum - round(optimum)| <= 1e-6`，否则
  `solver_objective_precision`（不允许带着浮点误差进入下一阶段）。
- **全局预算**：`time_abort` 是每次 `minimise()` 独立计时，三阶段各
  2000ms 会到 6s。必须维护一个 2s 的全局 deadline，每阶段把
  `min(perStageCap, remaining)` 同时传给 **`time_abort` 和
  `time_suffice`**；`iterations_abort`/`iterations_suffice` 也要设同类
  上限。只设 `time_abort` 不够：Ojalgo 找到第一个可行解后改用
  `time_suffice`（默认很长）决定是否继续搜索。剩余预算不足或任一阶段
  未 `isOptimal()` → 整体 blocked（`solver_timeout`）。Ojalgo 不支持
  热启动，阶段之间是重新分支定界。
- 每阶段共用同一 `ExpressionsBasedModel`，只追加约束/改目标权重，不重建
  变量。**必须把上一阶段的目标表达式 `weight(0)`**，否则旧目标会累加
  （已用 Ojalgo 48.4.2 小程序验证：追加约束后可重解，但旧 weight 不清零
  会保留）。
- 阶段判定用 `solved.getState().isOptimal()`：它同时接受 `OPTIMAL` 与
  `DISTINCT`；`FEASIBLE`/`APPROXIMATE`/超时一律视为未证明 → 整体
  blocked，不返回“阶段 1 最优、阶段 3 启发”的混合解。
- `GENERATE`/`ADD`/`REFILL` 跳过不适用阶段；`ADD`/`REFILL` 的 churn 由
  零删除硬策略固定为 0，P2 只剩 tierAnchor。
- 若基准测试证明三/四阶段 p95 超过预算，退化为**两阶段**：
  P1 safety 与 P2 合并（safety 权重 > max churn+tier 总贡献），
  P2 utility/diversity/stable；这是性能兜底，不是默认；合并会改变
  字典序语义，必须 bump 目标版本并整批回归。

### 4.3 结构偏差

```
tierDeviation = Σ_t |count_t - anchor_t|        // t ∈ {sprint,stable,protect}
localProtectCount = Σ x_i  where fact_i.tier == "protect"   // canonical key
                    and sameProvince(fact_i.provinceName, sourceProvince)
safetyDeficit = max(0, minLocalProtect - localProtectCount)

P1: minimize safetyDeficit
P2: minimize Wchurn * Σ removed + tierDeviation
    Wchurn = maxTierDeviation + 1
    maxTierDeviation = targetCount + anchorSum
    // L1 distance between count vector (sum=T) and anchor (sum=anchorSum)
    // is at most T + anchorSum；用 3T 在 anchorSum>2T 时会低估
```

- `safetyDeficit` 是整数变量 `0..minLocalProtect`；`localProtectCount`
  只数“保”档且生源省匹配的实体（unit 模式按 unit 数，volunteer 模式按
  item 数），与 `reviewSafetyGuard` 完全同口径（省份匹配沿用其
  `containsIgnoreCase`，不是严格相等）。`anchor_t` 为 null 的档位
  不加偏差项。
- `anchorSum` 可能不等于 `targetCount`：`requiredTierCounts` 按档位各自
  round 且 `max(1)`，缩放后总和可能大于/小于目标。`Wchurn` 用实际
  `anchorSum` 推导并断言 `Wchurn > maxTierDeviation = targetCount + anchorSum`；
  不能假设 3:3:4，也不能用 `3*targetCount`（anchorSum>2T 时低估）。
  输入校验：`targetCount <= n`、每个 anchor_t 在 `[0, n]`、
  `coverage.minCount <= targetCount`；越界 → `solver_input_invalid`
  或 `anchor_invalid`，不进入权重计算（防止异常值把 `Wchurn` 推到溢出）。
- `minLocalProtect` 的 `not_applicable`：若已确认的
  `mustExcludeRegions` 明确命中生源省，返回 `not_applicable`，L1 跳过并报
  `safety_floor_not_applicable`。**这需要 J5.4 同步 review 的
  `safety_guard` probe**；J5.3 默认关闭该分支
  （`safetyFloorNotApplicableEnabled=false`），在 J5.4 完成前仍按 review
  现有口径计算，避免“solver 认为不适用、review 仍硬失败”的双口径。
  此条列入 Q13。
  （`mustIncludeRegions` 的 only-keep 语义当前不存在，不纳入判断，
  避免凭空解释范围约束。）

- `anchor` 的优先级（推荐，S3 生效）：
  1. 显式 `tierAllocationConstraint` 的解析值（`TierAllocationResolution`）；
  2. 候选池 `requiredTierCounts` 按 `selectionTargetCount/requiredCount`
     等比缩放（与 review `expectedTierCount` 同口径）；
  3. 当前方案档位分布投影（现有 `TierStructureProjection.project`）。
- **S1 兼容期**保持现状：只有显式 tier 约束时才有 anchor，优先保证
  行为不漂移；S3 再切到 1/2/3 的统一口径，且必须过 J5.4 前置
  （review `ratio_distribution` 读同一目标）。
- `minLocalProtect`：`userScore == null || userScore < 580` 且生源省已知 → 2；
  `userScore >= 580` → 0；生源省缺失 → 0 + `safety_floor_unknown` 诊断。
  **不能写成 `userScore < 580`**：review 对 `userScore=null` 仍执行本省保底
  校验（`reviewSafetyGuard`，`PlanningStateService.java:11203-11265`）。
  该规则抽到 `SafetyFloorSupport`，review 与 solver 共用，禁止两处各写一份。
- `group_inner_safety_guard`（组内安全垫）本阶段**不进 solver**；它依赖
  单元内专业构成，属于 J5.4/J5.5 的组内选择问题，避免 J5.3 目标膨胀。

### 4.4 软效用

`CandidateUtilityScorer` 按快照一次性计算，不在 solver 里现算：

| 分量 | 来源 | 默认权重（内部） | 缺失处理 |
|---|---|---|---|
| preference | `intentScore` 的 snapshot 分位 | 40 | **0（保守）** |
| quality | `finalScore` 的 snapshot 分位 | 25 | **0** |
| safety | `admissionRatio` 在**同档位内**的分位 | 20 | **0** |
| future | `futureDevelopmentScore` 分位 | 10 | **0** |
| cost | `1 - min(tuition, 100000)/100000` | 5 | **0（未知学费不当作便宜）** |

- `utilityScore = round(Σ weight_i * component_i / 100)`，范围 0..100，
  **整数**；归一化用确定性分位（并列取平均秩），不使用浮点排序。
- **缺失值取 0，不取中性 50**：评审构造过“已知质量 40 的候选输给
  只有 preference、质量未知按 50 算的候选”，中性值会系统性奖励
  数据缺失。缺失即低分是保守选择，`utilityCoverage` 只作诊断/解释，
  不作为额外加分项；数据补齐后自然回升。
- `utilityCoverage < 60` 的候选标 `utility_data_gap`，在诊断中计数；
  仍允许参与选择，但不会因“缺数据”获得优势。
- `safety` 用同档位分位，避免 solver 把“冲”都换成高录取率候选而
  变相改变档位语义；档位数量本身由硬约束控制。
- 风险标记（中外合作/专项/限报/单科）**不进 utility**：它们是资格或
  审查问题，不能用一个软分抵消。`high_tuition` 只通过 cost 分量体现。
- 权重/分位算法变化 → bump `utilityModelVersion`，旧快照/缓存失效。

### 4.5 多样性（默认关闭）

- `DiversityPolicy.mode=off` 时不建任何变量/约束，行为与未加该字段一致。
- `mode=soft` 时，对每个分组 g（省/专业类/院校层次）引入
  `excess_g >= count_g - cap_g`，`excess_g >= 0`，目标最小化 `Σ excess_g`。
  `cap_g = max(1, ceil(share * targetCount))`，region/major_category
  默认 0.4，school_level 默认 0.6；分组数上限 32，超过按
  `(candidateCount ↓, key ↑)` 截断并报 `diversity_group_truncated`。
- 位置：在 utility **之后**。理由：多样性是“别太集中”的次级偏好；
  用户真正要求“至少覆盖 N 个城市/专业类”时应编译成 coverage 硬约束，
  而不是靠软惩罚。若评审要求“用户明确说多样性时优先于 utility”，
  则把 diversity 层移到 utility 之前（L4→L5 对调），并 bump 目标版本。
- 软惩罚永不导致不可行；所有 cap 都是可欠账的。

### 4.6 稳定性与数值分离

- 稳定序权重为 1；**要求 stableOrder 在快照内唯一且 `0..n-1`**，
  `maxStableTotal = n * (n-1)`（n ≤ 600 → 359,400）。不唯一 →
  `candidate_fact_invalid`（现有 solver 只查非负，不查重复）。
- P3 只放 utility 与 stable：`wUtility = maxStableTotal + 1`。utility 总分
  最大 `n*100`，P3 目标量级 ≤ `n*100*wUtility ≈ 2.2e10`，与现有 1e12
  相比更安全。
- P4（可选）只放 diversity 与 stable：`wDiversity = maxStableTotal + 1`；
  每个实体最多命中 `maxGroups` 个分组，但 P4 不与 utility 同目标，
  量级 ≤ `n*32*wDiversity ≈ 6.9e9`，仍在安全范围。
- **不要把 diversity 与 utility 塞进同一加权阶段**：多分组会让
  “一层压一层”的权重迅速到 1e14，既难解释也逼近数值容差。
- 阶段固定表达式用上阶段的最优值；maximization 阶段记录负目标值，
  固定时用同一表达式的 `upper(optimum)`（等价于 utility ≥ -optimum）。
- **stableOrder 的生成**：必须由包含 `entityId` 的总比较器一次性分配
  （`intentScore ↓ → finalScore ↓ → admissionRatio ↓ → schoolRank ↑ →
  entityId ↑`，兼容期按路径），不是只在 solver 入口校验唯一性；
  分配后断言唯一且 `0..n-1`。
- **稳定性契约（S1 前必须二选一写死）**：
  - **A. 严格字典序 canonicalization**：最后一阶段后，在所有最优解中
    按 `(stableOrder 向量, entityId)` 再选。实现成本高（逐位固定/多次
    可行性判定），J5.3 **不承诺**。
  - **B. 固定部署内确定性（J5.3 选择）**：同一
    `solverVersion + Ojalgo/JVM 配置 + snapshot digest` 下，selected/
    ordered 必须一致；通过固定单线程 Ojalgo 环境（限制
    `OjAlgoUtils.ENVIRONMENT`）+ 唯一 stableOrder 实现，并做 5 次重复
    测试。**跨部署/跨机器不承诺同解**：用户确认的预览由冻结回放保证
    不变；新预览允许不同，但必须过 golden 与目标层值对比。
  - `Σ stableOrder` 只是**标量平局**，不是 `(stableOrder, entityId)` 的
    完整字典序；两个不同子集可能同和。文档与回执不得宣称“完整
    字典序最优”。若产品后续要求严格字典序，另立 A 的实现里程碑。
  - 结果 trace 记录 `determinismMode=single_thread_v1` 与
    `environmentId`，方便复现。
- 候选排序/集合遍历一律用 `(stableOrder, entityId)` 全序；Map 用
  `LinkedHashMap`；禁止依赖 `HashMap` 迭代顺序。
- 时间中止不参与“确定性”口径（中止即失败）。

### 4.7 复杂度与候选帽

保留硬帽：`MAX_CANDIDATES=600`、`MAX_COVERAGE_CONSTRAINTS=64`、
`TIME_ABORT_MS=2000`、`ITERATION_ABORT=100000`。新增：

```
CandidatePoolReducer.reduce(facts, objectiveSet, policy, cap=600)
  0) 必保核心 mandatory:
       locked || pinned || forcedRequired || forcedAdd
       || (lockExisting && current && 不在 removable/forcedRemove)
       || forcedRemove（为 cap 保留变量，不要求被选中）
     （这些不是“建议保护”，而是动作/锁定语义要求，不能裁掉；
       未被锁定的 current 若动作允许删除，不强行占核心预算）
  1) witness（best effort）:
     用全量池按“mandatory → 覆盖缺口 → tier 下限 → 安全缺口 →
     目标数”做确定性贪心，得到一个**满足全部硬约束/policy** 的可行
     选择 W；W 必须包含 mandatory，且 `|W| <= cap`，否则视为构造
     失败（**不能把 W 截断后仍叫 witness**）。若 W 存在，
     mandatory = mandatory ∪ W（此时 |mandatory| <= |W| <= cap）。
  2) 若 |mandatory| > cap（只会在 witness 不存在且 current/locked/
     pinned/forcedRequired 本身超帽时发生）：
       blocked(candidate_cap_core_over_limit)，
       诊断附 locked/current/pinned/required 的规模与
       `witnessAvailable`；**不报 candidate_cap_infeasible**
       （不能把帽的核心预算不足说成原问题无解）。
       若 witness 存在却出现 |mandatory|>cap，说明构造违反
       `|W|<=cap`/包含 mandatory 的约束 → `solver_witness_broken`。
  3) budget = cap - |mandatory|。
  4) 可选保护（只花 budget，不再各自独立全量保护）：
     - safety 缺口代表（优先）
     - 未被 W 覆盖的 coverage 缺口代表
     - 未被 W 满足的 tier 下限/锚代表
     - 排序按（边际覆盖/档位收益 ↓, utility ↓, stableOrder ↑）
     直到 budget 用尽。未放下的代表只记
     `protection_budget_truncated`，**不 block**——W 已保证硬可行。
  5) 剩余预算按 (utility ↓, stableOrder ↑) 填满。
  6) 校验 entityId 非空且唯一、stableOrder 唯一；重复/空 →
     blocked(candidate_fact_invalid)，**不静默去重**（去重会掩盖
     unit/volunteer 混用或重复加入的 bug）；按 (stableOrder, entityId) 排序
  7) 对缩减集跑 precheckObjectiveCapacity；precheck 的 available 计数
     必须排除 tier upper=0 / ineligible 的候选。
  8) 若不可行且原始池 > cap：在同一 cap 内分环替换尾部候选
     （每环 cap/4，从未入选候选补入、从低 utility 尾部移出），最多 3 环。
     **不把规模扩到 cap 外**——solver 硬帽仍是 600，扩到 1200 会直接
     `solver_complexity_limit`。
     3 环后仍不可行：
       - witness 存在 → `solver_witness_broken`（内部错误，不应发生；
         mandatory 含 W，缩减集至少有一个可行解）
       - witness 不存在 → `solver_infeasible_after_cap`，**不报
         `candidate_shortage`**：无法区分“全池也不可行”与“帽把可行解
         排除了”
```

规则：

- **witness 先行**：只要 W 存在且放得进 cap，缩减集就保留一个可行解；
  独立 bucket 的 top-N 只能竞争剩余预算，不能把 W 挤掉。这样
  “重叠 coverage + 可行 witness + 各自 top-N 并集 > 600”不会误报
  `candidate_cap_infeasible`，而是 `protection_budget_truncated` +
  `capLimited=true`。

- 截断对所有路径生效（initial/fill/add/scope/refill/enforceSelection），
  不再只有 fill 截。
- **帽是启发式，不承诺全局最优**：若 `droppedCount > 0`，结果标
  `capLimited=true`/`globalOptimal=false`；影子与回执不得宣称“最优”。
  witness 只保证“缩减集至少有一个可行解”，不保证它等于全量池最优。
- 诊断字段（内部/预览诊断，不直接展示给用户）：
  `candidateCountOriginal`、`candidateCountSolved`、`droppedCount`、
  `coveragePreserved`、`candidateCapApplied`、`witnessAvailable`、
  `witnessSize`、`mandatorySize`、`optionalBudget`、
  `protectionBudgetTruncated`。
- 截断后 solver 若报不可行（非 precheck 能发现的联合约束冲突），
  同样走一次“帽内分环替换”；不允许直接把“截断导致的不可行”说成
  “候选不足”。
- `candidate_shortage` 的“可用数”口径继续用截断前全量池，避免把帽值
  当可用数（沿用现有 fill 的诊断约定）。
- 10041983 32MB 池：
  - 若 mandatory/witness 本身超 600 → `candidate_cap_core_over_limit`
    （附 locked/current/required/witness 规模）；
  - 若 witness 不存在且缩减集仍不可行 → `solver_infeasible_after_cap`；
  - 不静默丢候选后说“无解”，也不把保护预算不足说成原问题不可行。

---

## 5. 动作统一

`SelectionSolver.select(PlanCommand)` 是唯一选择入口。各动作只提供
`MutationPolicy` 与 objective delta：

| 动作 | 当前方案 | 允许删除 | 允许新增 | 目标数量 | churn 层 |
|---|---|---|---|---|---|
| GENERATE | 空 | n/a | 是 | 已确认 target 或池 requiredCount | 跳过 |
| FILL | 保留合规项 | 仅不满足新硬要求的项（调用方预过滤） | 是 | targetCount | 启用 |
| ADD | 保留 | **否**（硬） | 是（含 frozenRequired） | current + added 或显式 override | 跳过（0） |
| REPLACE | 保留未换项 | 仅 frozenRemove | **仅 frozenAdd（J4a 冻结）** | 不变 | 仅校验，不由 solver 改选 |
| REFILL | 保留 | **否**（硬） | 是 | requiredCount / target | 跳过（0） |
| SCOPE | 保留 | 仅范围违规项或按 strategy | 是 | targetCount | 启用 |
| REVIEW_FIX | 保留 | 按 fix 策略 | 是 | 按 fix | 按策略 |

关键约束：

- `ADD/REFILL` 的“零删除”必须落成 `upper/lower` 硬约束，不能只靠
  churn 权重；否则权重退化时会偷偷删条目。
- `FILL` 的保留项同样要硬锁：不在 `removableEntityIds` 里的 current
  一律 `lower(1)`；不能把“保留”交给 churn 软目标（否则新 tier/safety
  目标可以把合规旧项换掉）。
- **`REPLACE` 的换入/换出都已在 J4a 冻结**（`addedVolunteerIds`/
  `removedVolunteerIds`，`PendingPlanningCommandBizService` 只认冻结
  命令）。J5.3 不让 solver 改选换入集合：REPLACE 只做“冻结集合的
  可行性/顺序/后置校验”，或把 solver 结果与冻结集合比对，不一致直接
  409。若将来要让 solver 决定换入，必须先改 J4a 的冻结/确认契约，
  不能只改 solver。
- `ADD` 在单元模式下如果只是往已有组里加专业，**不是新的选择实体**：
  会出现 retained+available 同一个 `entityId`，触发
  `candidate_fact_invalid`（现有 solver 已拒绝重复 entityId）。
  这类操作要么走“组内专业补齐”的专门路径，要么在 compiler 层直接
  拒绝；J5.3 不通过 solver 伪造 unit 增补。
- `ADD` 遇到显式精确档位（如 3:3:4）时，目标数增加会改变配额；
  `TierAllocationSupport.compile` 可能在进入 solver 前就抛错。
  compiler 必须显式二选一：按新目标重解配额（并标记
  `tier_quota_rescaled`）或 blocked（`tier_quota_add_conflict`）；
  不能声称“solver 会处理”。
- `ADD` 的 `targetCountOverride` 必须 `>= current + added`（或由
  compiler 明确改写为增长后的目标）；小于该值 → 编译期
  `target_count_override_invalid`，不允许 solver 在“装不下”的目标下
  静默删旧项。
- **单元模式的 REPLACE/加专业**：J4a 冻结的是 volunteer 级
  added/removed 集合，而 solver 的 entity 是 unit；两者不能直接互换。
  J5.3 对单元模式 REPLACE 只做冻结集合的原子校验/顺序，不把
  volunteer 级集合硬套成 unit 级选择；“向已有组加专业”继续走 J4a
  路径，不由 solver 选择。若将来要统一，先扩 J4a 的冻结契约，不能
  在 compiler 里一刀切拒绝而回归既有能力。
- **pinned/unpin**：`pinned` 默认视为硬保留；若用户显式取消
  pin，必须在进入 compiler 前把该实体从 `pinned` 集合移除
  （`unpinEntityIds` 或 updated ordered plan），否则 solver 会继续
  当它不可删。J5.3 不新增外部 pin 动作，只尊重现有内部标记。
- `REMOVE`/`MOVE` 不走选择求解（只走排序/后置），但可以复用同一
  `inputDigest`/冻结校验框架。MOVE 的结果不能被后续重排静默覆盖：
  若同一回合还需重排，必须先应用 move 再排序，并把 move 作为后置
  事实校验。
- **显式“重新生成/整体优化”**必须用 GENERATE（current 视为空）或
  `countAsChurn=false`；不能一边声称重新生成、一边用 churn 锁住旧方案。
  哪些动作属于这一类由 compiler 的 action 决定，不能由模型自由发挥。
- 所有动作的结果都进入同一 `UnifiedPlanPostconditionValidator`
  （J5.4）；J5.3 不新增第二套后置。
- **priority（同档优先）在 J5.3 仍是“排序目标”，不是选择目标**：
  solver 只保证 `priorityMatched` 参与 within-tier 重排与后置；
  是否让“优先北京/优先计算机”直接影响选择，放 J5.4 决定
  （Q12）。这样 J5.3 不改变现有“优先只影响顺序”的行为，避免
  选择集与回执语义同时漂移。

---

## 6. 迁移阶段

### S0a：快照与影子（明确“不改行为”）

- 落 `CandidateSnapshotBuilder`/`CandidateFact`/`CandidateUtilityScorer`；
  资格必须复用 `RepairCandidateEligibility`、
  `RepairCandidateSelector.isCompensationSafeCandidate`（fill/scope）以及
  单元模式 `allMatch` 语义，不能只做“硬约束 + 学费”。
- 保留现有 `PlanSolverInputDTO` 适配器，新 solver 可读取 snapshot；
- 新增 `SolverGoldenShadowTest`：同一快照上跑旧 solver 与新 solver，
  只记录差异，不切流；**仓库内放可提交的小型确定性 fixture**（脱敏
  state/pool/objective/expected selection），不依赖外部 32MB 文件；
  大池走夜间/环境变量任务，报告带 checksum；
- 冻结 I/O 对比不能包含 `durationMs`；其余 selected/ordered/digest/
  diagnostics 逐字比较；
- 求解在写事务/行锁之外完成的设计先落到 shadow 路径：预览阶段算
  solver，写路径继续走旧逻辑；不在本阶段改 apply。

**S0a 退出条件**：8 个 J5.0 golden + 10041983 大池全部可跑；差异报告
逐条可解释；至少 6 个仓库内小 fixture 覆盖 fill/initial/add/scope/
refill/replace；**旧 apply 行为逐字不变**（flag off 回归，比较时排除
durationMs）。本阶段可以宣称“不改行为”。

### S0b：冻结写链迁移（行为变更，独立验收）

- **锁定/保留项硬约束先落地**：`lockExisting`、`removableEntityIds`、
  `forcedAdd/Remove` 变成变量上下界；不再用 churn 权重表达“零删除”；
- **FILL/PRIORITIZE 冻结补强**：pending 存完整回放负载与
  selected/ordered；apply 读 claimed pending 回放，不重新求解（见 §3.4）；
- **摘要改 selection-scoped**：预览/apply 用同一 builder 重建；新增
  未选中候选不失效，选中事实变化才 409；apply 后必须过统一后置；
- 求解在写事务/行锁之外完成：预览阶段算 solver，apply 只用冻结结果；
  避免 2s 求解期间持锁。

**S0b 验收口径**：不是“旧 apply 逐字不变”，而是
**“预览选择的 selected/ordered/digest == apply 回放结果”**；
预览→确认→执行在真栈单独验收（含候选刷新、并发写、后置失败回滚）。
S0b 是行为变更，不能和 S0a 的“不改行为”共用同一个退出条件。

**S1 前置**：S0a + S0b 都通过；未通过不开放 solver 切流 flag。

### S1：fill 路径切流（第一批）

- `fill_to_count` 改用新 solver（safety→churn/tier→utility + 统一截断；
  diversity 默认 off）；
- 旧 `capSolverCandidatePool` 保留为 flag-off 回退；
- 灰度：`solver.v2.paths=fill`；
- 验收：结构指标不劣于基线、质量均值不低、churn 不增、确定性不变；
  `safety_guard` 硬失败不得比基线增多（safety 已提到 churn 前）。
- **首验（2026-10-18，flag 临时开启）**：900040 覆盖预览
  `fill 80 + 浙江≥3` 走 staged solver（`ojalgo-48.4.2-j53-shadow`），
  输出 80 组、移除 1 组、新增 1 组；900045 覆盖预览/apply 44/44
  完全一致，验收后已恢复 version 14/44；900040 fill 80→85
  preview/apply 85/85 完全一致，验收后已恢复 version 5/80。
  **尚未常开，默认仍走旧 solver。**
- **第四轮复审修复（2026-10-18 晚）**：
  - 精确配额 objectiveType 必须报 `tier_exact`（与后置校验同口径）；
  - staged 快照池截到 capped eligible + retained，避免与 additions 映射不同源；
  - snapshot 只包含 apply 可解析的 available（initial 路径加
    `requireCompensationSafe` 并把 banned 标为不合格）；
  - reducer 保留全部 current 行（不强制选中），remove 名单按原始快照计算；
  - `enrichV2` 前对 objectiveSet 做 JSON 深拷贝，避免污染
    `TierAllocationResolutionDTO.objectiveDigest/solverVersion`；
  - freeze 预览摘要先刷新 overlay，且不再 hash `admissionRatio`。
  - 真栈：900045 staged fill + freeze 42→44（remove 4/add 6）apply
    后置通过；范围类提案无 canonical 元数据也能冻结回放；
    改请求 → 409 `user_goal_request_changed`。

### S2：initial/enforceSelection 切流

- `CanonicalPlanningRuntime.enforceSelection` 改读 snapshot + 新 solver；
  统一截断，解决大池直接 blocked；
- 结构目标切换到 `requiredTierCounts` 缩放口径前，先完成 J5.4 前置
  （review `ratio_distribution` 同源），否则保持旧 anchor；
- 验收：900040/900045/900016 等真栈回归；大池不再 `solver_complexity_limit`。
- **首验（2026-10-18，flag 临时开启）**：`solver.v2.paths=initial` 下
  900040 `forceRegenerate` 走 staged，输出 80 组，与切换前 selected/
  ordered 完全一致（set/order 都相同），验收后已恢复 version 5/80。
  **尚未常开，默认仍走旧 solver。**
- **第四轮复审修复（2026-10-18 晚）**：initial staged 快照改用
  `candidateFacts` 并与 `availableEntities` 同源（compensation-safe /
  banned 过滤）；`resolvedSelectionTarget` 补 null guard；
  reducer 保留 current 行，候选帽下不再漏报 remove。

### S3：scope/add/refill 切流

- scope：范围 delta 编成 hard/coverage；保留项与删除策略走 policy；
- add：`frozenRequired` lower=1 + 零删除；去掉“有 tierQuota 一律 blocked”
  的旧能力缺口（由 solver 判可行/不可行）；但精确档位下目标数增长必须
  先显式重解配额或 blocked（`tier_quota_add_conflict`），不能进 solver
  才抛错；单元模式“向已有组加专业”走专门路径或拒绝，不能产生重复
  `entityId`；
- refill：只补不删，目标/档位/覆盖走同一 compiler；
- 每个路径单独 flag，单独 golden，不允许一次性全切。
- **add/remove/replace 首验（2026-10-18，flag 临时开启）**：
  - add：900040 80→81，81 selected、0 remove、1 add，ready；
  - remove：900040 80→79，79 selected、1 remove、0 add，ready；
  - replace：900040 80→80，1 remove、1 add，ready。
  均未落盘，验收后路径已关。
- **refill/scope 代码已接**：refill 用 `REFILL` + lockExisting + 只追加，
  目标为每档 `max(当前,池目标)`；scope 的 `add_units_by_scope` 复用
  `dryRunAddUnits`，`solver.v2.paths=scope`。真栈 add-by-scope
  900040 80→82 ready（2 个新增）；refill 真栈待有缺口的会话。
- FILL/SCOPE staged 路径启用 `requireCompensationSafe`；单元档位冲突在
  `CandidateSnapshotBuilder` 直接 409 `tier_fact_conflict`。
- **S0b 冻结链第四轮复审修复（2026-10-18 晚）**：范围类提案优先回放
  pending 里的 `frozenProposal`（不再要求 canonical 三件套）；preview 额外
  冻结 `frozenRequestDigest`，apply 校验请求未被替换；`FrozenSelectionGuard`
  继续校验选中实体仍在/仍合格。

### S4：清理

- 删除/降级旧 fill 截断、独立 dry-run 选择、重复过滤（保留显式 fallback）；
- **legacy apply 清理**（freeze flag 全量开启并通过真栈验收后）：
  - 删除 user-goal “重新生成再应用”回退；
  - 删除 `isLegacyCanonicalProposal`/无 canonical 元数据的兼容分支；
  - `solverVersion` 精确相等改为 `hardObjectiveVersion` major + digest；
  - 删除旧 `OjalgoDeterministicPlanSolver` 与旧 `capSolverCandidatePool`；
- `hasSelectionObjectives` 的 gate 改为“有目标或有政策要求”；
  GENERATE 在无显式目标时也可跑结构/效用（需产品确认，见 §9-Q8）；
- 旧 solver 在 S1–S3 期间保留，flag 可回退；S4 才删除。

---

## 7. 测试与验收

### 7.1 单元/契约

- 层序：构造“零改动但零本省保底”vs“换 1 条即可过 safety”的方案，
  断言 safety 胜；再断言“少改但档位锚略差”胜“多改但锚完美”；
  “锚略差但效用高”胜“锚完美但效用低”；锁定/冻结项永远选中；
  不合格项永远不选。
- `mip_gap=0` 回归：构造真实最优与间隙最优差 1 的用例，断言
  阶段 optimum 取整后与穷举/小规模精确解一致；`FEASIBLE` 不得被
  当成 `OPTIMAL`。
- 阶段固定：P3 的 `fix_utility` 只含 utility 系数，不得把 stable
  一起钉死；构造“utility 相同、stable 与 diversity 冲突”的用例，
  断言 diversity 能交换 stable。
- 超时：只设 `time_abort` 的旧路径不得通过；每阶段必须同时设
  `time_suffice`/`iterations_suffice`，全局预算耗尽即 blocked。
- 确定性：600/64 规模在**固定部署环境**连续 5 次，selected/ordered/
  digest 相同；跨环境不作为 exact-set 门槛，只比较目标层值与
  StructureVector。若固定环境仍漂移，按 §4.6 契约 B 降级/固定单线程
  后再跑；不通过不得进入 S1。
- 动作策略：ADD/REFILL 零删除；FILL 未列入 `removableEntityIds` 的
  current 永远保留；REPLACE 的换入/换出都与 J4a 冻结集合一致；
  GENERATE 无 churn；精确档位 ADD 要么重解配额要么显式 blocked。
- 单元模式：同一 unit 内 tier 必须一致，unit tier 取法与
  `CanonicalPlanningRuntime.Entity.tier()`/`FillOption.representative`
  同源；往已有组加专业不得产生重复 entityId。
- 结构：`safetyDeficit` 先于 churn、churn 先于 tierAnchor；
  `userScore=null` 按 at-risk 处理；`score>=580` 时 floor=0 但
  `ratio_distribution`/组内安全仍由 review 独立判断；
  `not_applicable`（明确排除本省）需与 review 口径一致（J5.4）。
- 效用：分位/缺失值=0/权重版本；同一 snapshot 的 utility 分值稳定；
  已知低质量候选不得输给“质量缺失按中性算”的候选；
  `utility_data_gap` 计数正确。
- 多样性：off 时无变量；soft 时只惩罚超 cap；不可导致 blocked；
  utility 最优集合固定后再优化 diversity。
- 截断：witness 可行时缩减集必可行；mandatory/witness 不得被可选
  bucket 挤掉；**重叠 coverage + 可行 witness + 独立 top-N 并集 > 600**
  的用例断言 `protection_budget_truncated`/`capLimited`，而不是
  `candidate_cap_infeasible`；帽内替换确定；`capLimited/globalOptimal`
  标志正确；`candidate_cap_core_over_limit` 与
  `solver_infeasible_after_cap` 诊断区分正确。
- 确定性：同一部署环境、同一输入 5 次 selected/ordered/digest 相同；
  跨环境只比较层值与结构向量；stableOrder 重复/缺失直接
  `candidate_fact_invalid`；`Σ stableOrder` 不被断言为完整字典序。
- 冻结：selection-scoped digest 在“仅新增未选中候选”时不变；
  选中事实变化 → `solver_input_stale`；一致 → 按冻结选择执行；
  apply 后统一后置失败必须整笔回滚。
- 序列化：agent/WS/前端 payload 不含 utility/权重/分量（契约测试 +
  grep 白名单）。

### 7.2 Golden / 影子

沿用 J5.0 的 8 个会话与 10041983 32MB 池：

- 10041984（恢复态/缩水态）、900040、10041981、900038、900028、900018、
  10041983、900047（无审查，跳过 diff 但可跑 solver）；
- 每个会话输出：旧/新 selected digest、churn、StructureVector、
  utility 均值/中位、耗时、诊断；
- 门槛：
  - 硬约束回归 = 0（数量/覆盖/档位/锁定/零删除）；
  - `safety_guard` 硬失败数不得高于基线；`ADD/REFILL` churn = 0；
  - 结构向量不得系统性变差；每个变差样本必须逐条解释并被评审接受；
  - 大池不得再因 600 帽直接 blocked（要么求解，要么
    `candidate_cap_core_over_limit` / `solver_infeasible_after_cap`
    且有可解释诊断；不得把保护预算不足误报成原问题无解）。

### 7.3 性能

- 现有 ADR benchmark 扩展为 J5.3 用例：400/600 候选、16/32/64 覆盖、
  含 utility/diversity 变量；
- 指标：P50/P95/max、solverState、iterations；目标 P95 ≤ 1.5s、
  max ≤ 2s（单次请求含 safety/churn+tier/utility 三阶段，diversity off）；
  现有 400 候选/20 约束单次约 146ms，三阶段加效用变量后的第一道门槛是
  “≤3× 单阶段 + 30%”；diversity 开启时另测四阶段。
- **本地首测（2026-10-18）**：600 候选 / 80 目标 / coverage + tier +
  safety，三阶段 OPTIMAL，耗时约 **472ms**（`StagedSolverPerformanceTest`）；
  仍低于 2s 预算，但需补 600/64 覆盖与 diversity 场景。
- 若超预算，按 §4.2 退化为两阶段并重新跑 golden（会改变目标语义，
  必须按新 `hardObjectiveVersion` 整批验收）；
- 记录 10041983 大池的截断前后耗时/候选数。

### 7.4 真栈验收（切流后）

- fill：900045/900040 等会话补齐，结构/数量/审查重跑一致；
- initial：大池会话不再 complexity block；
- scope：范围应用后重生成不被撤销；
- add：有 tierQuota 时不再一律 blocked，solver 给可行/不可行诊断；
- 回执不含权重/效用数字；预览→确认→执行 digest 一致；
- 回滚：flag off 后同一请求结果与切流前逐字一致（golden 对比）。

---

## 8. 上线与回滚

- 配置（示例名，落地时以现有配置框架为准）：
  - `solver.v2.shadow=true|false`
  - `solver.v2.paths=fill|initial|scope|add|refill`（逗号列表）
  - `solver.v2.diversity=false`
  - `solver.v2.deadlineMs=2000`
- 影子模式：新旧都算，返回旧结果；只在日志/指标里记录差异，不影响用户。
  按 `solver.v2.shadowSampleRate` 采样（默认 0，灰度期 5%–10%），
  避免每次请求都多跑 3–4 次 ILP 把延迟/CPU 翻倍；大池会话优先采样。
- 切流模式：按路径逐个开启；每开一个路径，先跑该路径 golden + 真栈
  小流量，再全量。**Q13（排除本省 safety）与 Q14（单元模式加专业）
  未拍板前，不开放 initial/scope/add 的相关 solver flag**；对应路径
  继续走旧逻辑。
- 回滚：关闭对应 path；旧 solver 代码与旧截断保留至少一个版本周期。
  现有 flag 是静态 `@Value`（如 `planning.candidate-pool.split.enabled`），
  没有 `@RefreshScope`，**回滚需要重启**；若要求热回滚，先引入配置中心/
  DB 开关，不把“重启”写成“即时”。
- 已冻结命令：记录 `solverVersion/hardObjectiveVersion/objectiveDigest/
  inputDigest`；flag 回退后仍按冻结选择执行，但 apply 时重建摘要。
  **版本比较用 `hardObjectiveVersion` 的 major 兼容 + digest**，不要
  对 `solverVersion` 做精确字符串相等（部署/回滚会把所有旧 pending 409）。
  摘要不一致才 409 要求重新预览（不允许执行“旧预览 + 新事实”）。
- 观测指标（内部）：
  `solver_v2_requests_total{path}`、`solver_v2_blocked_total{reason}`、
  `solver_v2_timeout_total`、`solver_v2_duration_ms`、
  `solver_shadow_diff_total`、`solver_shadow_hard_regression_total`
  （必须为 0）、`solver_cap_applied_total{dropped}`。

---

## 9. 待评审决策（需要明确拍板）

| ID | 问题 | 推荐 | 备选/影响 |
|---|---|---|---|
| Q1 | safety/churn/tierAnchor 的层序 | **safety → churn → tierAnchor**（safety 是 hard probe 底线；churn 只压档位锚） | churn 先于 safety：保留零保底旧方案，review 硬失败；不可接受 |
| Q2 | 三阶段精确 vs 两阶段加权 | **safety / churn+tier / utility 三阶段，diversity 另立 P4**；`mip_gap=0` | 两阶段：少一次求解，但会把 safety 或 tier 与 churn 揉在一起，语义不可审计 |
| Q3 | safetyFloor 软 vs 硬 | **软目标，但必须是 churn 之上的第一软层** + review 硬诊断 | 硬约束：候选不足会整单不可行；排在 churn 后：等于没修 |
| Q4 | 效用分量的默认权重/缺失值 | 40/25/20/10/5；**缺失=0**（保守） | 中性 50 会奖励缺数据；重归一化会让单分量候选虚高 |
| Q5 | 多样性默认与层序 | **默认 off；soft 在 utility 之后**；显式“不要超过 X%”另立 hard-cap schema | 用户明确要求“至少 N 个城市/专业类”编成 coverage；上限类要求 coverage 表达不了 |
| Q6 | 候选帽策略 | **mandatory + witness 先行，其余代表竞争剩余 budget + 帽内替换；帽改变最优时标 `capLimited`** | 2×cap 不可行（solver 硬帽 600）；独立 bucket top-N 并集可能误报无解 |
| Q7 | J5.1 是否硬前置 | **是**；最小切片先服务 fill，资格必须复用既有 predicate | 只做适配器：solver 仍读 `PlanSolverInputDTO`，无法真正用效用/资格原因 |
| Q8 | 无显式目标时是否跑 solver | **S4 再开**；S1-S3 保持 `hasSelectionObjectives` gate | 立即开：initial 无目标时也结构/效用最优，但行为漂移大；§5 的 GENERATE 以“有目标”为前提 |
| Q9 | 结构锚来源 | S1 旧口径；S3 切 `tierGoal > requiredTierCounts 缩放 > 历史投影` | 只保留历史投影：与 review 口径继续分叉；锚和可能不等于 targetCount |
| Q10 | 冻结摘要范围/不一致时 | **selection-scoped digest**；选中事实变化才 409 重新预览 | 整池 digest：正常 overlay 刷新会误杀 pending；仅告警会套旧选择到新事实 |
| Q11 | review hard finding 是否进 solver 硬约束 | **不进**；J5.3 只共用 safety floor 支持类 | 进：solver 与 review 强耦合；J5.3 不宣称“15 probe 全同源” |
| Q12 | 同档优先是否影响“选哪些” | **J5.3 不影响**（只排序）；J5.4 升级为选择目标 | 立即影响：更贴用户偏好，但选择集/回执/修复策略都要重新验收 |
| Q13 | 明确排除本省时 safety 怎么处理 | **not_applicable，但必须 J5.4 同步 review**；J5.4 前按 review 旧口径 | solver 单独 not_applicable 会造成“solver 放行、review 硬拦”双口径 |
| Q14 | 单元模式向已有组加专业 | **专门路径或 compiler 拒绝**；不进 solver 选择 | 进 solver 会产生重复 entityId / 组原子性破坏 |
| Q15 | 稳定性承诺 | **固定部署内确定（单线程 + 唯一 stableOrder）；跨部署不承诺** | 严格 `(stableOrder, entityId)` 字典序需逐位 canonicalization，另立里程碑；`Σ stableOrder` 只是标量平局 |

---

## 10. 风险

1. **效用不可解释**：用户看到方案变化但不知道为什么。缓解：回执只给
   “更匹配/更稳/更省”的定性原因 + affected refs；内部层值只进日志。
2. **数据缺失偏差**：缺失=0 会让数据不全的候选系统性吃亏。缓解：
   `utilityCoverage` 诊断 + golden 对比 + 数据补齐后重算；这是保守选择，
   比“中性 50 奖励缺失”可接受。
3. **多阶段超时**：600 候选 × 3–4 次 ILP；`time_abort` 是每阶段独立计时，
   不共享会到 6–8s。缓解：全局 2s deadline、每阶段传剩余预算、
   `isOptimal()`、失败 fail-closed；性能门禁。
4. **截断误杀/改变最优**：mandatory/witness 不足导致“假不可行”或选不到
   全量池最优。缓解：mandatory + witness 先行、其余代表竞争 budget、
   precheck 排除 tier 不可用候选、帽内替换、`capLimited` 明示；
   golden 覆盖大池；不宣称全局最优。
5. **目标漂移**：solver 与 review 对“保底/档位”口径不一致。缓解：
   `SafetyFloorSupport` 只统一 safety floor；J5.4 前不切结构锚；
   `not_applicable` 必须等 review 同步；golden diff 逐条解释。
6. **冻结摘要**：整池 digest 会误杀正常 pending；过松会套旧选择到新事实。
   缓解：selection-scoped digest + apply 后统一后置；新增未选中候选不失效。
7. **行为漂移**：safety→churn 会为了保底换条目。缓解：只换到
   `minLocalProtect` 为止；`not_applicable` 场景显式跳过；golden 对比
   churn 增量并逐条解释。
8. **冻结语义缺口**：FILL/PRIORITIZE 现在 apply 会重新求解，预览≠确认。
   缓解：S0b 把 selected/ordered 写进 pending 并回放；未完成前不宣称
   “预览即执行”。
9. **版本/回滚**：精确 `solverVersion` 相等会让部署期间的 pending 全 409；
   静态 flag 回滚需要重启。缓解：major 版本 + digest；回滚步骤写入 runbook。
10. **稳定性承诺被误读**：`Σ stableOrder` 不是完整字典序，跨部署也不
    保证同解。缓解：契约限定为“固定部署内 + 单线程 + 唯一 stableOrder”；
    pending 靠冻结回放；跨环境只比较目标层值/结构向量，不以 selected
    集合逐字相同作为验收。

---

## 11. 附录：与 J5.0/J5.2/J5.4 的边界

| 能力 | J5.0 | J5.2 | J5.3 | J5.4/J5.5 |
|---|---|---|---|---|
| `EvaluationContext`/`StructureVector` | ✅ 定义/影子 | ✅ 输出 | 读取结构指标做目标 | 持久化/同源 |
| `PlanEvaluation`/findings | ✅ 影子映射 | ✅ 运行时附加 | 不消费 findings | 审查切换/修复动作 |
| `CandidateSnapshot` | — | — | ✅ 最小切片 | 统一所有候选源 |
| 目标编译 | 硬目标 | hard/structure/soft 三层规划 | 扩展 Structure/Utility/Diversity/Mutation | review 与 solver 同源 |
| solver | 现状 | — | safety→churn/tier→utility（+diversity）字典序 | 后置统一 |
| `checks` 删除 | 审计 | 暂缓 | 不碰 | 三段迁移 |

**一句话**：J5.3 把“选哪些”从“约束满足 + 少改”升级为“硬可行 →
保底 → 少改 → 档位锚 → 更好 → 分散 → 稳定”的可审计搜索；它依赖
J5.1 的快照与 J5.2 的评价口径，但不重写审查、不改用户可见的权重叙事。
评审后保留的最大边界是：J5.3 只统一 safety floor 的**计算支持类**，
不宣称 15 个 probe 与 solver 全部同源；那属于 J5.4。
