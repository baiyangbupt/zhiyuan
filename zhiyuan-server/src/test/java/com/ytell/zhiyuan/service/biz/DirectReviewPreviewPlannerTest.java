package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

class DirectReviewPreviewPlannerTest {
    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.EnumSource(ReviewProtectionTestSupport.Carrier.class)
    void rejectsProtectionAcrossAllGroupCarriers(ReviewProtectionTestSupport.Carrier carrier) {
        groupFixture();
        carrier.protect(state);
        String baseline = JSON.toJSONString(state);

        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            throw new AssertionError("protected plans must not reach reevaluation");
        });

        assertNoFrozen(proposal, "review_fix_order_locked");
        assertEquals(baseline, JSON.toJSONString(state));
    }

    private final DirectReviewPreviewPlanner planner = new DirectReviewPreviewPlanner();
    private PlanningStateDTO state;
    private EvaluationFindingDTO finding;
    private List<CandidateItemDTO> candidates;

    @BeforeEach
    void fixture() {
        state = new PlanningStateDTO();
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        candidates = Lists.newArrayList(candidate("high", 90D), candidate("low", 30D), candidate("mid", 60D));
        state.getCandidatePoolState().setItems(candidates);
        for (int index = 0; index < candidates.size(); index++) {
            CandidateItemDTO candidate = candidates.get(index);
            DraftItemDTO selected = new DraftItemDTO();
            selected.setVolunteerId(candidate.getVolunteerId());
            selected.setTier("protect");
            state.getWorkingPlanState().getItems().add(selected);
            OrderedItemDTO ordered = new OrderedItemDTO();
            ordered.setVolunteerId(candidate.getVolunteerId());
            ordered.setTier("protect");
            ordered.setPosition(index + 1);
            state.getOrderedPlanState().getItems().add(ordered);
        }
        finding = new EvaluationFindingDTO();
        finding.setCode("probability_inversion");
        finding.setResultStatus("fail");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("sort_by_probability");
        command.setSourceStrategy("sort_by_probability");
        command.setEvaluationVersion("before-evaluation");
        command.setCommandDigest("command-digest");
        for (CandidateItemDTO candidate : candidates) {
            EvaluationEntryRefDTO ref = new EvaluationEntryRefDTO();
            ref.setLevel("volunteer");
            ref.setId(candidate.getVolunteerId());
            command.getReorderTargets().add(ref);
        }
        finding.setSuggestedCommand(command);
    }

    @Test
    void freezesActualSelectionOrderAndFactsWithoutMutatingInputOrPretendingSolverExecution() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = plan();
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertNull(proposal.getSolverResult());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals(Lists.newArrayList("high", "low", "mid"), proposal.getFrozenReviewPlan().getSelectedEntityIds());
        assertEquals(Lists.newArrayList("low", "mid", "high"), proposal.getFrozenReviewPlan().getOrderedEntityIds());
        assertEquals(proposal.getFrozenReviewPlan().getOrderedEntityIds(),
                proposal.getFrozenReviewPlan().getOrderedPlan().getItems().stream()
                        .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));
        assertEquals(3, proposal.getFrozenReviewPlan().getSelectedFacts().size());
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getCanonicalObjectiveDigest());
        assertEquals(0, proposal.getDryRunResult().getAddVolunteerCount());
        assertEquals(baseline, JSON.toJSONString(state));
        proposal.getFrozenReviewPlan().getSelectedFacts().get(0).setProvinceName("changed");
        proposal.getFrozenReviewPlan().getWorkingPlan().getItems().clear();
        assertEquals(baseline, JSON.toJSONString(state));
    }

    @Test
    void confirmableModePromotesFrozenProposalToReadyWithExecutableCommand() {
        DirectReviewPreviewPlanner confirmable = new DirectReviewPreviewPlanner(true);
        FixProposalDTO proposal = confirmable.plan(state, candidates, finding,
                after -> review("pass", "pass"));

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertTrue(finding.getSuggestedCommand().getExecutable());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertNotNull(proposal.getFrozenReviewPlan());
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getPlanContentDigest());
        assertEquals(Integer.valueOf(7), proposal.getSourceVersionGuard());
        assertNull(proposal.getBlockingReason());
        assertFalse(proposal.getBlockingReasonCodes().contains("review_fix_prepare_unavailable"));
        assertEquals(Lists.newArrayList("low", "mid", "high"),
                proposal.getFrozenReviewPlan().getOrderedEntityIds());
    }

    @Test
    void previewModeKeepsTheOriginalPreviewOnlyContract() {
        FixProposalDTO proposal = plan();
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertFalse(finding.getSuggestedCommand().getExecutable());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertEquals("review_fix_prepare_unavailable", proposal.getBlockingReason());
        assertTrue(proposal.getBlockingReasonCodes().contains("review_fix_prepare_unavailable"));
    }

    @Test
    void confirmableModeStillBlocksWhenPostconditionFails() {
        DirectReviewPreviewPlanner confirmable = new DirectReviewPreviewPlanner(true);
        FixProposalDTO proposal = confirmable.plan(state, candidates, finding,
                after -> review("fail", "pass"));

        assertNotEquals("ready", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertNull(proposal.getFrozenReviewPlan());
        assertEquals("repair_goal_unreachable", proposal.getBlockingReason());
    }

    @Test
    void stableDigestsBindSelectedFactsButNotUnrelatedPoolOrder() {
        FixProposalDTO first = plan();
        assertEquals(first.getProposalId(), plan().getProposalId());
        assertEquals(first.getPreviewDigest(), plan().getPreviewDigest());
        candidates.add(candidate("unselected", 50D));
        assertEquals(first.getPreviewDigest(), plan().getPreviewDigest());
        candidates.get(0).setTuitionPerYear(18000);
        assertNotEquals(first.getPreviewDigest(), plan().getPreviewDigest());
    }

    @Test
    void refusesMissingDuplicateOrNonFiniteCandidateFacts() {
        candidates.remove(0);
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        fixture();
        candidates.add(candidate("high", 70D));
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        fixture();
        candidates.get(0).setAdmissionRatio(Double.NaN);
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        fixture();
        candidates.get(0).setAdmissionRatio(null);
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
    }

    @Test
    void refusesGroupModeWithoutUnitsAndMajorModePinnedLockedAndInconsistentWorkingSelection() {
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
        fixture();
        state.getOrderedPlanState().getItems().get(0).setPinned(true);
        assertNoFrozen(plan(), "review_fix_order_locked");
        fixture();
        state.getWorkingPlanState().getItems().get(0).setLocked(true);
        assertNoFrozen(plan(), "review_fix_order_locked");
        fixture();
        state.getWorkingPlanState().getItems().remove(0);
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
    }

    @Test
    void groupInversionFreezesReorderedUnitsFlattenedItemsAndUnitFacts() {
        groupFixture();
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = new DirectReviewPreviewPlanner(true)
                .plan(state, candidates, finding, after -> review("pass", "pass"));

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(Lists.newArrayList("u-high", "u-mid", "u-low"), frozen.getSelectedEntityIds());
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"), frozen.getOrderedEntityIds());
        assertEquals(frozen.getOrderedEntityIds(), frozen.getOrderedPlan().getUnits().stream()
                .map(OrderedUnitDTO::getUnitId).collect(Collectors.toList()));
        assertEquals(Lists.newArrayList("u-low-v", "u-mid-v", "u-high-v"),
                frozen.getOrderedPlan().getItems().stream()
                        .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));
        for (int index = 0; index < 3; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getUnits().get(index).getPosition());
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getItems().get(index).getPosition());
        }
        assertEquals(3, frozen.getWorkingPlan().getUnits().size());
        assertEquals(3, frozen.getWorkingPlan().getItems().size());
        assertEquals(3, frozen.getSelectedFacts().size());
        assertEquals("unit", proposal.getActions().get(0).getLevel());
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"),
                proposal.getActions().get(0).getUnitIds());
        assertTrue(proposal.getActions().get(0).getVolunteerIds().isEmpty());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getBeforeUnitTotal());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getAfterUnitTotal());
        assertEquals(new java.util.LinkedHashSet<>(Lists.newArrayList("u-high", "u-mid", "u-low")),
                proposal.getDryRunResult().getBeforeUnitIds());
        assertNotNull(proposal.getPreviewDigest());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals(DirectReviewPreviewPlanner.factsDigestForUnits(
                        frozen.getSelectedEntityIds(), frozen.getOrderedPlan().getUnits(), candidates),
                frozen.getFactsDigest());
        assertEquals(baseline, JSON.toJSONString(state), "预览不得改动输入状态");
    }

    @Test
    void unitModeIsDetectedFromOrderedUnitsEvenWithoutGroupVolunteerModel() {
        groupFixture();
        state.getCandidatePoolState().setVolunteerModel("major");
        FixProposalDTO proposal = new DirectReviewPreviewPlanner(true)
                .plan(state, candidates, finding, after -> review("pass", "pass"));
        assertEquals("ready", proposal.getStatus());
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"),
                proposal.getFrozenReviewPlan().getOrderedEntityIds());
    }

    @Test
    void unitRatioFallsBackToSchoolEnrollRatioAndRejectsNonFinite() {
        groupFixture();
        for (OrderedUnitDTO unit : state.getOrderedPlanState().getUnits()) {
            unit.setAdmissionRatio(null);
        }
        FixProposalDTO proposal = new DirectReviewPreviewPlanner(true)
                .plan(state, candidates, finding, after -> review("pass", "pass"));
        assertEquals("ready", proposal.getStatus());
        assertEquals(Lists.newArrayList("u-low", "u-mid", "u-high"),
                proposal.getFrozenReviewPlan().getOrderedEntityIds());

        groupFixture();
        state.getOrderedPlanState().getUnits().get(0).setAdmissionRatio(Double.NaN);
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        groupFixture();
        for (OrderedUnitDTO unit : state.getOrderedPlanState().getUnits()) {
            unit.setAdmissionRatio(null);
            unit.setSchoolEnrollRatio(null);
        }
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
    }

    @Test
    void unitModeRejectsLocksPinsPriorityRulesAndInconsistentUnits() {
        groupFixture();
        state.getOrderedPlanState().getUnits().get(0).setLocked(true);
        assertNoFrozen(plan(), "review_fix_order_locked");
        groupFixture();
        state.getOrderedPlanState().getUnits().get(0).setPinned(true);
        assertNoFrozen(plan(), "review_fix_order_locked");
        groupFixture();
        state.getOrderedPlanState().getUnits().get(0).setPinnedPosition(2);
        assertNoFrozen(plan(), "review_fix_order_locked");
        groupFixture();
        state.getWorkingPlanState().getUnits().get(0).setLocked(true);
        assertNoFrozen(plan(), "review_fix_order_locked");
        groupFixture();
        PriorityRuleDTO priority = new PriorityRuleDTO();
        priority.setDomain("region");
        priority.setKey("province");
        priority.getValues().add("浙江");
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().add(priority);
        assertNoFrozen(plan(), "review_fix_direct_unsupported");
        groupFixture();
        state.getWorkingPlanState().getUnits().remove(0);
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
        groupFixture();
        state.getOrderedPlanState().getUnits().get(0).setMajorItems(Lists.newArrayList(major("missing-v")));
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
    }

    @Test
    void unitModeRequiresUnitLevelReorderTargetsAndContiguousPositions() {
        groupFixture();
        finding.getSuggestedCommand().getReorderTargets().get(0).setLevel("volunteer");
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
        groupFixture();
        state.getOrderedPlanState().getUnits().get(0).setPosition(2);
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
        groupFixture();
        finding.getSuggestedCommand().getReorderTargets().get(0).setId("unknown-unit");
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
    }

    @Test
    void rejectsInvalidPositionsAndUnauthorizedReferences() {
        state.getOrderedPlanState().getItems().get(0).setPosition(2);
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
        fixture();
        finding.getSuggestedCommand().getReorderTargets().get(0).setId("unknown");
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
    }

    @Test
    void preflightUsesRecomputedOriginalProbeAndHardFacts() {
        FixProposalDTO failed = planner.plan(state, candidates, finding, after -> review("fail", "pass"));
        assertNoFrozen(failed, "repair_goal_unreachable");
        failed = planner.plan(state, candidates, finding, after -> review("pass", "fail"));
        assertNoFrozen(failed, "hard_constraints_unsatisfied");
        failed = planner.plan(state, candidates, finding, after -> new ReviewStateDTO());
        assertNoFrozen(failed, "review_fix_evaluation_unavailable");
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("浙江");
        assertNoFrozen(plan(), "hard_constraints_unsatisfied");
    }

    @Test
    void neverMovesEntriesOutsideAuthorizedScopeOrMutatesThroughReevaluation() {
        finding.getSuggestedCommand().getReorderTargets().remove(2);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals("mid", after.getOrderedPlanState().getItems().get(2).getVolunteerId());
            after.getConstraintState().getHardConstraints().getMustExcludeRegions().add("changed");
            return review("fail", "pass");
        });
        assertNoFrozen(proposal, "repair_goal_unreachable");
        assertTrue(state.getConstraintState().getHardConstraints().getMustExcludeRegions().isEmpty());
    }

    @Test
    void returnsNothingForSearchOrUncompiledFindings() {
        finding.getSuggestedCommand().setStrategy("add_safety_items");
        assertNull(plan());
        finding.setSuggestedCommand(null);
        assertNull(plan());
    }

    @Test
    void malformedCollectionsAndUnimplementedPriorityOrderingFailClosed() {
        state.getOrderedPlanState().setItems(null);
        assertNoFrozen(plan(), "review_fix_selection_incomplete");
        fixture();
        PriorityRuleDTO priority = new PriorityRuleDTO();
        priority.setDomain("region");
        priority.setKey("province");
        priority.getValues().add("浙江");
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().add(priority);
        assertNoFrozen(plan(), "review_fix_direct_unsupported");
    }

    @Test
    void exceptionsDuringFreshEvaluationFailClosed() {
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            throw new IllegalStateException("unavailable facts");
        });
        assertNoFrozen(proposal, "review_fix_evaluation_unavailable");
    }

    @Test
    void unresolvedHardIdentityAndNameConstraintsCannotBecomeGreen() {
        state.getConstraintState().getHardConstraints().getMustIncludeMajorIds().add("required");
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        candidates.forEach(candidate -> candidate.setMajorId("required"));
        assertNotNull(plan().getFrozenReviewPlan());
        candidates.get(0).setMajorId("0");
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        fixture();
        state.getConstraintState().getHardConstraints().getMustExcludeRegionIds().add("city-id");
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        fixture();
        state.getConstraintState().getHardConstraints().getMustExcludeMajors().add("医学");
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
        fixture();
        state.getConstraintState().getHardConstraints().getMustExcludeSchools().add("民办");
        assertNoFrozen(plan(), "review_fix_facts_incomplete");
    }

    private void groupFixture() {
        state = new PlanningStateDTO();
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        candidates = Lists.newArrayList();
        String[] unitIds = {"u-high", "u-mid", "u-low"};
        double[] ratios = {90D, 60D, 30D};
        for (int index = 0; index < unitIds.length; index++) {
            String volunteerId = unitIds[index] + "-v";
            CandidateItemDTO candidate = candidate(volunteerId, ratios[index]);
            candidate.setSchoolEnrollRatio(ratios[index]);
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);

            DraftUnitDTO workingUnit = new DraftUnitDTO();
            workingUnit.setUnitId(unitIds[index]);
            workingUnit.setTier("protect");
            workingUnit.getMajorItems().add(major(volunteerId));
            state.getWorkingPlanState().getUnits().add(workingUnit);

            DraftItemDTO selected = new DraftItemDTO();
            selected.setVolunteerId(volunteerId);
            selected.setTier("protect");
            state.getWorkingPlanState().getItems().add(selected);

            OrderedUnitDTO orderedUnit = new OrderedUnitDTO();
            orderedUnit.setUnitId(unitIds[index]);
            orderedUnit.setPosition(index + 1);
            orderedUnit.setTier("protect");
            orderedUnit.setSchoolName("学校" + (index + 1) + "第01组");
            orderedUnit.setProvinceName("浙江");
            orderedUnit.setAdmissionRatio(ratios[index]);
            orderedUnit.setSchoolEnrollRatio(ratios[index]);
            orderedUnit.getMajorItems().add(major(volunteerId));
            state.getOrderedPlanState().getUnits().add(orderedUnit);

            OrderedItemDTO ordered = new OrderedItemDTO();
            ordered.setVolunteerId(volunteerId);
            ordered.setTier("protect");
            ordered.setPosition(index + 1);
            state.getOrderedPlanState().getItems().add(ordered);
        }
        finding = new EvaluationFindingDTO();
        finding.setCode("probability_inversion");
        finding.setResultStatus("fail");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("sort_by_probability");
        command.setSourceStrategy("sort_by_probability");
        command.setEvaluationVersion("before-evaluation");
        command.setCommandDigest("command-digest");
        for (String unitId : unitIds) {
            EvaluationEntryRefDTO ref = new EvaluationEntryRefDTO();
            ref.setLevel("unit");
            ref.setId(unitId);
            command.getReorderTargets().add(ref);
        }
        finding.setSuggestedCommand(command);
    }

    private PlanningUnitMajorDTO major(String volunteerId) {
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        return major;
    }

    private FixProposalDTO plan() {
        return planner.plan(state, candidates, finding, after -> review("pass", "pass"));
    }

    private void assertNoFrozen(FixProposalDTO proposal, String reason) {
        assertNotNull(proposal);
        assertNotEquals("ready", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals(reason, proposal.getBlockingReason());
        assertNull(proposal.getFrozenReviewPlan());
    }

    private ReviewStateDTO review(String status, String hardStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible("pass".equals(hardStatus));
        EvaluationFindingDTO probe = new EvaluationFindingDTO();
        probe.setCode("probability_inversion");
        probe.setResultStatus(status);
        probe.setRuleStrength("soft");
        EvaluationFindingDTO hard = new EvaluationFindingDTO();
        hard.setCode("count_validation_hard");
        hard.setResultStatus(hardStatus);
        hard.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(probe, hard));
        return review;
    }

    private CandidateItemDTO candidate(String id, Double ratio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setAdmissionRatio(ratio);
        candidate.setProvinceName("浙江");
        candidate.setTier("protect");
        return candidate;
    }
}
