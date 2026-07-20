# 志愿 Agent 4.1 M2 冲稳保目标实施计划

> **面向执行 Agent：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划；所有步骤使用复选框（`- [ ]`）跟踪状态。

**目标：** 在不削弱 4.0 精确数量行为、不提前开放 M3 组合的前提下，增加数量区间、仅上限、比例、历史 range patch、确定性结构保持、原子持久化和专用 postcondition。

**架构：** 保持唯一的 `PlanChangeSpec -> Proposal -> pending -> command` 链路。将请求增量、持久化有效目标、canonical solver bounds 和冻结解析结果拆成不同 typed DTO；所有 exact/range/ratio 输入统一经过 `TierAllocationSupport` 编译，由现有 ojAlgo runtime 求解，并且只持久化权威 Proposal 的结果。历史已确认目标继续作为硬约束；当前档位数量只在最小 churn 之后作为确定性的次级优化目标。

**技术栈：** Python 3.11、TypedDict/Pydantic AI、pytest、Java 8、Spring Boot、Lombok DTO、ojAlgo 48.4.2、JUnit 5、Mockito、Maven、JSON final-action fixtures。

---

## 事实源与执行规则

- 权威设计位于 `docs/release-4.1.0-zhiyuan-agent-implementation-plan.md` 的 5.2、5.3、5.3.1、6.2、6.4、7、9.3 和 10.3 节。本文只提供可执行的 M2 清单；设计变化和里程碑状态必须回写主计划。
- 本清单执行期间不得启动 M3-M7；所有未在本文明确开放的组合继续保留 `tier_quota_composite_not_supported`。
- 不得从 `raw_user_text` 恢复字段、增加中文话术路由规则、引入软偏好、增加旧 solver fallback、增加 feature flag 双执行、放宽超时，或重试完整 turn/case/package。
- 用户授权本次执行创建提交之前不得 commit。获得授权后，只能在下列检查点暂存对应的 M2 文件。
- 当前 worktree 已有 M0/M1 和用户改动；每次修改重叠文件前先读取 `git diff`，不得回退无关改动。

## 文件职责映射

**新增：**

- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierCountRangeDTO.java`：单个档位可空的 min/max 硬边界。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierCountsDTO.java`：冲、稳、保三个整数数量。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierWeightsDTO.java`：用户提交或 canonical 化后的比例权重。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierQuotaGoalRequestDTO.java`：包含 `updateMode` 的请求增量。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierAllocationConstraintDTO.java`：供 solver 消费的 canonical min/max 边界。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierAllocationResolutionDTO.java`：目标总数、有效边界、canonical 权重、解析数量、解析方法和 tie 顺序。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierQuotaChangeDTO.java`：Proposal 的 before/request/effective/resolution/state-diff 信封。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/TierAllocationSupport.java`：统一负责校验、patch/replace、比例解析、canonical 化、持久化、语义等价和旧 exact 读取。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/TierStructureProjection.java`：只作为 solver tie-break 基线的有界历史数量投影。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/UnifiedPlanPostconditionValidator.java`：从 command service 提取的统一方案/目标 postcondition 组件。
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/TierAllocationSupportTest.java`：typed 契约、合并、比例、持久化和旧状态测试。
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/TierStructureProjectionTest.java`：比例投影和确定性 tie 测试。
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/UnifiedPlanPostconditionValidatorTest.java`：exact/range/ratio、持久化和 frozen result 校验测试。
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandRollbackIntegrationTest.java`：opt-in 的真实事务回滚测试，不增加生产失败开关。
- `zhiyuan-agent/examples/dialog_regression_410_m2_tier_allocation_cases.json`：M2 真实 LLM preview/confirm/blocked 用例。
- `zhiyuan-agent/tests/unit/test_release_410_plan_change_contract.py`：持续演进的 4.1 PlanChangeSpec contract/golden/normalizer 对账。

**修改：**

- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierQuotaGoalDTO.java`：持久化的有效 exact/range/ratio 源目标，不包含请求 update mode。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/UserGoalFixProposalReq.java`：请求字段改用 `TierQuotaGoalRequestDTO`。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/HardPlanningObjectivesDTO.java`：保留旧 `tierQuotaGoal` JSON，并增加 `tierQuotaResolution`。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/CanonicalPlanningObjectiveSetDTO.java`：增加 canonical goal、bounds、resolution 和 state-changed 标记。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/FixProposalDTO.java`：增加权威 `tierQuotaChange`。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/PlanChangePostconditionReportDTO.java`：增加有效目标、bounds/resolved counts、实际数量、持久化和满足状态。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/PlanSolverResultDTO.java`：增加结构基线和实际 resolved tier counts，供 Proposal、digest 和 postcondition 复用。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningObjectiveCompiler.java`：把旧状态和请求增量编译为唯一 canonical allocation。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/OjalgoDeterministicPlanSolver.java`：增加 min/max 表达式、结构偏移目标、diagnostics 和 M2 solver version。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/CanonicalPlanningRuntime.java`：统一 exact/range/ratio 目标总数解析和冻结 apply 校验。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/UserGoalProposalBuilder.java`：展示 before/request/effective，区分纯目标更新与真正 no-change，并以选中结果生成 dry-run 数量。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java`：在现有事务中持久化权威有效目标和 resolution。
- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandBizService.java`：校验请求类型并执行通用 allocation postcondition。
- `zhiyuan-agent/app/zhiyuan_agent/tools.py`：扩展公开 schema、结构化归一、后端请求、冻结 pending 和 postcondition 投影。
- `zhiyuan-agent/app/zhiyuan_agent/prompt.py`：只描述稳定 schema 边界，不增加场景表或常驻 tier distribution。
- `zhiyuan-agent/examples/plan_change_spec_410_contract.py`：加入 update mode 和 canonical ratio 语义的 M2 reference contract。
- `zhiyuan-agent/examples/plan_change_spec_410_golden.json`：加入 M2 合法/非法契约用例。
- `zhiyuan-agent/examples/dialog_quality_gate.py`：注册新的 M2 final-action 包，不改冻结的 M0 manifest。
- `zhiyuan-agent/tests/unit/test_release_410_m0_contract.py`：只保留冻结的 M0 manifest、大 fixture 来源和 24/13 包步数对账，不再承担可演进 M2 contract 断言。
- `zhiyuan-agent/tests/unit/test_zhiyuan_agent_direct.py`：增加 range/ratio/pending/postcondition 测试。
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PlanningObjectiveCompilerTest.java`
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/OjalgoDeterministicPlanSolverTest.java`
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/UserGoalProposalBuilderTest.java`
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PlanningStateServiceTest.java`
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandBizServiceTest.java`
- `docs/release-4.1.0-zhiyuan-agent-implementation-plan.md`：记录 RED/GREEN/VERIFY/CLEAN 状态和证据。

