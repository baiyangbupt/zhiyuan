package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Search 首个切片：count_target fail → fill_missing_count，复用 user-goal staged solver
 * 生成冻结方案，postcondition 通过后才允许进入确认链。
 */
class SearchReviewPreviewPlannerTest {
    private static final int CURRENT = 80;
    private static final int TARGET = 82;

    private final SearchReviewPreviewPlanner planner = new SearchReviewPreviewPlanner();
    private PlanningStateDTO state;
    private EvaluationFindingDTO finding;
    private List<CandidateItemDTO> candidates;

    @BeforeEach
    void fixture() {
        state = new PlanningStateDTO();
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(TARGET);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(TARGET);
        candidates = Lists.newArrayList();
        for (int index = 1; index <= CURRENT + 4; index++) {
            CandidateItemDTO candidate = candidate(String.format("v%03d", index));
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);
            if (index <= CURRENT) {
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(candidate.getVolunteerId());
                selected.setTier("protect");
                state.getWorkingPlanState().getItems().add(selected);
                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(candidate.getVolunteerId());
                ordered.setTier("protect");
                ordered.setPosition(index);
                state.getOrderedPlanState().getItems().add(ordered);
            }
        }
        finding = new EvaluationFindingDTO();
        finding.setCode("count_target");
        finding.setResultStatus("fail");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("fill_missing_count");
        command.setSourceStrategy("count_target");
        command.setLevel("volunteer");
        command.setTargetCount(TARGET);
        command.setEvaluationVersion("before-evaluation");
        command.setCommandDigest("command-digest");
        finding.setSuggestedCommand(command);
    }

    @Test
    void freezesSolverSelectionForCountTargetAndPassesPostcondition() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = plan(false);

        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals("review_check", proposal.getProposalSource());
        assertNotNull(proposal.getSolverResult());
        assertEquals("ready", proposal.getSolverResult().getStatus());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
        assertNotNull(proposal.getCanonicalObjectiveDigest());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("review_fix_prepare_unavailable", proposal.getBlockingReason());

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(TARGET, frozen.getSelectedEntityIds().size());
        assertEquals(TARGET, frozen.getOrderedEntityIds().size());
        assertEquals(TARGET, frozen.getWorkingPlan().getItems().size());
        assertEquals(TARGET, frozen.getOrderedPlan().getItems().size());
        assertEquals(TARGET, frozen.getSelectedFacts().size());
        for (int index = 0; index < TARGET; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getItems().get(index).getPosition());
            assertEquals(frozen.getOrderedEntityIds().get(index),
                    frozen.getOrderedPlan().getItems().get(index).getVolunteerId());
        }
        assertEquals(DirectReviewPreviewPlanner.factsDigestForEntities(
                        frozen.getSelectedEntityIds(), candidates),
                frozen.getFactsDigest());
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getPlanContentDigest());
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void confirmableModePromotesFrozenFillToReady() {
        FixProposalDTO proposal = plan(true);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertTrue(finding.getSuggestedCommand().getExecutable());
        assertEquals(Integer.valueOf(7), proposal.getSourceVersionGuard());
        assertNull(proposal.getBlockingReason());
        assertFalse(proposal.getBlockingReasonCodes().contains("review_fix_prepare_unavailable"));
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
    }

    @Test
    void rejectsNonCountTargetFindingsWithoutProposal() {
        finding.setCode("probability_inversion");
        finding.getSuggestedCommand().setStrategy("sort_by_probability");
        assertNull(plan(false));
        finding.setCode("count_target");
        finding.setResultStatus("pass");
        assertNull(plan(false));
        finding.setResultStatus("fail");
        finding.getSuggestedCommand().setStrategy("add_safety_items");
        assertNull(plan(false));
        finding.getSuggestedCommand().setStrategy("fill_missing_count");
        finding.getSuggestedCommand().setTargetCount(null);
        assertNoFrozen(plan(false), "review_fix_search_no_change");
    }

    @Test
    void rejectsUnitModeAndUnsupportedSelections() {
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        assertNoFrozen(plan(false), "review_fix_search_unsupported");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getOrderedPlanState().getItems().get(0).setPinned(true);
        assertNoFrozen(plan(false), "review_fix_selection_incomplete");
        state.getOrderedPlanState().getItems().get(0).setPinned(null);
        state.getWorkingPlanState().getItems().get(0).setLocked(true);
        assertNoFrozen(plan(false), "review_fix_selection_incomplete");
    }

    @Test
    void blockedWhenTargetDoesNotIncreaseOrPostconditionFails() {
        finding.getSuggestedCommand().setTargetCount(CURRENT);
        assertNoFrozen(plan(false), "review_fix_search_no_change");
        finding.getSuggestedCommand().setTargetCount(TARGET);
        FixProposalDTO failed = planner.plan(state, candidates, finding,
                after -> review("fail", "pass"), false);
        assertNoFrozen(failed, "repair_goal_unreachable");
        FixProposalDTO hard = planner.plan(state, candidates, finding,
                after -> review("pass", "fail"), false);
        assertNoFrozen(hard, "hard_constraints_unsatisfied");
        FixProposalDTO unavailable = planner.plan(state, candidates, finding,
                after -> new ReviewStateDTO(), false);
        assertNoFrozen(unavailable, "review_fix_evaluation_unavailable");
    }

    @Test
    void reevaluationSeesTheMaterializedEightyTwoAndInputStaysUntouched() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals(TARGET, after.getWorkingPlanState().getItems().size());
            assertEquals(TARGET, after.getOrderedPlanState().getItems().size());
            assertEquals(TARGET - CURRENT, (int) after.getOrderedPlanState().getItems().stream()
                    .filter(item -> "review_fix".equals(item.getSource())).count());
            after.getWorkingPlanState().getItems().clear();
            return review("pass", "pass");
        }, false);
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(baseline, JSON.toJSONString(state), "reevaluate 也只拿到副本");
    }

    private FixProposalDTO plan(boolean confirmable) {
        return planner.plan(state, candidates, finding,
                after -> review("pass", "pass"), confirmable);
    }

    private void assertNoFrozen(FixProposalDTO proposal, String reason) {
        assertNotNull(proposal);
        assertNotReady(proposal);
        assertEquals(reason, proposal.getBlockingReason());
        assertNull(proposal.getFrozenReviewPlan());
    }

    private void assertNotReady(FixProposalDTO proposal) {
        assertFalse("ready".equals(proposal.getStatus()));
        assertFalse(proposal.getRequiresConfirmation());
    }

    private ReviewStateDTO review(String status, String hardStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible("pass".equals(hardStatus));
        EvaluationFindingDTO probe = new EvaluationFindingDTO();
        probe.setCode("count_target");
        probe.setResultStatus(status);
        probe.setRuleStrength("soft");
        EvaluationFindingDTO hard = new EvaluationFindingDTO();
        hard.setCode("count_validation_hard");
        hard.setResultStatus(hardStatus);
        hard.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(probe, hard));
        return review;
    }

    private CandidateItemDTO candidate(String id) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setSchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setTier("protect");
        candidate.setProvinceName("浙江");
        candidate.setAdmissionRatio(50D);
        candidate.setSchoolEnrollRatio(50D);
        candidate.setFinalScore(80D);
        candidate.setIntentScore(40D);
        return candidate;
    }
}
