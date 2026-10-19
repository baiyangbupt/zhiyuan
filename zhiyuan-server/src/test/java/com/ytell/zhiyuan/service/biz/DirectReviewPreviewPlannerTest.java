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
    void refusesGroupModePinnedLockedAndInconsistentWorkingSelection() {
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        assertNoFrozen(plan(), "review_fix_direct_unsupported");
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