**hard cut 后删除：**

- `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/TierQuotaSupport.java`
- `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/TierQuotaSupportTest.java`

### 任务 1：冻结请求、持久化、canonical 和解析结果类型

**文件：** 上述 DTO、compiler/support 文件，以及 `TierAllocationSupportTest.java`、`PlanningObjectiveCompilerTest.java`。

- [x] **步骤 1：编写失败的 DTO 和 compiler 测试**

在生产类型存在之前先增加以下具名用例：

```java
@Test
void shouldPatchOnlyExplicitRangeBoundsAndKeepHistoricalBounds() {
    PlanningStateDTO state = state("major", 12, 45);
    TierQuotaGoalDTO confirmed = ranges(bound(8, 12), bound(16, 20), bound(18, 22));
    state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(confirmed);
    TierQuotaGoalRequestDTO requestGoal = rangeRequest("patch", bound(null, 10), null, null);

    TierAllocationSupport.CompiledTierAllocation compiled =
            TierAllocationSupport.compile(state, requestGoal, 45);

    assertEquals(Integer.valueOf(8), compiled.getEffectiveSourceGoal().getSprint().getMinCount());
    assertEquals(Integer.valueOf(10), compiled.getEffectiveSourceGoal().getSprint().getMaxCount());
    assertEquals(Integer.valueOf(16), compiled.getEffectiveSourceGoal().getStable().getMinCount());
    assertTrue(compiled.isStateChanged());
}

@Test
void shouldCanonicalizeEquivalentRatiosToOneDigest() {
    CanonicalPlanningObjectiveSetDTO left = PlanningObjectiveCompiler.compile(
            state("major", 12, 45), fillWithRatio(45, 3, 4, 3));
    CanonicalPlanningObjectiveSetDTO right = PlanningObjectiveCompiler.compile(
            state("major", 12, 45), fillWithRatio(45, 30, 40, 30));

    assertEquals(left.getObjectiveDigest(), right.getObjectiveDigest());
    assertEquals(Integer.valueOf(14), left.getTierAllocationResolution()
            .getResolvedCounts().getSprintCount());
    assertEquals(Integer.valueOf(18), left.getTierAllocationResolution()
            .getResolvedCounts().getStableCount());
    assertEquals(Integer.valueOf(13), left.getTierAllocationResolution()
            .getResolvedCounts().getProtectCount());
}
```

同时增加以下精确矩阵：replace 删除历史 bounds；range min/max 非法；`sum(min) > target`；`sum(max) < target`；比例权重合计为零；比例余数 tie 顺序；exact 总数不一致；exact `updateMode` 不是 `replace`；跨类型 patch 返回 `tier_quota_update_type_conflict`；新 tier 请求遇到已确认 coverage/priority 时返回 `tier_quota_composite_not_supported`；新 requirements/priority 请求遇到已确认 tier goal 时同样 blocked。保留现有 `shouldCompilePersistedFourZeroObjectivesWithoutRequest`，证明 4.0 已存在 exact + coverage/单 priority 状态仍可 `compileConfirmed`，但不能接受本轮新组合字段。

- [x] **步骤 2：运行 RED 并记录预期编译失败**

运行：

```bash
cd zhiyuan-server
mvn -q -Dtest=TierAllocationSupportTest,PlanningObjectiveCompilerTest test
```

预期：由于 `TierQuotaGoalRequestDTO`、`TierAllocationSupport` 和新的 canonical 字段尚不存在，测试编译失败。把命令和第一条相关错误记录到主计划 M2 小节。

- [x] **步骤 3：使用以下准确字段名增加聚焦 DTO**

```java
@Data
public class TierCountRangeDTO {
    private Integer minCount;
    private Integer maxCount;
}

@Data
public class TierCountsDTO {
    private Integer sprintCount;
    private Integer stableCount;
    private Integer protectCount;
}

@Data
public class TierWeightsDTO {
    private Integer sprintWeight;
    private Integer stableWeight;
    private Integer protectWeight;
}

@Data
public class TierQuotaGoalRequestDTO {
    private String type;
    private String updateMode;
    private Integer sprintCount;
    private Integer stableCount;
    private Integer protectCount;
    private TierCountRangeDTO sprint;
    private TierCountRangeDTO stable;
    private TierCountRangeDTO protect;
    private Integer sprintWeight;
    private Integer stableWeight;
    private Integer protectWeight;
}

@Data
public class TierAllocationConstraintDTO {
    private String sourceType;
    private TierCountRangeDTO sprint;
    private TierCountRangeDTO stable;
    private TierCountRangeDTO protect;
}

@Data
public class TierAllocationResolutionDTO {
    private Integer targetCount;
    private TierAllocationConstraintDTO effectiveBounds;
    private TierWeightsDTO canonicalWeights;
    private TierCountsDTO resolvedCounts;
    private String resolutionMethod;
    private List<String> tieBreakOrder = Lists.newArrayList("sprint", "stable", "protect");
    private String objectiveDigest;
    private String solverVersion;
}
```

给持久化 `TierQuotaGoalDTO` 增加 range 和 weight 字段，但不增加 `updateMode`。把 `UserGoalFixProposalReq.tierQuotaGoal` 改为 `TierQuotaGoalRequestDTO`。为保持 4.0 JSON 兼容，`HardPlanningObjectivesDTO.tierQuotaGoal` 继续使用 `TierQuotaGoalDTO`，同时增加 `TierAllocationResolutionDTO tierQuotaResolution`。

- [x] **步骤 4：实现统一的 exact、range 和 ratio compiler**

使用以下 package-level 契约：

