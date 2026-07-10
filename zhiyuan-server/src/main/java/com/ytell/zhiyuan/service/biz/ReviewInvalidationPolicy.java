package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

import java.util.List;

public final class ReviewInvalidationPolicy {

    private static final List<String> PLAN_STRUCTURE_REVIEW_CODES = Lists.newArrayList(
            "ratio_distribution",
            "safety_guard",
            "probability_inversion",
            "probability_gap",
            "count_validation",
            "high_tuition",
            "admission_limit",
            "special_enrollment",
            "edge_score",
            "cooperative_program",
            "major_group_safety_intent_alignment",
            "group_inner_safety_guard"
    );

    private static final List<String> CANDIDATE_POOL_REVIEW_CODES = Lists.newArrayList(PLAN_STRUCTURE_REVIEW_CODES);

    private static final List<String> PREFERENCE_REVIEW_CODES = Lists.newArrayList(
            "ratio_distribution",
            "safety_guard",
            "probability_gap",
            "edge_score",
            "major_group_safety_intent_alignment",
            "group_inner_safety_guard"
    );

    private static final List<String> CONSTRAINT_REVIEW_CODES = Lists.newArrayList(CANDIDATE_POOL_REVIEW_CODES);

    private ReviewInvalidationPolicy() {
    }

    public static void markPlanStructureStale(PlanningStateDTO state) {
        if (state == null || state.getStaleFlags() == null) {
            return;
        }
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        markReason(state, "plan_structure_changed", "方案内容或顺序已调整，需要重新审查。", PLAN_STRUCTURE_REVIEW_CODES);
    }

    public static void markCandidatePoolDependentsStale(PlanningStateDTO state) {
        if (state == null || state.getStaleFlags() == null) {
            return;
        }
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setOrderedPlan(true);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        markReason(state, "candidate_pool_refreshed", "候选池和专家推荐已刷新，当前方案未自动调整，建议重新审查确认。", CANDIDATE_POOL_REVIEW_CODES);
    }

    public static void markPreferenceIntentStale(PlanningStateDTO state) {
        if (state == null || state.getStaleFlags() == null) {
            return;
        }
        state.getStaleFlags().setRecommendationOverlay(true);
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setOrderedPlan(true);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        markReason(state, "preference_intent_changed", "报考偏好已调整，专家推荐、排序方案和审查建议需要重新计算。", PREFERENCE_REVIEW_CODES);
    }

    public static void markConstraintIntentStale(PlanningStateDTO state) {
        if (state == null || state.getStaleFlags() == null) {
            return;
        }
        state.getStaleFlags().setRecommendationOverlay(true);
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setOrderedPlan(true);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        markReason(state, "constraint_intent_changed", "报考要求已调整，推荐、方案和审查需要重新计算。", CONSTRAINT_REVIEW_CODES);
    }

    public static void markCandidateViewStale(PlanningStateDTO state) {
        if (state == null || state.getStaleFlags() == null) {
            return;
        }
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setPlanAdjustment(true);
        if (Boolean.TRUE.equals(state.getStaleFlags().getReview())) {
            return;
        }
        markReason(state, "candidate_view_changed", "候选筛选视图已调整，推荐和调整建议需要更新。", Lists.newArrayList());
    }

    private static void markReason(PlanningStateDTO state,
                                   String reasonCode,
                                   String message,
                                   List<String> affectedReviewCodes) {
        state.getStaleFlags().setReasonCode(reasonCode);
        state.getStaleFlags().setMessage(message);
        state.getStaleFlags().setAffectedReviewCodes(affectedReviewCodes == null
                ? Lists.newArrayList()
                : Lists.newArrayList(affectedReviewCodes));
    }
}
