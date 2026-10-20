package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 组模式 Search 切片：44 个专业组、目标 46 组 → count_target fail →
 * fill_missing_count；目标数按 unit 计，物化后 working/ordered units 均为 46。
 */
class GroupSearchReviewPreviewPlannerTest {
    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.EnumSource(ReviewProtectionTestSupport.Carrier.class)
    void rejectsProtectionAcrossAllGroupCarriers(ReviewProtectionTestSupport.Carrier carrier) {
        carrier.protect(state);
        String baseline = JSON.toJSONString(state);

        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            throw new AssertionError("protected plans must not reach reevaluation");
        }, true);

        assertEquals("review_fix_order_locked", proposal.getBlockingReason());
        assertFalse(proposal.getRequiresConfirmation());
        assertNull(proposal.getFrozenReviewPlan());
        assertEquals(baseline, JSON.toJSONString(state));
    }

    private static final int CURRENT_UNITS = 44;
    private static final int TARGET_UNITS = 46;
    private static final int EXTRA_UNITS = 4;
    private static final int MAJORS_PER_UNIT = 2;
    private static final int TOTAL_ITEMS = TARGET_UNITS * MAJORS_PER_UNIT;

    private final SearchReviewPreviewPlanner planner = new SearchReviewPreviewPlanner();
    private PlanningStateDTO state;
    private EvaluationFindingDTO finding;
    private List<CandidateItemDTO> candidates;

    @BeforeEach
    void fixture() {
        state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(TARGET_UNITS);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        // 550 分 → 本省保底要求 2 组；前两组是浙江 protect，安全垫已满足。
        state.getCandidatePoolState().setUserScore(550);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(TARGET_UNITS);

        candidates = Lists.newArrayList();
        for (int unitIndex = 1; unitIndex <= CURRENT_UNITS + EXTRA_UNITS; unitIndex++) {
            String unitId = String.format("u%03d", unitIndex);
            boolean current = unitIndex <= CURRENT_UNITS;
            boolean local = unitIndex <= 2;
            DraftUnitDTO workingUnit = current ? new DraftUnitDTO() : null;
            if (workingUnit != null) {
                workingUnit.setUnitId(unitId);
                workingUnit.setTier("protect");
                workingUnit.setSchoolName("学校" + unitIndex + "第01组");
            }
            OrderedUnitDTO orderedUnit = current ? new OrderedUnitDTO() : null;
            if (orderedUnit != null) {
                orderedUnit.setUnitId(unitId);
                orderedUnit.setPosition(unitIndex);
                orderedUnit.setTier("protect");
                orderedUnit.setSchoolName("学校" + unitIndex + "第01组");
                orderedUnit.setProvinceName(local ? "浙江" : "江苏");
                orderedUnit.setAdmissionRatio(65D);
                orderedUnit.setSchoolEnrollRatio(60D);
            }
            for (int majorIndex = 1; majorIndex <= MAJORS_PER_UNIT; majorIndex++) {
                String volunteerId = unitId + "-v" + majorIndex;
                CandidateItemDTO candidate = new CandidateItemDTO();
                candidate.setVolunteerId(volunteerId);
                // planSchoolDataId 即 group entityId：物化时按 unit 聚合。
                candidate.setPlanSchoolDataId(unitId);
                candidate.setSchoolId("s" + unitId);
                candidate.setSchoolName("学校" + unitIndex + "第01组");
                candidate.setDisplaySchoolName("学校" + unitIndex + "第01组");
                candidate.setMajorName("专业" + unitIndex + "-" + majorIndex);
                candidate.setMajorCategory("工学");
                candidate.setTier("protect");
                candidate.setProvinceName(local ? "浙江" : "江苏");
                candidate.setAdmissionRatio(65D);
                candidate.setSchoolEnrollRatio(60D);
                candidate.setFinalScore(80D);
                candidate.setIntentScore(40D);
                candidate.setTuitionPerYear(5000);
                candidates.add(candidate);
                state.getCandidatePoolState().getItems().add(candidate);
                if (!current) {
                    continue;
                }
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(volunteerId);
                selected.setTier("protect");
                selected.setSchoolName(candidate.getSchoolName());
                selected.setMajorName(candidate.getMajorName());
                state.getWorkingPlanState().getItems().add(selected);

                PlanningUnitMajorDTO workingMajor = new PlanningUnitMajorDTO();
                workingMajor.setVolunteerId(volunteerId);
                workingMajor.setMajorName(candidate.getMajorName());
                workingMajor.setTier("protect");
                workingUnit.getMajorItems().add(workingMajor);

                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(volunteerId);
                ordered.setTier("protect");
                ordered.setSchoolName(candidate.getSchoolName());
                ordered.setMajorName(candidate.getMajorName());
                ordered.setPosition(state.getOrderedPlanState().getItems().size() + 1);
                state.getOrderedPlanState().getItems().add(ordered);

                PlanningUnitMajorDTO orderedMajor = new PlanningUnitMajorDTO();
                orderedMajor.setVolunteerId(volunteerId);
                orderedMajor.setMajorName(candidate.getMajorName());
                orderedMajor.setTier("protect");
                orderedUnit.getMajorItems().add(orderedMajor);
            }
            if (workingUnit != null) {
                state.getWorkingPlanState().getUnits().add(workingUnit);
                state.getOrderedPlanState().getUnits().add(orderedUnit);
            }
        }

        finding = new EvaluationFindingDTO();
        finding.setCode("count_target");
        finding.setResultStatus("fail");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("fill_missing_count");
        command.setSourceStrategy("count_target");
        command.setLevel("unit");
        command.setTargetCount(TARGET_UNITS);
        command.setEvaluationVersion("before-evaluation");
        command.setCommandDigest("group-command-digest");
        finding.setSuggestedCommand(command);
    }

    @Test
    void fillsGroupCountTargetInUnitsAndFreezesUnitCarriers() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals(TARGET_UNITS, after.getOrderedPlanState().getUnits().size(),
                    "目标数按 unit 计，不是 item 数");
            assertEquals(TOTAL_ITEMS, after.getOrderedPlanState().getItems().size());
            assertEquals(TOTAL_ITEMS, after.getWorkingPlanState().getItems().size());
            assertEquals(TARGET_UNITS, after.getWorkingPlanState().getUnits().size());
            Set<String> units = after.getOrderedPlanState().getUnits().stream()
                    .map(OrderedUnitDTO::getUnitId).collect(Collectors.toCollection(LinkedHashSet::new));
            assertEquals(TARGET_UNITS, units.size());
            return review("pass");
        }, true);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("review_check", proposal.getProposalSource());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("count_target", proposal.getSourceStrategy());
        assertEquals("count_target", proposal.getFindingCode());
        assertEquals(Integer.valueOf(7), proposal.getSourceVersionGuard());
        assertNotNull(proposal.getCanonicalObjectiveDigest());
        assertNotNull(proposal.getHardObjectiveVersion());
        assertEquals("ready", proposal.getSolverResult().getStatus());
        assertEquals(TARGET_UNITS, proposal.getSolverResult().getSelectedEntityIds().size());
        assertEquals(Integer.valueOf(CURRENT_UNITS), proposal.getTargetCountBefore());
        assertEquals(Integer.valueOf(TARGET_UNITS), proposal.getTargetCountAfter());
        assertEquals(Integer.valueOf(2), proposal.getAddedUnitCount());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("count_target", proposal.getFindingPostcondition().getFindingCode());

        assertFalse(proposal.getActions().isEmpty());
        for (FixProposalActionDTO action : proposal.getActions()) {
            assertEquals("unit", action.getLevel());
        }
        FixProposalActionDTO fill = proposal.getActions().stream()
                .filter(action -> "fill_total_count".equals(action.getActionType()))
                .findFirst().orElse(null);
        assertNotNull(fill);
        assertEquals(2, fill.getUnitIds().size());

        assertEquals(Integer.valueOf(CURRENT_UNITS), proposal.getDryRunResult().getBeforeUnitTotal());
        assertEquals(Integer.valueOf(TARGET_UNITS), proposal.getDryRunResult().getAfterUnitTotal());
        assertEquals(CURRENT_UNITS, proposal.getDryRunResult().getBeforeUnitIds().size());
        assertEquals(TARGET_UNITS, proposal.getDryRunResult().getAfterUnitIds().size());

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(TARGET_UNITS, frozen.getSelectedEntityIds().size());
        assertEquals(TARGET_UNITS, frozen.getOrderedEntityIds().size());
        assertEquals(TARGET_UNITS, frozen.getWorkingPlan().getUnits().size());
        assertEquals(TARGET_UNITS, frozen.getOrderedPlan().getUnits().size());
        assertEquals(TOTAL_ITEMS, frozen.getWorkingPlan().getItems().size());
        assertEquals(TOTAL_ITEMS, frozen.getOrderedPlan().getItems().size());
        assertEquals(TOTAL_ITEMS, frozen.getSelectedFacts().size());
        assertEquals(frozen.getOrderedEntityIds(), frozen.getOrderedPlan().getUnits().stream()
                .map(OrderedUnitDTO::getUnitId).collect(Collectors.toList()));
        for (int index = 0; index < TARGET_UNITS; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getUnits().get(index).getPosition());
        }
        for (int index = 0; index < TOTAL_ITEMS; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getItems().get(index).getPosition());
        }
        assertEquals(DirectReviewPreviewPlanner.factsDigestForUnits(
                        frozen.getSelectedEntityIds(), frozen.getOrderedPlan().getUnits(), candidates),
                frozen.getFactsDigest());
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getPlanContentDigest());
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void detectsGroupModeFromOrderedUnitsWhenVolunteerModelIsMissing() {
        state.getCandidatePoolState().setVolunteerModel(null);
        FixProposalDTO proposal = planner.plan(state, candidates, finding,
                after -> review("pass"), true);
        assertEquals("ready", proposal.getStatus());
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(TARGET_UNITS, proposal.getFrozenReviewPlan().getOrderedPlan().getUnits().size());
    }

    @Test
    void fillsGroupCoverageInUnitsAtSameCount() {
        for (CandidateItemDTO candidate : candidates) {
            if ("u045".equals(candidate.getPlanSchoolDataId())
                    || "u046".equals(candidate.getPlanSchoolDataId())) {
                candidate.setProvinceName("浙江");
            }
        }
        finding.setCode("coverage:0");
        finding.getSuggestedCommand().setStrategy("must_include_scope");
        finding.getSuggestedCommand().setApplyStrategy("fill_missing_count");
        finding.getSuggestedCommand().setTargetCount(CURRENT_UNITS);
        CoverageRequirementDTO requirement = new CoverageRequirementDTO();
        requirement.setDomain("region");
        requirement.setKey("province");
        requirement.setValues(Lists.newArrayList("浙江"));
        requirement.setMinCount(4);
        finding.getSuggestedCommand().getCoverageRequirements().add(requirement);

        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            List<OrderedUnitDTO> units = after.getOrderedPlanState().getUnits();
            assertEquals(CURRENT_UNITS, units.size(), "coverage 等量替换不改变 unit 数");
            long local = units.stream()
                    .filter(unit -> "浙江".equals(unit.getProvinceName()))
                    .count();
            assertEquals(4, local, "必须补齐浙江覆盖到 4 组");
            return coverageReview("pass");
        }, true);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("coverage:0", proposal.getFindingCode());
        assertEquals("补齐覆盖要求预览", proposal.getTitle());
        assertEquals(CURRENT_UNITS, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("coverage:0", proposal.getFindingPostcondition().getFindingCode());
        for (FixProposalActionDTO action : proposal.getActions()) {
            assertEquals("unit", action.getLevel());
            assertEquals("coverage:0", action.getSourceCheckCode());
        }
        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(CURRENT_UNITS, frozen.getOrderedPlan().getUnits().size());
        assertEquals(CURRENT_UNITS * MAJORS_PER_UNIT, frozen.getOrderedPlan().getItems().size());
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void rejectsNoChangeLocksAndCoverageWithoutRequirementsInUnitMode() {
        finding.getSuggestedCommand().setTargetCount(CURRENT_UNITS);
        FixProposalDTO noChange = planner.plan(state, candidates, finding,
                after -> review("pass"), false);
        assertNotNull(noChange);
        assertEquals("review_fix_search_no_change", noChange.getBlockingReason());
        assertNull(noChange.getFrozenReviewPlan());

        finding.getSuggestedCommand().setTargetCount(TARGET_UNITS);
        state.getOrderedPlanState().getUnits().get(0).setPinned(true);
        FixProposalDTO locked = planner.plan(state, candidates, finding,
                after -> review("pass"), false);
        assertEquals("review_fix_order_locked", locked.getBlockingReason());
        state.getOrderedPlanState().getUnits().get(0).setPinned(false);

        finding.setCode("coverage:0");
        finding.getSuggestedCommand().setStrategy("must_include_scope");
        finding.getSuggestedCommand().setApplyStrategy("fill_missing_count");
        FixProposalDTO coverage = planner.plan(state, candidates, finding,
                after -> coverageReview("pass"), false);
        assertEquals("review_fix_coverage_unavailable", coverage.getBlockingReason());
    }

    private ReviewStateDTO coverageReview(String coverageStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-group-coverage-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible(true);
        EvaluationFindingDTO coverage = new EvaluationFindingDTO();
        coverage.setCode("coverage:0");
        coverage.setResultStatus(coverageStatus);
        coverage.setRuleStrength("soft");
        EvaluationFindingDTO hard = new EvaluationFindingDTO();
        hard.setCode("count_validation_hard");
        hard.setResultStatus("pass");
        hard.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(coverage, hard));
        return review;
    }

    private ReviewStateDTO review(String countStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-group-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible(true);
        EvaluationFindingDTO count = new EvaluationFindingDTO();
        count.setCode("count_target");
        count.setResultStatus(countStatus);
        count.setRuleStrength("soft");
        EvaluationFindingDTO hard = new EvaluationFindingDTO();
        hard.setCode("count_validation_hard");
        hard.setResultStatus("pass");
        hard.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(count, hard));
        return review;
    }
}