```java
static CompiledTierAllocation compile(PlanningStateDTO state,
                                      TierQuotaGoalRequestDTO request,
                                      Integer targetCount)

static CompiledTierAllocation compileConfirmed(PlanningStateDTO state,
                                               Integer targetCount)

static void persist(PlanningStateDTO state,
                    TierQuotaGoalDTO effectiveSourceGoal,
                    TierAllocationResolutionDTO resolution)

static boolean isPersisted(PlanningStateDTO state,
                           TierQuotaGoalDTO effectiveSourceGoal,
                           TierAllocationResolutionDTO resolution)
```

`CompiledTierAllocation` 必须暴露 `effectiveSourceGoal`、`canonicalGoal`、`constraint`、`resolution` 和 `stateChanged`。实现以下准确规则：

```java
if ("patch".equals(updateMode) && confirmed != null
        && !"count_ranges".equals(normalized(confirmed.getType()))) {
    throw new ContractException("tier_quota_update_type_conflict",
            "历史冲稳保目标类型不同，必须明确 replace。" );
}
if (sumMin > targetCount) {
    throw new ContractException("tier_range_min_infeasible", "档位最低数量合计超过总数。" );
}
if (sumMax < targetCount) {
    throw new ContractException("tier_range_max_infeasible", "档位最高数量合计不足总数。" );
}
```

`TierAllocationSupport` 定义带 `reasonCode` 的 package-private `ContractException`；`PlanningObjectiveCompiler` 捕获后映射为现有 `PlanningObjectiveCompiler.CompilationException`，保证外部错误契约不分叉。ratio 请求与历史 canonical ratio 语义等价时，`stateChanged=false`，并继续保留已确认 source weights，不因 `30:40:30` 与 `3:4:3` 的写法差异创建目标更新。

使用整数除法和余数解析比例，通过最大公约数约分权重，并按 `sprint, stable, protect` 顺序处理相同余数。digest payload 包含 canonical goal、effective bounds、target count、canonical weights、resolved counts 和 tie order；排除语义等价的原始比例权重、`updateMode`、`resolution.objectiveDigest` 和 `resolution.solverVersion`。计算 digest 后再把 digest 和 solver version 写入冻结 resolution。

- [x] **步骤 5：把 compiler 调用方 hard cut 到新 support**

在 `PlanningObjectiveCompiler` 中设置：

```java
result.setTierAllocationGoal(compiled.getCanonicalGoal());
result.setTierAllocationConstraint(compiled.getConstraint());
result.setTierAllocationResolution(compiled.getResolution());
result.setTierAllocationStateChanged(compiled.isStateChanged());
```

存在已持久化 ratio 且请求改变 `targetCount` 时重新解析；已持久化 exact 合计与新总数不一致时抛出 `tier_exact_total_mismatch`。不得从当前数量推导 ratio 或 range。

- [x] **步骤 6：运行 GREEN 和相邻兼容测试**

运行：

```bash
cd zhiyuan-server
mvn -q -Dtest=TierAllocationSupportTest,PlanningObjectiveCompilerTest test
```

预期：PASS。随后运行：

```bash
cd zhiyuan-server
mvn -q -Dtest=TierQuotaSupportTest,UserGoalProposalBuilderTest test
```

预期：现有 exact-count 测试继续全绿；迁移期间旧 support 只允许委托新 compiler，不再独立裁决。

- [ ] **步骤 7：获得授权后创建提交检查点**

```bash
git add zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningObjectiveCompiler.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/TierAllocationSupport.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/TierAllocationSupportTest.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PlanningObjectiveCompilerTest.java
git commit -m "feat: compile M2 tier allocation goals"
```

### 任务 2：为求解器增加范围边界和历史结构基线

**文件：** `TierStructureProjection.java` 及其测试、`OjalgoDeterministicPlanSolver.java`、`CanonicalPlanningRuntime.java` 和 solver 测试。

- [x] **步骤 1：编写失败的投影和 solver 测试**

```java
@Test
void shouldKeepCurrentCountsWhenTheyAlreadySatisfyMaxOnly() {
    CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 4);
    objectives.setTierAllocationConstraint(bounds(0, 2, 0, 4, 0, 4));
    PlanSolverResultDTO result = solver.solve(input(objectives,
            candidate("s1", 0, true, "sprint", true),
            candidate("t1", 1, true, "stable", true),
            candidate("t2", 2, true, "stable", true),
            candidate("p1", 3, true, "protect", true)));

    assertEquals("no_change", result.getStatus());
    assertEquals(Integer.valueOf(1), result.getResolvedTierCounts().getSprintCount());
}

@Test
void shouldPreferHistoricalShapeAfterApplyingSprintMaximum() {
    TierCountsDTO projected = TierStructureProjection.project(
            counts(12, 17, 16), 45, bounds(0, 10, 0, 45, 0, 45));

    assertEquals(counts(10, 18, 17), projected);
}
```

再按准确输入/输出补齐 solver 矩阵：min-only；完整 ranges；max 导致候选不足；locked 数量超过 max；ratio 编译为 exact bounds；反转 transport 候选顺序后结果不变；结构 anchor 不可达时仍在硬范围内求解；objective result 以 `tier_range` 返回 required min/max。

- [x] **步骤 2：运行 RED**

```bash
cd zhiyuan-server
mvn -q -Dtest=TierStructureProjectionTest,OjalgoDeterministicPlanSolverTest test
```

预期：投影/range 字段缺失导致编译失败，或者现有 solver 错误地只执行 exact counts。

- [x] **步骤 3：实现有界结构投影**

当 target 和 bounds 已由当前数量满足时，`TierStructureProjection.project` 必须原样返回当前数量。否则使用 largest remainder 把当前三档向量缩放到 target，截断违反的 bounds，再按历史权重向仍有容量的档位重新分配。余数相同按 `sprint, stable, protect` 处理。当前三档全为零时返回 `null`，让 solver 使用稳定候选顺序，不发明默认分布。

- [x] **步骤 4：用 min/max 表达式替换 exact-only 档位表达式**

```java
private void addTierExpression(ExpressionsBasedModel model,
                               List<Variable> variables,
                               List<PlanSolverInputDTO.CandidateDTO> candidates,
                               String tier,
                               TierCountRangeDTO bound) {
    Expression expression = model.addExpression("tier:" + tier);
    if (bound.getMinCount() != null) expression.lower(bound.getMinCount());
    if (bound.getMaxCount() != null) expression.upper(bound.getMaxCount());
    for (int index = 0; index < candidates.size(); index++) {
        if (tier.equals(tier(candidates.get(index)))) expression.set(variables.get(index), 1);
    }
}
```

