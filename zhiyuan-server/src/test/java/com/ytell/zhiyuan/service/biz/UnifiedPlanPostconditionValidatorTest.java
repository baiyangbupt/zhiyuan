package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaChangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class UnifiedPlanPostconditionValidatorTest {

    private final UnifiedPlanPostconditionValidator validator =
            new UnifiedPlanPostconditionValidator();

    /**
     * 约束路的满足度：方案里有违反已确认硬约束的条目 ⇒ 40905（事务回滚，不改用户方案）。
     *
     * <p>真栈形态（2026-09-25）：`mustIncludeMajors=["临床医学"]` 下，重生成后的方案里
     * 14/26 个单元不含临床医学（中医学/口腔医学/麻醉学…）——命令层却报 `succeeded` ✗，
     * 而网关侧连 `status` 字段都读不到 → 只能判 `failed` ✗。两个信号都不可用。
     */
    @Test
    void shouldFailConstraintApplyWhenPlanViolatesConfirmedConstraint() {
        PlanningStateDTO state = constraintState(Lists.newArrayList("临床医学"));
        state.getOrderedPlanState().getUnits().add(unit("中医学(五年)", "中医学类", "医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(五年)", "临床医学类", "医学"));

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validateConstraintApply("apply_constraint_and_regenerate", state));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
    }

    /** 对照：方案全部合规时给出满足的报告，命令照常成功。 */
    @Test
    void shouldAcceptConstraintApplyWhenPlanSatisfiesConfirmedConstraint() {
        PlanningStateDTO state = constraintState(Lists.newArrayList("临床医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(五年)", "临床医学类", "医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(5+3一体化)", "临床医学类", "医学"));

        PlanChangePostconditionReportDTO report = validator.validateConstraintApply(
                "apply_constraint_and_regenerate", state);

        assertTrue(report.getSatisfied());
        assertEquals("unit", report.getCountMode());
        assertEquals(Integer.valueOf(2), report.getActualCount());
    }

    /**
     * 纯学费清理是替换语义：执行前 3 组、执行后 2 组 ⇒ 不得报 satisfied
     * （2026-10-18 真栈：51 组缩到 36 组仍 satisfied=true ✗，回执也看不出缺口）。
     */
    @Test
    void shouldFailCountPreservingConstraintWhenPlanShrinks() {
        PlanningStateDTO state = constraintState(Lists.newArrayList("临床医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(五年)", "临床医学类", "医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(5+3一体化)", "临床医学类", "医学"));

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validateConstraintApply(
                        "apply_constraint_and_regenerate", state, 3, true));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        assertTrue(error.getMessage().contains(
                UnifiedPlanPostconditionValidator.CONSTRAINT_COUNT_SHORTFALL_REASON));
        assertTrue(error.getMessage().contains("before=3 actual=2 shortage=1"));
    }

    /** 对照：`only_keep` / `exclude` 的收缩是预期结果——不启用数量判据时照常满足。 */
    @Test
    void shouldAllowScopeConstraintToShrinkWhenCountPreservationIsOff() {
        PlanningStateDTO state = constraintState(Lists.newArrayList("临床医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(五年)", "临床医学类", "医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(5+3一体化)", "临床医学类", "医学"));

        PlanChangePostconditionReportDTO report = validator.validateConstraintApply(
                "apply_constraint_and_regenerate", state, 3, false);

        assertTrue(report.getSatisfied());
        assertEquals(Integer.valueOf(3), report.getCountBefore());
        assertEquals(Integer.valueOf(2), report.getActualCount());
        assertEquals(Integer.valueOf(0), report.getShortage());
    }

    /** 数量保持住了：回执要能读到 before/after，且 shortage=0。 */
    @Test
    void shouldReportCountBeforeAndAfterWhenCountIsPreserved() {
        PlanningStateDTO state = constraintState(Lists.newArrayList("临床医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(五年)", "临床医学类", "医学"));
        state.getOrderedPlanState().getUnits().add(unit("临床医学(5+3一体化)", "临床医学类", "医学"));

        PlanChangePostconditionReportDTO report = validator.validateConstraintApply(
                "apply_constraint_and_regenerate", state, 2, true);

        assertTrue(report.getSatisfied());
        assertEquals(Integer.valueOf(2), report.getCountBefore());
        assertEquals(Integer.valueOf(2), report.getActualCount());
        assertEquals(Integer.valueOf(0), report.getShortage());
    }

    /**
     * **空方案上没有"已满足"** ✓（2026-09-26 裁决落地 ✓）：三类约束的共同前提是"得有对象可比"。
     *
     * <p>数违反条目这条路（`validateConstraintApply` ✓）在空方案上是**零违反** ✗ →
     * 会判 `satisfied=true` ✗；报告路的排除类判据 `noneMatch` 同样恒真 ✗。
     * "方案没了"被读成"约束已满足"，是报告最会误导人的那种自相矛盾 ✗
     * （命令侧的 `40906` 只护着"约束刚落地"那一条 ✗，而满足度报告是**长期可读的证据** ✓）。
     */
    @Test
    void shouldNotTreatEmptyPlanAsSatisfiedByExcludeConstraint() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getConstraintState().getHardConstraints().setMustExcludeMajors(Lists.newArrayList("临床医学"));
        // 方案是空的 ✗（一条不剩）

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validateConstraintApply("apply_constraint_and_regenerate", state));
        assertTrue(error.getMessage().contains(UnifiedPlanPostconditionValidator.EMPTY_PLAN_VACUOUS_REASON),
                "失败要说明是「没有可比对象」，别让下游只能猜 ✗：" + error.getMessage());
    }

    /** 对照 ✓：**没有已确认约束**时空方案不算失败 ✓（"零违反"本来就对 ✓，别把这条改坏了 ✗）。 */
    @Test
    void shouldAcceptEmptyPlanWhenNoConstraintIsConfirmed() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");

        PlanChangePostconditionReportDTO report = validator.validateConstraintApply(
                "apply_constraint_and_regenerate", state);

        assertTrue(report.getSatisfied());
        assertEquals(Integer.valueOf(0), report.getActualCount());
    }

    private PlanningStateDTO constraintState(java.util.List<String> includeMajors) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getConstraintState().getHardConstraints().setMustIncludeMajors(includeMajors);
        return state;
    }

    private OrderedUnitDTO unit(String majorName, String category, String discipline) {
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u-" + majorName);
        unit.setSchoolName("测试大学");
        unit.setProvinceName("广东");
        unit.setCityName("广州");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        // 组内专业带出 `majorName` + 分类**名** ✓（与真实工作台一致 ✓：
        // `PlanningUnitMajorDTO` 现在带上 `majorCategory`/`majorDiscipline` ✓，
        // 单元侧的专业筛选（`RepairCandidateEligibility`）按同一套字段比对 ✓）。
        major.setMajorName(majorName);
        major.setMajorCategory(category);
        major.setMajorDiscipline(discipline);
        unit.setMajorItems(Lists.newArrayList(major));
        return unit;
    }

    /**
     * 范围把门类说成“医学类”时，单元侧也要判得过 ✓（2026-10-08 真栈：只留“医学类”）。
     *
     * <p>单元专业带不出分类名时 ✗，`"医学类"` 只剩专业名可看——候选侧筛过的单元
     * （`discipline="医学"`）在这里被算作违反 ✗ → 40905 回滚（用户看到的还是"没改成" ✗）。
     */
    @Test
    void shouldAcceptConstraintApplyWhenUnitMajorMatchesScopeWithTaxonomySuffix() {
        PlanningStateDTO state = constraintState(Lists.newArrayList("医学类"));
        state.getOrderedPlanState().getUnits().add(unit("口腔医学(5年)", "口腔医学类", "医学"));
        state.getOrderedPlanState().getUnits().add(unit("麻醉学(5年)", "临床医学类", "医学"));

        PlanChangePostconditionReportDTO report = validator.validateConstraintApply(
                "apply_constraint_and_regenerate", state);

        assertTrue(report.getSatisfied());
        assertEquals(Integer.valueOf(2), report.getActualCount());
    }

    /** 对照 ✗：分类名对不上“医学类”的单元仍要判违反（40905 该响就响 ✓）。 */
    @Test
    void shouldFailConstraintApplyWhenUnitMajorTaxonomyMissesSuffixScope() {
        PlanningStateDTO state = constraintState(Lists.newArrayList("医学类"));
        state.getOrderedPlanState().getUnits().add(unit("软件工程", "计算机类", "工学"));

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validateConstraintApply("apply_constraint_and_regenerate", state));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
    }

    /**
     * 报告口径 == 生成口径（2026-10-16 40905 定案）：请求不带 `priorityRules`、state 里有一条
     * **持久化**优先规则时，报告必须**按 state 规则重建** ✓。
     *
     * <p>生成侧 `PlanningObjectiveCompiler.compile`（:58-60）请求为空即回落已确认规则，
     * 冻结目标因此带 `priority:0`；报告侧以前只遍历请求 ⇒ 请求为空时漏掉这条 objective ⇒
     * 冻结目标对不上 ⇒ 卡任何点击必挂 `frozen objective result mismatch` ✗
     * （"浙江优先"卡 rev15 实拍，100% 复现）。
     */
    @Test
    void shouldReportStatePersistedPriorityRuleWhenRequestOmitsPriorityRules() {
        PlanningStateDTO state = stateWithPersistedPriorityRule("浙江");
        PendingPlanningCommandReq request = fillRequestWithoutPriorityRules(2);

        PlanChangePostconditionReportDTO report = validator.validate(
                request, state, userGoalApplyResult());

        assertTrue(report.getSatisfied());
        assertEquals(Integer.valueOf(1), report.getPriorityRuleCount());
        assertEquals(Integer.valueOf(1), report.getSatisfiedPriorityRuleCount());
        assertTrue(report.getPriorityRuleResults().get(0).getPersisted());
        assertEquals("priority:0", report.getObjectiveResults().get(1).getObjectiveId());
        assertTrue(report.getObjectiveResults().get(1).getSatisfied());
    }

    /**
     * 覆盖约束同理：生成侧 `mergedCoverage(state, request)` 总会带上已确认覆盖，
     * 报告侧只遍历请求就会漏掉 `coverage:0` → 40905。请求没重复浙江≥2 时也要报。
     * canonical 元数据完整（两侧 digest + hardObjectiveVersion）时正常通过。
     */
    @Test
    void shouldReportPersistedCoverageRequirementWhenCanonicalMetadataIsComplete() {
        PlanningStateDTO state = coverageState();
        Fixture fixture = coverageFixture(state, "solver-hard-objective-v1.2");

        PlanChangePostconditionReportDTO report = validator.validate(
                fixture.request, fixture.state, fixture.applyResult);

        assertTrue(report.getSatisfied());
        assertEquals(Integer.valueOf(1), report.getRequirementCount());
        // validateCanonicalObjectiveResults 通过后用 frozen 列表回填报告，
        // 所以这里只剩冻结结果本身（coverage:0）。
        assertEquals("coverage:0", report.getObjectiveResults().get(0).getObjectiveId());
        assertTrue(report.getObjectiveResults().get(0).getSatisfied());
    }

    /**
     * 旧测试曾靠 solverVersion/solverInputDigest 精确相等、无 hardObjectiveVersion 也能成功
     * （legacy 回退）。staged solver 是唯一框架后 hardObjectiveVersion 强制：缺失即 40905。
     */
    @Test
    void shouldFailCanonicalPostconditionWhenHardObjectiveVersionIsMissing() {
        PlanningStateDTO state = coverageState();
        Fixture fixture = coverageFixture(state, null);

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validate(fixture.request, fixture.state, fixture.applyResult));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        assertTrue(error.getMessage().contains("canonical frozen result metadata mismatch"));
    }

    /** scope-only 提案（无 canonical objective 元数据）：canonical 校验整体跳过。 */
    @Test
    void shouldSkipCanonicalChecksForScopeOnlyProposal() {
        PlanningStateDTO state = coverageState();
        Fixture fixture = coverageFixture(state, null);
        fixture.request.getProposalApply().setCanonicalObjectiveDigest(null);
        fixture.request.getProposalApply().setSolverVersion(null);
        fixture.request.getProposalApply().setSolverInputDigest(null);
        fixture.applyResult.getProposal().setCanonicalObjectiveDigest(null);
        fixture.applyResult.getProposal().setSolverVersion(null);
        fixture.applyResult.getProposal().setSolverInputDigest(null);
        fixture.applyResult.getProposal().setSolverResult(null);

        PlanChangePostconditionReportDTO report = validator.validate(
                fixture.request, fixture.state, fixture.applyResult);

        assertTrue(report.getSatisfied());
    }

    private PlanningStateDTO coverageState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getCandidatePoolState().getItems().add(candidate("a", "浙江"));
        state.getCandidatePoolState().getItems().add(candidate("b", "浙江"));
        state.getOrderedPlanState().getItems().add(orderedItem("a", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("b", "稳"));
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("region");
        coverage.setKey("province");
        coverage.setValues(Lists.newArrayList("浙江"));
        coverage.setMinCount(2);
        state.getConstraintState().getHardPlanningObjectives()
                .setCoverageRequirements(Lists.newArrayList(coverage));
        return state;
    }

    private Fixture coverageFixture(PlanningStateDTO state, String hardObjectiveVersion) {
        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(2);
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId("ugp-coverage");
        applyReq.setProposalSource("user_goal");
        applyReq.setUserGoalRequest(userGoal);
        String digest = PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest();
        applyReq.setCanonicalObjectiveDigest(digest);
        applyReq.setSolverVersion("sv");
        applyReq.setSolverInputDigest("sid");
        applyReq.setHardObjectiveVersion(hardObjectiveVersion);

        PlanSolverResultDTO frozen = new PlanSolverResultDTO();
        frozen.setStatus("ready");
        frozen.setSolverVersion("sv");
        frozen.setInputDigest("sid");
        frozen.setSelectedEntityIds(Lists.newArrayList("a", "b"));
        frozen.setOrderedEntityIds(Lists.newArrayList("a", "b"));
        PlanSolverResultDTO.ObjectiveResultDTO coverageResult =
                new PlanSolverResultDTO.ObjectiveResultDTO();
        coverageResult.setObjectiveId("coverage:0");
        coverageResult.setObjectiveType("coverage");
        coverageResult.setRequiredMin(2);
        coverageResult.setActualCount(2);
        coverageResult.setSatisfied(true);
        frozen.getObjectiveResults().add(coverageResult);

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("ugp-coverage");
        proposal.setProposalSource("user_goal");
        proposal.setCanonicalObjectiveDigest(digest);
        proposal.setSolverVersion("sv");
        proposal.setSolverInputDigest("sid");
        proposal.setHardObjectiveVersion(hardObjectiveVersion);
        proposal.setSolverResult(frozen);
        PendingPlanningCommandReq request = new PendingPlanningCommandReq();
        request.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        request.setProposalApply(applyReq);
        FixProposalApplyRes applyRes = new FixProposalApplyRes();
        applyRes.setStatus("applied");
        applyRes.setProposal(proposal);
        return new Fixture(request, state, applyRes);
    }

    /**
     * 后置校验与 apply 前策略同判据：两侧 hardObjectiveVersion major 相同时，
     * solverVersion/solverInputDigest 的跨部署漂移不应把已应用的结果判失败
     * （请求↔提案的版本不再比对，绑定只看提案↔冻结结果）。
     */
    @Test
    void shouldAcceptSolverVersionDriftWhenHardObjectiveMajorMatches() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getCandidatePoolState().getItems().add(candidate("a", "浙江"));
        state.getCandidatePoolState().getItems().add(candidate("b", "浙江"));
        state.getOrderedPlanState().getItems().add(orderedItem("a", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("b", "稳"));

        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(2);
        String digest = PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest();
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId("ugp-s4");
        applyReq.setProposalSource("user_goal");
        applyReq.setUserGoalRequest(userGoal);
        applyReq.setCanonicalObjectiveDigest(digest);
        applyReq.setSolverVersion("solver-from-previous-deploy");
        applyReq.setSolverInputDigest("input-from-previous-deploy");
        applyReq.setHardObjectiveVersion("solver-hard-objective-v1.9");

        PlanSolverResultDTO frozen = new PlanSolverResultDTO();
        frozen.setStatus("ready");
        frozen.setSolverVersion("solver-from-current-deploy");
        frozen.setInputDigest("input-from-current-deploy");
        frozen.setSelectedEntityIds(Lists.newArrayList("a", "b"));
        frozen.setOrderedEntityIds(Lists.newArrayList("a", "b"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("ugp-s4");
        proposal.setProposalSource("user_goal");
        proposal.setCanonicalObjectiveDigest(digest);
        proposal.setSolverVersion("solver-from-current-deploy");
        proposal.setSolverInputDigest("input-from-current-deploy");
        proposal.setHardObjectiveVersion("solver-hard-objective-v1.2");
        proposal.setSolverResult(frozen);

        PendingPlanningCommandReq request = new PendingPlanningCommandReq();
        request.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        request.setProposalApply(applyReq);
        FixProposalApplyRes applyRes = new FixProposalApplyRes();
        applyRes.setStatus("applied");
        applyRes.setProposal(proposal);

        PlanChangePostconditionReportDTO report = validator.validate(request, state, applyRes);

        assertTrue(report.getSatisfied());
        assertEquals("solver-from-current-deploy", report.getSolverVersion());
    }

    /**
     * J5.4 拍板：safety 只报告、不因缺口回滚。方案数量/要求都满足，但本省
     * 保底为 0 时，satisfied 仍为 true，safetyResult 明确记缺口。
     */
    @Test
    void shouldReportSafetyDeficitWithoutBlockingApply() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getCandidatePoolState().setUserScore(550);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        CandidateItemDTO first = candidate("v1", "浙江");
        CandidateItemDTO second = candidate("v2", "浙江");
        state.getCandidatePoolState().getItems().add(first);
        state.getCandidatePoolState().getItems().add(second);
        state.getOrderedPlanState().getItems().add(orderedItem("v1", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("v2", "稳"));

        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(2);
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId("ugp-safety");
        applyReq.setProposalSource("user_goal");
        applyReq.setUserGoalRequest(userGoal);
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("ugp-safety");
        proposal.setProposalSource("user_goal");
        proposal.setStrategy("fill_missing_count");
        FixProposalApplyRes applyRes = new FixProposalApplyRes();
        applyRes.setStatus("applied");
        applyRes.setProposal(proposal);
        PendingPlanningCommandReq request = new PendingPlanningCommandReq();
        request.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        request.setProposalApply(applyReq);

        PlanChangePostconditionReportDTO report = validator.validate(request, state, applyRes);

        assertTrue(report.getSatisfied());
        assertFalse(report.getSafetyResult().getSatisfied());
        assertEquals(Integer.valueOf(2), report.getSafetyResult().getRequiredCount());
        assertEquals(Integer.valueOf(0), report.getSafetyResult().getActualCount());
        assertEquals("applicable", report.getSafetyResult().getMode());
    }

    /** 反向对照 ✓：请求与 state 都没有优先规则时照旧通过，且不许凭空造出一条规则 ✗。 */
    @Test
    void shouldNotReportPriorityRuleWhenNeitherRequestNorStateHasOne() {
        PlanningStateDTO state = stateWithPersistedPriorityRule(null);
        PendingPlanningCommandReq request = fillRequestWithoutPriorityRules(2);

        PlanChangePostconditionReportDTO report = validator.validate(
                request, state, userGoalApplyResult());

        assertTrue(report.getSatisfied());
        assertEquals(Integer.valueOf(0), report.getPriorityRuleCount());
        for (int index = 0; index < report.getObjectiveResults().size(); index++) {
            assertFalse("priority_within_tier".equals(
                    report.getObjectiveResults().get(index).getObjectiveType()),
                    "没有规则就没有这条 objective ✗："
                            + report.getObjectiveResults().get(index).getObjectiveId());
        }
    }

    private PlanningStateDTO stateWithPersistedPriorityRule(String province) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        CandidateItemDTO prioritized = candidate("v-prioritized", province);
        CandidateItemDTO other = candidate("v-other", "北京");
        state.getCandidatePoolState().getItems().add(prioritized);
        state.getCandidatePoolState().getItems().add(other);
        state.getOrderedPlanState().getItems().add(orderedItem(prioritized.getVolunteerId(), "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem(other.getVolunteerId(), "稳"));
        if (province != null) {
            state.getConstraintState().getHardPlanningObjectives().getPriorityRules()
                    .add(priorityRule(province));
        }
        return state;
    }

    private CandidateItemDTO candidate(String volunteerId, String province) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setSchoolName(volunteerId);
        candidate.setProvinceName(province);
        return candidate;
    }

    private OrderedItemDTO orderedItem(String volunteerId, String tier) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        return item;
    }

    private PriorityRuleDTO priorityRule(String province) {
        PriorityRuleDTO rule = new PriorityRuleDTO();
        rule.setDomain("region");
        rule.setKey("province");
        rule.setValues(Lists.newArrayList(province));
        rule.setOrderingTarget("rank_before");
        rule.setScope("within_tier");
        return rule;
    }

    private PendingPlanningCommandReq fillRequestWithoutPriorityRules(int targetCount) {
        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(targetCount);
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId("ugp-fill");
        applyReq.setProposalSource("user_goal");
        applyReq.setSourceVersionGuard(12);
        applyReq.setUserGoalRequest(userGoal);
        PendingPlanningCommandReq request = new PendingPlanningCommandReq();
        request.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        request.setProposalApply(applyReq);
        return request;
    }

    private FixProposalApplyRes userGoalApplyResult() {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("ugp-fill");
        proposal.setProposalSource("user_goal");
        proposal.setStrategy("fill_missing_count");
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setProposal(proposal);
        return result;
    }

    @Test
    void shouldVerifyPersistedRangeAndActualCounts() {
        TierQuotaGoalRequestDTO requestGoal = rangeRequest(0, 2);
        Fixture fixture = fixture(requestGoal, 1, 2, 1);

        PlanChangePostconditionReportDTO report = validator.validate(
                fixture.request, fixture.state, fixture.applyResult);

        assertTrue(report.getSatisfied());
        assertTrue(report.getTierQuotaResult().getPlanSatisfied());
        assertTrue(report.getTierQuotaResult().getPersisted());
        assertEquals(Integer.valueOf(2), report.getTierQuotaResult()
                .getEffectiveGoal().getSprint().getMaxCount());
        assertEquals(Integer.valueOf(1), report.getTierQuotaResult()
                .getActualCounts().getSprintCount());
    }

    @Test
    void shouldVerifySubmittedAndCanonicalRatioState() {
        TierQuotaGoalRequestDTO requestGoal = ratioRequest(30, 40, 30);
        Fixture fixture = fixture(requestGoal, 1, 2, 1);

        PlanChangePostconditionReportDTO report = validator.validate(
                fixture.request, fixture.state, fixture.applyResult);

        assertEquals(Integer.valueOf(30), report.getTierQuotaResult()
                .getEffectiveGoal().getSprintWeight());
        assertEquals(Integer.valueOf(3), report.getTierQuotaResult()
                .getResolution().getCanonicalWeights().getSprintWeight());
        assertEquals(Integer.valueOf(2), report.getTierQuotaResult()
                .getResolution().getResolvedCounts().getStableCount());
    }

    @Test
    void shouldFailWhenFinalTierCountExceedsPersistedMaximum() {
        Fixture fixture = fixture(rangeRequest(0, 0), 1, 2, 1);

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validate(fixture.request, fixture.state, fixture.applyResult));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
    }

    @Test
    void shouldFailWhenPersistedResolutionMetadataDiffersFromProposal() {
        Fixture fixture = fixture(rangeRequest(0, 2), 1, 2, 1);
        TierAllocationSupport.confirmedResolution(fixture.state)
                .setObjectiveDigest("different-objective-digest");

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validate(fixture.request, fixture.state, fixture.applyResult));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
    }

    private Fixture fixture(TierQuotaGoalRequestDTO requested,
                            int sprint,
                            int stable,
                            int protect) {
        int targetCount = sprint + stable + protect;
        PlanningStateDTO empty = new PlanningStateDTO();
        TierAllocationSupport.CompiledTierAllocation compiled =
                TierAllocationSupport.compile(empty, requested, targetCount);
        TierCountsDTO frozenCounts = new TierCountsDTO();
        frozenCounts.setSprintCount(sprint);
        frozenCounts.setStableCount(stable);
        frozenCounts.setProtectCount(protect);
        compiled.getResolution().setResolvedCounts(frozenCounts);
        compiled.getResolution().setObjectiveDigest("fixture-objective-digest");
        compiled.getResolution().setSolverVersion("ojalgo-48.4.2-m2");

        PlanningStateDTO state = stateWithTiers(sprint, stable, protect);
        TierAllocationSupport.persist(
                state, compiled.getEffectiveSourceGoal(), compiled.getResolution());
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(targetCount);

        TierQuotaChangeDTO change = new TierQuotaChangeDTO();
        change.setRequestedGoal(requested);
        change.setEffectiveGoal(compiled.getEffectiveSourceGoal());
        change.setResolution(compiled.getResolution());
        change.setStateChanged(true);
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("m2-tier-proposal");
        proposal.setProposalSource("user_goal");
        proposal.setStrategy("fill_missing_count");
        proposal.setTierQuotaChange(change);

        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(targetCount);
        userGoal.setPersistTargetCount(false);
        userGoal.setTierQuotaGoal(requested);
        FixProposalApplyReq apply = new FixProposalApplyReq();
        apply.setProposalId(proposal.getProposalId());
        apply.setProposalSource("user_goal");
        apply.setUserGoalRequest(userGoal);
        PendingPlanningCommandReq command = new PendingPlanningCommandReq();
        command.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        command.setProposalApply(apply);

        FixProposalApplyRes applyResult = new FixProposalApplyRes();
        applyResult.setStatus("applied");
        applyResult.setProposal(proposal);
        applyResult.setState(state);
        return new Fixture(command, state, applyResult);
    }

    private PlanningStateDTO stateWithTiers(int sprint, int stable, int protect) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(sprint + stable + protect);
        int index = 0;
        index = addTier(state, index, sprint, "冲");
        index = addTier(state, index, stable, "稳");
        addTier(state, index, protect, "保");
        return state;
    }

    private int addTier(PlanningStateDTO state, int index, int count, String tier) {
        for (int offset = 0; offset < count; offset++) {
            String id = "v-" + index++;
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(id);
            candidate.setTier(tier);
            state.getCandidatePoolState().getItems().add(candidate);
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId(id);
            item.setTier(tier);
            state.getOrderedPlanState().getItems().add(item);
        }
        return index;
    }

    private TierQuotaGoalRequestDTO rangeRequest(int minimum, int maximum) {
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        result.setType("count_ranges");
        result.setUpdateMode("replace");
        TierCountRangeDTO sprint = new TierCountRangeDTO();
        sprint.setMinCount(minimum);
        sprint.setMaxCount(maximum);
        result.setSprint(sprint);
        return result;
    }

    private TierQuotaGoalRequestDTO ratioRequest(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        result.setType("ratios");
        result.setUpdateMode("replace");
        result.setSprintWeight(sprint);
        result.setStableWeight(stable);
        result.setProtectWeight(protect);
        return result;
    }

    private static final class Fixture {
        private final PendingPlanningCommandReq request;
        private final PlanningStateDTO state;
        private final FixProposalApplyRes applyResult;

        private Fixture(PendingPlanningCommandReq request,
                        PlanningStateDTO state,
                        FixProposalApplyRes applyResult) {
            this.request = request;
            this.state = state;
            this.applyResult = applyResult;
        }
    }
}
