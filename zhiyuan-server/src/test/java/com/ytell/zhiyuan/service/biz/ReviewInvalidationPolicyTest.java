package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class ReviewInvalidationPolicyTest {

    @Test
    void shouldMarkPlanStructureStaleOnlyForPlanReviewAndAdjustment() {
        PlanningStateDTO state = cleanState();

        ReviewInvalidationPolicy.markPlanStructureStale(state);

        assertFalse(state.getStaleFlags().getCandidatePool());
        assertFalse(state.getStaleFlags().getRecommendationOverlay());
        assertFalse(state.getStaleFlags().getInitialRecommendation());
        assertFalse(state.getStaleFlags().getOrderedPlan());
        assertTrue(state.getStaleFlags().getPlanAdjustment());
        assertTrue(state.getStaleFlags().getReview());
        assertEquals("plan_structure_changed", state.getStaleFlags().getReasonCode());
        assertEquals("方案内容或顺序已调整，需要重新审查。", state.getStaleFlags().getMessage());
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("probability_inversion"));
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("count_validation"));
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("high_tuition"));
    }

    @Test
    void shouldMarkCandidatePoolDependentsStaleWithoutCandidatePoolItself() {
        PlanningStateDTO state = cleanState();

        ReviewInvalidationPolicy.markCandidatePoolDependentsStale(state);

        assertFalse(state.getStaleFlags().getCandidatePool());
        assertFalse(state.getStaleFlags().getRecommendationOverlay());
        assertTrue(state.getStaleFlags().getInitialRecommendation());
        assertTrue(state.getStaleFlags().getOrderedPlan());
        assertTrue(state.getStaleFlags().getPlanAdjustment());
        assertTrue(state.getStaleFlags().getReview());
        assertEquals("candidate_pool_refreshed", state.getStaleFlags().getReasonCode());
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("admission_limit"));
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("group_inner_safety_guard"));
    }

    @Test
    void shouldMarkPreferenceIntentStaleWithoutCandidatePool() {
        PlanningStateDTO state = cleanState();

        ReviewInvalidationPolicy.markPreferenceIntentStale(state);

        assertFalse(state.getStaleFlags().getCandidatePool());
        assertTrue(state.getStaleFlags().getRecommendationOverlay());
        assertTrue(state.getStaleFlags().getInitialRecommendation());
        assertTrue(state.getStaleFlags().getOrderedPlan());
        assertTrue(state.getStaleFlags().getPlanAdjustment());
        assertTrue(state.getStaleFlags().getReview());
        assertEquals("preference_intent_changed", state.getStaleFlags().getReasonCode());
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("major_group_safety_intent_alignment"));
        assertFalse(state.getStaleFlags().getAffectedReviewCodes().contains("admission_limit"));
    }

    @Test
    void shouldMarkConstraintIntentStaleWithCandidatePool() {
        PlanningStateDTO state = cleanState();

        ReviewInvalidationPolicy.markConstraintIntentStale(state);

        assertTrue(state.getStaleFlags().getCandidatePool());
        assertTrue(state.getStaleFlags().getRecommendationOverlay());
        assertTrue(state.getStaleFlags().getInitialRecommendation());
        assertTrue(state.getStaleFlags().getOrderedPlan());
        assertTrue(state.getStaleFlags().getPlanAdjustment());
        assertTrue(state.getStaleFlags().getReview());
        assertEquals("constraint_intent_changed", state.getStaleFlags().getReasonCode());
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("admission_limit"));
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().contains("cooperative_program"));
    }

    @Test
    void shouldMarkCandidateViewStaleWithoutReview() {
        PlanningStateDTO state = cleanState();

        ReviewInvalidationPolicy.markCandidateViewStale(state);

        assertFalse(state.getStaleFlags().getCandidatePool());
        assertFalse(state.getStaleFlags().getRecommendationOverlay());
        assertTrue(state.getStaleFlags().getInitialRecommendation());
        assertFalse(state.getStaleFlags().getOrderedPlan());
        assertTrue(state.getStaleFlags().getPlanAdjustment());
        assertFalse(state.getStaleFlags().getReview());
        assertEquals("candidate_view_changed", state.getStaleFlags().getReasonCode());
        assertTrue(state.getStaleFlags().getAffectedReviewCodes().isEmpty());
    }

    @Test
    void shouldNotOverrideReviewStaleReasonForCandidateViewChange() {
        PlanningStateDTO state = cleanState();
        ReviewInvalidationPolicy.markPlanStructureStale(state);

        ReviewInvalidationPolicy.markCandidateViewStale(state);

        assertTrue(state.getStaleFlags().getInitialRecommendation());
        assertTrue(state.getStaleFlags().getPlanAdjustment());
        assertTrue(state.getStaleFlags().getReview());
        assertEquals("plan_structure_changed", state.getStaleFlags().getReasonCode());
        assertEquals("方案内容或顺序已调整，需要重新审查。", state.getStaleFlags().getMessage());
    }

    private PlanningStateDTO cleanState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getStaleFlags().setCandidatePool(false);
        state.getStaleFlags().setRecommendationOverlay(false);
        state.getStaleFlags().setInitialRecommendation(false);
        state.getStaleFlags().setOrderedPlan(false);
        state.getStaleFlags().setPlanAdjustment(false);
        state.getStaleFlags().setReview(false);
        return state;
    }
}