围绕投影后的 tier anchor 增加非负整数 deviation 变量。设置 `CHURN_WEIGHT = 1_000_000_000_000L`、`STRUCTURE_DEVIATION_WEIGHT = 1_000_000L`，candidate stable-order 权重保持 `stableOrder + 1`；这样在最多 600 candidates 下，单次 churn 的代价严格高于全部结构偏移，单个结构偏移的代价严格高于全部 stable-order 差异。设置 `SOLVER_VERSION = "ojalgo-48.4.2-m2"`，并把 anchor/resolved tier counts 纳入 solver result/input digest。

`PlanSolverResultDTO` 增加以下准确字段，供 Proposal 和 postcondition 直接复用：

```java
private TierCountsDTO historicalTierAnchor;
private TierCountsDTO resolvedTierCounts;
```

- [x] **步骤 5：增加 typed 预检和 objective results**

eligible capacity 低于 minimum 时返回 `tier_min_infeasible`；所有 maxima 无法容纳 target 时返回 `tier_max_infeasible`；locked items 超过 maximum 时返回 `locked_conflict`。canonical exact bounds 继续返回 `tier_exact_infeasible`，避免 4.0 diagnostics 漂移。

- [x] **步骤 6：更新 canonical runtime 的目标总数解析**

删除以 `TierQuotaSupport.total()` 作为通用目标总数来源的逻辑。exact/range/ratio 都使用 canonical `targetCount`；exact 合计由 compiler 校验，ratio 和 range 不得从三个请求数量推导总数。

- [x] **步骤 7：运行 GREEN、确定性重复和 ADR fixture**

```bash
cd zhiyuan-server
mvn -q -Dtest=TierStructureProjectionTest,OjalgoDeterministicPlanSolverTest,CanonicalPlanningRuntimeTest,PlanSolver410AdrBenchmarkTest test
```

预期：PASS；相同输入重复运行得到相同 selected IDs、resolved tier counts 和 input digest。记录耗时，并确认 400-candidate fixture 仍在现有 2 秒 solver 上限内。

- [ ] **步骤 8：获得授权后创建提交检查点**

```bash
git add zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/TierStructureProjection.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/OjalgoDeterministicPlanSolver.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/CanonicalPlanningRuntime.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/PlanSolverResultDTO.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/TierStructureProjectionTest.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/OjalgoDeterministicPlanSolverTest.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/CanonicalPlanningRuntimeTest.java
git commit -m "feat: solve bounded tier allocations"
```

### 任务 3：让 Proposal 状态同时取决于方案和目标状态

**文件：** Proposal DTO、dry-run DTO、builder 和 builder 测试。

- [x] **步骤 1：编写失败的 Proposal 测试**

增加以下具名测试：

```java
@Test
void shouldCreateReadyProposalWhenNewMaximumNeedsOnlyPersistence() {
    PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
    UserGoalFixProposalReq req = fillWithSprintMaxPatch(4, 2);

    FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

    assertEquals("ready", proposal.getStatus());
    assertTrue(proposal.getActions().isEmpty());
    assertEquals("no_change", proposal.getSolverResult().getStatus());
    assertTrue(proposal.getTierQuotaChange().getStateChanged());
    assertTrue(proposal.getSummary().contains("方案项目不变"));
}

@Test
void shouldReturnInfoWhenPlanAndEffectiveGoalAreBothUnchanged() {
    PlanningStateDTO state = stateWithConfirmedSprintMax(2);
    FixProposalDTO proposal = UserGoalProposalBuilder.build(
            state, fillWithSprintMaxPatch(4, 2)).getProposals().get(0);

    assertEquals("info", proposal.getStatus());
    assertFalse(proposal.getRequiresConfirmation());
}
```

再增加准确矩阵：range replace 展示被移除的历史目标；ratio 同时展示 submitted/canonical/resolved 值；dry-run 使用实际 selected counts 而不是请求 maxima；跨类型 patch blocked 且无 actions；候选不足透出 solver diagnostic。

- [x] **步骤 2：运行 RED**

```bash
cd zhiyuan-server
mvn -q -Dtest=UserGoalProposalBuilderTest test
```

预期：`TierQuotaChangeDTO` 字段缺失，或已满足的 max-only 被错误返回为不持久化的 `info`。

- [x] **步骤 3：增加权威 Proposal 信封**

```java
@Data
public class TierQuotaChangeDTO {
    private TierQuotaGoalDTO beforeGoal;
    private TierQuotaGoalRequestDTO requestedGoal;
    private TierQuotaGoalDTO effectiveGoal;
    private TierAllocationResolutionDTO resolution;
    private Boolean stateChanged = false;
}
```

在 `FixProposalDTO` 增加 `private TierQuotaChangeDTO tierQuotaChange;`。从 solver 实际选中的 entities 填充 `resolution.resolvedCounts`，绝不能使用 range maximum。

- [x] **步骤 4：实现方案状态和目标状态的二维判定**

```java
boolean planChanged = "ready".equals(selection.solverResult.getStatus());
boolean objectiveChanged = Boolean.TRUE.equals(objectiveSet.getTierAllocationStateChanged());
if (!planChanged && !objectiveChanged && !hasProjectedRequirements && !hasPriorityRule) {
    proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
    proposal.setRequiresConfirmation(false);
    proposal.setSummary("当前方案和已确认冲稳保目标都已满足，本轮无需更新。");
    return proposal;
}
proposal.setStatus(RepairProposalTaxonomy.Status.READY);
proposal.setRequiresConfirmation(true);
```

纯目标更新时 actions 保持空，并在 Proposal 中说明只保存档位硬目标。replace 必须展示 `beforeGoal`、`requestedGoal` 和 `effectiveGoal`。blocked 设置 `requiresConfirmation=false`，且不得挂载 ready action。

- [x] **步骤 5：运行 GREEN 和 exact-count 回归**

```bash
cd zhiyuan-server
mvn -q -Dtest=UserGoalProposalBuilderTest,PlanningObjectiveCompilerTest,OjalgoDeterministicPlanSolverTest test
```

预期：PASS，并包含现有 exact replacement 和 exact total mismatch 测试。

- [ ] **步骤 6：获得授权后创建提交检查点**

