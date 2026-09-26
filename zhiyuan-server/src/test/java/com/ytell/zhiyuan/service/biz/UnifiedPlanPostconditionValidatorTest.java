package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaChangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
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
        // 组内专业只带得出 `majorName`（`PlanningUnitMajorDTO` 没有 category/discipline ✗），
        // 所以组级匹配本来就走名字 ✓——粗粒度字段的放大问题只发生在候选级 ✓。
        major.setMajorName(majorName);
        unit.setMajorItems(Lists.newArrayList(major));
        return unit;
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