```bash
git add zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/FixProposalDTO.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/FixProposalDryRunResultDTO.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/TierQuotaChangeDTO.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/UserGoalProposalBuilder.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/UserGoalProposalBuilderTest.java
git commit -m "feat: expose M2 tier allocation proposals"
```

### 任务 4：原子完成持久化、regenerate、apply、校验和回滚

**文件：** hard-objective/postcondition DTO、support、state service、command service、统一 postcondition validator 及其测试。

- [x] **步骤 1：编写失败的持久化和 postcondition 测试**

增加以下准确矩阵：range source goal + resolved counts；ratio submitted weights + canonical weights；旧 exact JSON 读取；target 45 -> 50 后 ratio 重新解析；exact 在总数变化后冲突；range regenerate；纯目标 apply；postcondition 失败。postcondition 的单元矩阵放在 `UnifiedPlanPostconditionValidatorTest`，command service 测试只验证事务顺序和结果写入边界。

```java
@Test
void shouldVerifyPersistedRangeAndActualCounts() {
    PendingPlanningCommandReq req = canonicalRangePlanChangeReq(4, 2);
    when(planningStateService.applyFixProposal(anyLong(), anyLong(), any()))
            .thenReturn(appliedRangeResult(1, 2, 1));

    PendingPlanningCommandRes result = service.execute(1L, 101L, req);

    assertTrue(result.getPostconditionReport().getTierQuotaResult().getPlanSatisfied());
    assertTrue(result.getPostconditionReport().getTierQuotaResult().getPersisted());
    assertTrue(result.getPostconditionReport().getSatisfied());
}
```

增加失败用例：持久化 max 为 2，但最终 sprint count 为 3；预期 `POSTCONDITION_FAILED_CODE`，且不得更新 succeeded command。

- [x] **步骤 2：运行 RED**

```bash
cd zhiyuan-server
mvn -q -Dtest=PlanningStateServiceTest,PendingPlanningCommandBizServiceTest,UnifiedPlanPostconditionValidatorTest,TierAllocationSupportTest test
```

预期：exact-only 持久化/postcondition 代码无法验证 range 或 ratio 状态。

- [x] **步骤 3：持久化权威 Proposal 结果而不是请求增量**

在 `PlanningStateService.applyUserGoalTargetToPlanningState` 中，用以下逻辑替换 raw quota 持久化：

```java
TierQuotaChangeDTO change = proposal.getTierQuotaChange();
if (change != null && Boolean.TRUE.equals(change.getStateChanged())) {
    TierAllocationSupport.persist(state, change.getEffectiveGoal(), change.getResolution());
}
```

用户只改变总数、已确认 ratio 因此重新解析时也必须执行该逻辑。apply 阶段不得重新计算或舍入，只消费权威重建 Proposal 和冻结 solver result。

- [x] **步骤 4：提取并泛化 postcondition，且不破坏 exact 字段**

把 `PendingPlanningCommandBizService.verifyPlanChangePostcondition` 迁移到 `@Component UnifiedPlanPostconditionValidator`，command service 只在 apply/regenerate/review 完成后调用 `validator.validate(req, state, applyRes)`。为保持 4.0 response 兼容，`TierQuotaResultDTO` 保留旧 `type/sprintCount/stableCount/protectCount`，同时增加 `effectiveGoal`、`resolution` 和 `actualCounts`。exact/ratio 对照 resolved exact counts 校验；range 对照全部有效 min/max bounds 校验。`persisted` 必须同时满足目标语义等价、canonical resolution 等价，以及 objective digest/solver metadata 匹配。

- [x] **步骤 5：保持事务回滚行为**

公开方法 `PendingPlanningCommandBizService.execute` 继续使用 `@Transactional(rollbackFor = Exception.class)`，且 validator 异常必须发生在写入 succeeded command 之前。新增 `PendingPlanningCommandRollbackIntegrationTest`：使用 `@SpringBootTest` 和 `@MockBean UnifiedPlanPostconditionValidator`，先写入隔离 session/active pending/ready command 所需状态，再让 validator 在 apply 后抛出 `BusinessException(40906, "m2_postcondition_injected_failure")`。从事务外重新读取并断言 planning version、正式 selected IDs、`tierQuotaGoal`、`tierQuotaResolution` 都等于执行前值，command 不是 succeeded，pending 不是 applied。该测试只由 `RUN_M2_ROLLBACK_INTEGRATION=1` 启用，不增加生产代码失败开关。

- [x] **步骤 6：运行 GREEN**

```bash
cd zhiyuan-server
mvn -q -Dtest=TierAllocationSupportTest,PlanningStateServiceTest,PendingPlanningCommandBizServiceTest,UnifiedPlanPostconditionValidatorTest,CanonicalPlanningRuntimeTest test
```

预期：PASS；exact postcondition response 字段继续存在；range/ratio report 同时证明方案和持久化；失败路径绝不把 command 标为 succeeded。

- [x] **步骤 7：hard cut 旧 exact-only support**

把剩余所有生产调用从 `TierQuotaSupport` 迁移到 `TierAllocationSupport`，然后删除 `TierQuotaSupport.java` 和 `TierQuotaSupportTest.java`。运行：

```bash
rg -n "TierQuotaSupport|syntheticRequirements|syntheticObjectives" zhiyuan-server/src/main zhiyuan-server/src/test
```

预期：零匹配。历史文档可以保留旧类名作为删除证据。

- [ ] **步骤 8：获得授权后创建提交检查点**

```bash
git add zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandBizService.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/TierAllocationSupport.java zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/UnifiedPlanPostconditionValidator.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PlanningStateServiceTest.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandBizServiceTest.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/UnifiedPlanPostconditionValidatorTest.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/PendingPlanningCommandRollbackIntegrationTest.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/TierAllocationSupportTest.java
git commit -m "feat: persist and verify M2 tier goals"
```

### 任务 5：扩展 Agent 契约且不增加文本恢复

**文件：** `tools.py`、direct 测试和 prompt。

- [x] **步骤 1：编写失败的 Agent 归一和 pending 测试**

增加以下准确 direct unit 矩阵：exact 兼容；max-only patch；完整 range replace；ratio replace；update mode 缺失/非法；Boolean/非整数 bounds；min > max；weights 合计为零；未知字段；range/ratio 与 requirements 组合；ready 纯目标 pending；info 真 no-change；blocked 跨类型 patch；Proposal effective-goal 透传。

```python
def test_normalize_range_patch_keeps_only_explicit_bounds():
    goal, errors = _normalize_plan_tier_quota_goal({
        "type": "count_ranges",
        "update_mode": "patch",
        "sprint": {"max_count": 10},
    })
    assert errors == []
    assert goal == {
        "type": "count_ranges",
        "updateMode": "patch",
        "sprint": {"maxCount": 10},
    }
```

- [x] **步骤 2：运行 RED**

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_release_410_plan_change_contract.py tests/unit/test_zhiyuan_agent_direct.py -k "tier_quota or tier_allocation" -q
```

预期：新类型被 `only_exact_counts_supported` 拒绝，或者被错误冻结成 exact-only payload。

- [x] **步骤 3：增加可区分的 TypedDict 结构**

```python
class PlanTierCountBound(TypedDict, total=False):
    min_count: int
    max_count: int

class PlanTierQuotaGoal(TypedDict, total=False):
    type: Literal["exact_counts", "count_ranges", "ratios"]
    update_mode: Literal["patch", "replace"]
    sprint_count: int
    stable_count: int
    protect_count: int
    sprint: PlanTierCountBound
    stable: PlanTierCountBound
    protect: PlanTierCountBound
    sprint_weight: int
    stable_weight: int
    protect_weight: int
```

只保留一个公开 `tier_quota_goal` 字段。归一逻辑可以把 snake_case 改为 camelCase 并校验标量类型，但不得读取 `raw_user_text`、当前自然语言或中文话术列表。

- [x] **步骤 4：分别冻结请求增量和权威 Proposal 状态**

把归一后的请求增量作为 `userGoalRequest.tierQuotaGoal` 发送；把原始 snake-case typed delta 保存到 `executionPayload.plan_change_spec`；把后端 `proposal.tierQuotaChange.effectiveGoal` 和 `resolution` 保存到 pending postconditions/display。Python 不得计算比例数量或合并历史 bounds。

只有 exact goal 执行本地总数合计早期校验。range/ratio 的 target 可行性以后端 compiler 为准。没有 `selection_goal` 时继续保持当前正式方案总数。

- [x] **步骤 5：保留 M3 guard 并更新稳定 prompt 边界**

Prompt 只说明 schema 语义、`patch` 与显式 `replace` 的区别、完整 ratio weights 和禁止猜数。不得恢复 M1 已删除的常驻当前 tier distribution，也不得增加中文话术用例列表。

- [x] **步骤 6：运行 GREEN 和全部 direct Agent 测试**

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_release_410_m0_contract.py tests/unit/test_release_410_plan_change_contract.py tests/unit/test_zhiyuan_agent_direct.py -q
```

预期：PASS；现有 4.0 exact pending shape 继续接受；新的 range/ratio pending 只包含一个 Proposal 和一个权威 apply payload。

执行证据（2026-07-20）：

- RED：新增 exact/range/ratio 归一、请求增量冻结、权威 effective goal/resolution、非 ready Proposal、M3 组合 guard 和 prompt 边界矩阵；新类型最初仍走 exact-only 拒绝/冻结路径。补充确认结果类型用例后，range/ratio 均稳定失败为“冲稳保精确配额”；补充未知类型用例后，稳定失败为旧 `only_exact_counts_supported` 且误报 exact 字段缺失。
- GREEN：`PlanTierQuotaGoal` 扩展为 exact/range/ratio 与 patch/replace；Python 只做结构化字段归一和 exact 合计校验，range/ratio 合并、可行性、约分和解析全部交给后端；pending 分别冻结 snake-case 请求 delta、camelCase `userGoalRequest` 和 Proposal 权威 effective goal/resolution。确认成功文案按 postcondition 类型展示精确配额、数量范围或比例。
- VERIFY：运行 `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_release_410_m0_contract.py tests/unit/test_zhiyuan_agent_direct.py -q`，最终结果 `290 passed, 33 skipped`。Task 6 才创建的 `test_release_410_plan_change_contract.py` 本步骤未提前伪造。
- CLEAN：删除过时错误码 `only_exact_counts_supported`，未知类型改为 `tier_quota_type_invalid` 并在类型字段边界 fail closed；旧 exact 场景例句未恢复，quota normalizer 不读取 `raw_user_text`，M3 前 `tier_quota_composite_not_supported` 继续保留。

- [ ] **步骤 7：获得授权后创建提交检查点**

```bash
git add zhiyuan-agent/app/zhiyuan_agent/tools.py zhiyuan-agent/app/zhiyuan_agent/prompt.py zhiyuan-agent/tests/unit/test_release_410_m0_contract.py zhiyuan-agent/tests/unit/test_release_410_plan_change_contract.py zhiyuan-agent/tests/unit/test_zhiyuan_agent_direct.py
git commit -m "feat: expose M2 tier goals to the agent"
```

### 任务 6：更新离线契约、golden 用例和真实对话资产

**文件：** reference contract/golden、quality gate、新 M2 case 文件和主计划。

- [x] **步骤 1：先更新离线 reference contract，再调整预期数量**

先把 `test_release_410_m0_contract.py` 中持续演进的 PlanChangeSpec/golden/normalizer 断言移到新文件 `test_release_410_plan_change_contract.py`；原文件只保留冻结 M0 manifest 和大 fixture 来源断言。随后设置 `SCHEMA_VERSION = "4.1.0-m2"`。range/ratio 强制 `update_mode`；exact 允许缺省或 `replace`；用最大公约数 canonicalize ratio weights；patch 输出表达请求增量，不能在没有 planning state 时假装已经完成合并。reference API 增加可选 `context_tier_goal`，只用于验证同类型历史 patch 和跨类型 typed blocked。

- [x] **步骤 2：增加精确 golden 用例**

合法矩阵包括：max-only patch、完整 range replace、总数 45 的 ratio replace、等价的 30:40:30 ratio，以及不含 update mode 的 4.0 exact。非法矩阵包括：range mode 缺失、ratio patch、空 range、min > max、bounds 合计不可行、weight 合计为零、exact patch，以及带 confirmed-goal context 的跨类型 patch。unit 断言更新为精确的新用例总数。

- [x] **步骤 3：运行 contract 和 JSON parse gate**

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python examples/plan_change_spec_410_contract.py
```

预期：全部 golden case 通过，且 `failures=[]`。

- [x] **步骤 4：增加一个 M2 final-action 包**

`dialog_regression_410_m2_tier_allocation_cases.json` 必须包含以下隔离用例和准确后端断言：

- max-only currently satisfied -> ready pending -> confirm persists range with zero add/remove;
- max-only currently violated -> confirm final sprint count is at most max;
- same-type historical range patch keeps unmentioned bounds;
- cross-type patch -> blocked, no pending;
- ratio -> Proposal shows resolved counts -> confirm persists source weights and canonical resolution;
- confirmed ratio plus new target count -> one new Proposal with re-resolved counts;
- repeated semantically identical goal -> no pending;
- candidate shortage/locked conflict -> blocked, no partial persistence.

在 `dialog_quality_gate.py` 中把该文件注册为 M2 包。不得修改 `release_410_m0_baseline_manifest.json`；M0 的 24-file/178-step 证据已经冻结。

使用独立常量和 mode，不能把 M2 文件追加进冻结的 `FINAL_ACTION_CASE_FILES`：

```python
M2_FINAL_ACTION_CASE_FILES = [
    "dialog_regression_410_m2_tier_allocation_cases.json",
]
```

把 `tests/unit/test_release_410_plan_change_contract.py` 加入 `LOCAL_PYTEST_TARGETS`；给 gate 增加 `m2-final-action` category 和同名 `--mode` choice。现有 `final-action` 仍只运行冻结 24 包，`m2-final-action` 只运行上述 M2 列表，`all` 才同时包含两者。

- [ ] **步骤 5：验证资产和聚焦真实对话**

解析全部受控 JSON，然后用 `dialog_regression_runner.py` 运行新包，并携带 `--clear-history-per-case`、`--clear-backend-pending-per-case`、`--clear-backend-planning-intent-per-case`、`--assert-plan-style` 和准确的 `/private/tmp/zhiyuan_410_m2_tier_allocation_gate.json` metrics 路径。继续使用现有 60 秒 warning 和 180 秒 response 上限。

预期：一次 clean first-pass 结果；不得重试失败的 turn/case/package 来拼接发布证据。

执行记录（2026-07-20）：离线 contract 输出 `schemaVersion=4.1.0-m2`、`26/26`、`failures=[]`；M0/可演进 contract/gate 静态组合为 `28 passed`。M2 包冻结 `8 cases / 21 steps`，独立 `m2-final-action` mode 只生成这一条命令，冻结的 `FINAL_ACTION_CASE_FILES` 仍为 24 个且 manifest 无 diff。

真实对话未通过退出门禁：`/private/tmp/zhiyuan_410_m2_tier_allocation_gate.json` 记录 `steps=8`、`successfulSteps=0`、`failedSteps=8`、`failedByReason.environment=8`。全部 case 在第一个对话 turn 前即因 runner 使用默认 `18290` 而本地后端位于 `8080`、MySQL clone 未传本地密码而终止；没有产生功能性结果。遵守一次 clean first-pass 规则，本轮未重跑 turn/case/package，也未将其标记为 M2 通过证据。

- [ ] **步骤 6：获得授权后创建提交检查点**

```bash
git add zhiyuan-agent/examples/plan_change_spec_410_contract.py zhiyuan-agent/examples/plan_change_spec_410_golden.json zhiyuan-agent/examples/dialog_regression_410_m2_tier_allocation_cases.json zhiyuan-agent/examples/dialog_quality_gate.py zhiyuan-agent/tests/unit/test_release_410_m0_contract.py zhiyuan-agent/tests/unit/test_release_410_plan_change_contract.py docs/release-4.1.0-zhiyuan-agent-implementation-plan.md
git commit -m "test: add M2 tier allocation release cases"
```

### 任务 7：完成全量验证、失败审计、清理和里程碑关闭

**文件：** 全部 M2 文件、主计划、metrics、数据库、候选副本和 MySQL binlog。

- [x] **步骤 1：从 clean compile 运行聚焦 Java/Python 测试集**

```bash
cd zhiyuan-server
mvn -q clean -Dtest=TierAllocationSupportTest,TierStructureProjectionTest,PlanningObjectiveCompilerTest,OjalgoDeterministicPlanSolverTest,CanonicalPlanningRuntimeTest,UserGoalProposalBuilderTest,PlanningStateServiceTest,PendingPlanningCommandBizServiceTest,UnifiedPlanPostconditionValidatorTest test
```

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_release_410_m0_contract.py tests/unit/test_release_410_plan_change_contract.py tests/unit/test_zhiyuan_agent_direct.py -q
```

预期：PASS，且 failures/errors 都为零。

- [x] **步骤 2：运行全量自动化测试集**

```bash
cd zhiyuan-server
mvn -q clean test
```

```bash
cd zhiyuan-agent
PYTHONPATH=. .venv/bin/python -m pytest -q
```

预期：failures/errors 为零；明确报告 skipped 测试。把准确数量和耗时写入主计划。

- [x] **步骤 3：运行静态检查和资产检查**

运行 Python `compileall`，解析所有受控 examples/server JSON，运行 `git diff --check`，并使用 `rg` 审计旧 `TierQuotaSupport`、synthetic quota helpers、新增 raw-text recovery、中文话术映射、solver fallback，以及对 `tier_quota_composite_not_supported` 的任何提前删除。

预期：旧 support/synthetic 生产引用为零；M3 guard 仍然存在；全部 JSON 和编译检查通过。

- [ ] **步骤 4：运行一次 clean M2 final-action gate 和冻结的 4.0 回归**

在隔离服务中运行新 M2 包和现有冻结的 24-package final-action gate。冻结的 24 包必须与 manifest 完全一致，M2 包必须与自身声明的 step count 一致。只有在 `warnings=[]`、`failures=[]`、没有 case/package/turn retry、没有放宽超时时才能退出。

- [x] **步骤 5：运行隔离事务集成测试证明回滚**

以 `RUN_M2_ROLLBACK_INTEGRATION=1` 运行 `PendingPlanningCommandRollbackIntegrationTest`。测试通过 mock Spring validator 在 apply 后抛错，不修改生产配置；验证 command 失败、pending 不是 `applied`、planning version 不增长、正式 selected IDs 不变，并且 `tierQuotaGoal`、`tierQuotaResolution` 都等于执行前值。测试 finally 删除隔离 session、pending、command 和 planning state。

```bash
cd zhiyuan-server
RUN_M2_ROLLBACK_INTEGRATION=1 mvn -q -Dtest=PendingPlanningCommandRollbackIntegrationTest test
```

预期：PASS；finally 清理后隔离 session、pending、command 和 planning state 行数都为零。

- [x] **步骤 6：清理测试状态和磁盘资产**

只删除 M2 测试 session/command/pending/extra/message/behavior/freshness/integration 行、Agent SQLite history、候选 clone 文件、被替换的 M2 metrics 和临时 probe 文件。封存 MySQL binlog 只能通过 MySQL SQL purge，必须保留活动 binlog，并复查磁盘空间和已停止端口。严禁从文件系统直接删除 binlog。

执行证据（2026-07-20）：

- 最终聚焦集：Java `362 tests`、`0 failures/errors`、`3 skipped`；Python `296 passed, 33 skipped`。
- 最终全量集：Java `655 tests`、`0 failures/errors`、`5 skipped`；Python `1763 passed, 42 skipped`。
- 静态/资产：`compileall` 退出码 0，受控 examples/resources/bizdata 共 `51` 个 JSON 全部解析，`git diff --check` 通过；旧 `TierQuotaSupport`、synthetic quota helper 和旧 command postcondition 为零匹配，M3 `tier_quota_composite_not_supported` 仍存在。
- 回滚：`RUN_M2_ROLLBACK_INTEGRATION=1` 的 `PendingPlanningCommandRollbackIntegrationTest` 为 `1/1`，退出码 0；finally 继续验证隔离 session/pending/command/planning state 零残留。
- 清理：live 环境失败生成的 `9914201-9914208` 共 24 个候选副本已删除，应用服务端口均停止；MySQL chat session/command/pending/extra data 四类残留行均为 `0`，Agent SQLite history 为 `0`，磁盘约 `83GiB` 可用。MySQL 9 `SHOW BINARY LOGS` 与 `SHOW BINARY LOG STATUS` 均确认只有活动 `binlog.000612`（约 150KB），没有旧 binlog 可 purge，因此未删除活动日志。
- 旧文案：`UserGoalProposalBuilder` 的通用 exact-only 文案已改为按 exact/range/ratio 类型化，新增 range/ratio ready 和 M3 blocked 回归；生产代码中剩余“冲稳保精确配额”仅位于 exact 专用摘要、校验和确认标签。
- 第二轮完整 live 证据：修复 8080/数据库凭据后重新执行完整 `8 cases / 21 steps`，环境准备全部成功，结果 `7/21`；`14` 个失败按 runner 计为 content `11`、backend `6`、tool `1`，没有 environment failure。不得运行冻结 24 包，也不得关闭 M2。
- live 首因不是后端数学路径：SQLite 历史中的真实 tool args 证明混合 `total=False` schema 允许模型把 ratio/range 换算成 exact、给纯 tier 请求附加无依据 selection/requirements，并把历史 range 全量回填为 patch 请求。下一轮 RED/GREEN 必须采用 discriminator union、一次 typed retry 和 Proposal 权威 requested delta，继续禁止中文话术规则及 raw text recovery。
- live 同时证伪三条资产假设：候选源有 `514` 个冲刺候选，`min=45` 不会容量不足；ratio DTO 合法携带其他 nullable 字段；纯目标更新的完整 unit DTO 会刷新，但 45 个 `unitId` 的集合和顺序保持一致。资产修复只能改为确定性不可行边界、subset contains 和 ID 序列对账，不能删除真实 postcondition/persistence 断言。

- [ ] **步骤 7：在 canonical 主计划中关闭 M2**

在 `docs/release-4.1.0-zhiyuan-agent-implementation-plan.md` 中记录 RED/GREEN 步骤、准确自动化数量、final-action 路径、失败分类、回滚证据、清理行数、活动 binlog、磁盘空间和已删除旧实现清单。只有 10.3 节所有退出条件满足后才能标记 M2 完成；M3 继续 pending。

- [ ] **步骤 8：获得授权后创建最终提交**

```bash
git add docs/release-4.1.0-zhiyuan-agent-implementation-plan.md docs/superpowers/plans/2026-07-20-zhiyuan-agent-m2-tier-allocation.md
git commit -m "docs: close M2 tier allocation milestone"
```

## 契约覆盖映射

| 已确认契约 | 实施任务 |
| --- | --- |
| count ranges、max-only、patch/replace、跨类型 blocked | 任务 1、3、5、6 |
| ratio 约分、largest remainder、固定 tie、总数变化重算 | 任务 1、2、4、6 |
| 原始请求、有效持久化目标、canonical bounds、冻结数量分层 | 任务 1、3、4、5 |
| 历史硬目标继承与当前实际结构次级优化 | 任务 1、2 |
| 纯目标更新、真正 no-change、blocked 无 pending | 任务 3、5、6 |
| 单 Proposal/pending/command、冻结 apply、统一 postcondition | 任务 3、4、5 |
| apply 失败同时回滚方案和目标 | 任务 4、7 |
| 4.0 exact 请求、状态、pending 和 response 兼容 | 任务 1、2、4、5、7 |
| 新 M3 组合继续 fail closed；4.0 grandfathered exact 组合只兼容 regenerate | 任务 1、4、5、7 |

## 完成门禁

- [ ] 4.0 exact 请求、持久化状态和旧 pending 继续可读、可执行。
- [ ] Max-only、ranges、ratio resolution、ratio 总数变化、range patch 和显式 replace 都有 typed Agent/backend 契约。
- [ ] 历史已确认目标继续是硬要求；历史实际结构只作为确定性的次级目标。
- [ ] 纯目标变化创建一个 ready pending；真正语义 no-change 不创建 pending。
- [ ] Blocked 路径不创建 pending，也不持久化任何内容。
- [ ] Apply 消费冻结的服务端 Proposal 数据；事务回滚同时恢复方案和目标。
- [ ] Postcondition 证明 bounds/resolved counts、持久化 goal/resolution、canonical digest、solver/input version、selected IDs 和 order。
- [ ] M3 组合继续 blocked，且不引入 soft-preference/runtime phrase-rule 路径。
- [ ] hard cut 后删除旧 exact-only support 和被替换的测试。
- [ ] 全量测试、静态检查、M2 final-action、冻结 4.0 gate、清理和文档全部完成。
