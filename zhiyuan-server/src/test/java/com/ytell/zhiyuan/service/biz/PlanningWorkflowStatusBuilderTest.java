package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningBehaviorEventDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkflowStatusDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class PlanningWorkflowStatusBuilderTest {

    @Test
    void shouldFallbackCandidateStatusFromGeneratedSummary() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel("majorGroup");
        candidatePoolState.setRequiredUnitCount(5);
        candidatePoolState.getSummary().setUnitTotal(3);
        candidatePoolState.getSummary().setTotal(18);
        state.setCandidatePoolState(candidatePoolState);

        PlanningWorkflowStatusDTO status = PlanningWorkflowStatusBuilder.build(state, null);

        assertEquals("low_count", status.getCandidateStatus());
        assertEquals("当前可用于规划的候选偏少，方案选择空间有限", status.getCandidateMessage());
    }

    @Test
    void shouldResolvePlanStatusByCurrentPlanStage() {
        assertEquals("empty", PlanningWorkflowStatusBuilder.build(new PlanningStateDTO(), null).getPlanStatus());

        PlanningStateDTO selected = new PlanningStateDTO();
        selected.getWorkingPlanState().getItems().add(workingItem("v1"));
        assertEquals("selected", PlanningWorkflowStatusBuilder.build(selected, null).getPlanStatus());

        PlanningStateDTO dirty = orderedState();
        dirty.getStaleFlags().setOrderedPlan(true);
        assertEquals("dirty", PlanningWorkflowStatusBuilder.build(dirty, null).getPlanStatus());

        PlanningStateDTO pendingReview = orderedState();
        pendingReview.getStaleFlags().setReview(true);
        assertEquals("pending_review", PlanningWorkflowStatusBuilder.build(pendingReview, null).getPlanStatus());

        PlanningStateDTO ready = orderedState();
        ready.getReviewState().setReviewedAt("2026-06-09T10:00:00+08:00");
        assertEquals("ready", PlanningWorkflowStatusBuilder.build(ready, null).getPlanStatus());
    }

    @Test
    void shouldResolveLegacyReadonlyPlan() {
        PlanningStateDTO state = orderedState();
        state.getOrderedPlanState().setGenerationMode("legacy_submitted");

        PlanningWorkflowStatusDTO status = PlanningWorkflowStatusBuilder.build(state, null);

        assertEquals("legacy_readonly", status.getPlanStatus());
        assertTrue(Boolean.TRUE.equals(status.getLegacySubmitted()));
        assertEquals("历史已确认方案，建议只读查看", status.getLegacyMessage());
    }

    @Test
    void shouldResolveReviewStatusWithStaleReasonAndAffectedCodes() {
        PlanningStateDTO state = orderedState();
        state.getReviewState().setReviewedAt("2026-06-09T10:00:00+08:00");
        state.getStaleFlags().setReview(true);
        state.getStaleFlags().setReasonCode("plan_structure_changed");
        state.getStaleFlags().setMessage("方案内容或顺序已调整，需要重新审查。");
        state.getStaleFlags().setAffectedReviewCodes(Lists.newArrayList("probability_inversion", "count_validation"));

        PlanningWorkflowStatusDTO status = PlanningWorkflowStatusBuilder.build(state, null);

        assertEquals("stale", status.getReviewStatus());
        assertEquals("plan_structure_changed", status.getReviewReasonCode());
        assertEquals("方案内容或顺序已调整，需要重新审查。", status.getReviewReasonMessage());
        assertEquals(Lists.newArrayList("probability_inversion", "count_validation"), status.getAffectedReviewCodes());
    }

    @Test
    void shouldResolveReviewStatusByReviewResult() {
        assertEquals("not_reviewed", PlanningWorkflowStatusBuilder.build(orderedState(), null).getReviewStatus());

        PlanningStateDTO failed = reviewedState();
        failed.getReviewState().setStatus("failed");
        assertEquals("failed", PlanningWorkflowStatusBuilder.build(failed, null).getReviewStatus());

        PlanningStateDTO risk = reviewedState();
        risk.getReviewState().getSummary().setRiskCount(1);
        assertEquals("has_risk", PlanningWorkflowStatusBuilder.build(risk, null).getReviewStatus());

        PlanningStateDTO warning = reviewedState();
        warning.getReviewState().getSummary().setWarnCount(1);
        assertEquals("has_warning", PlanningWorkflowStatusBuilder.build(warning, null).getReviewStatus());

        PlanningStateDTO passed = reviewedState();
        assertEquals("passed", PlanningWorkflowStatusBuilder.build(passed, null).getReviewStatus());
    }

    @Test
    void shouldResolveExportStatusFromLatestExportEvent() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(3);
        assertEquals("not_exported", PlanningWorkflowStatusBuilder.build(state, null).getExportStatus());

        PlanningBehaviorEventDTO staleExport = exportEvent(2, "2026-06-09T10:00:00+08:00");
        PlanningWorkflowStatusDTO stale = PlanningWorkflowStatusBuilder.build(state, staleExport);
        assertEquals("stale", stale.getExportStatus());
        assertEquals("方案已调整，建议重新导出", stale.getExportMessage());
        assertEquals("2026-06-09T10:00:00+08:00", stale.getLastExportedAt());

        PlanningBehaviorEventDTO currentExport = exportEvent(3, "2026-06-09T11:00:00+08:00");
        PlanningWorkflowStatusDTO exported = PlanningWorkflowStatusBuilder.build(state, currentExport);
        assertEquals("exported", exported.getExportStatus());
        assertEquals("方案已导出", exported.getExportMessage());
        assertEquals("2026-06-09T11:00:00+08:00", exported.getLastExportedAt());
    }

    private PlanningStateDTO orderedState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getOrderedPlanState().getItems().add(orderedItem("v1"));
        return state;
    }

    private PlanningStateDTO reviewedState() {
        PlanningStateDTO state = orderedState();
        state.getReviewState().setReviewedAt("2026-06-09T10:00:00+08:00");
        state.getReviewState().setStatus("completed");
        return state;
    }

    private DraftItemDTO workingItem(String volunteerId) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        return item;
    }

    private OrderedItemDTO orderedItem(String volunteerId) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        return item;
    }

    private PlanningBehaviorEventDTO exportEvent(Integer planVersion, String createdAt) {
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventType("plan_export");
        event.setPlanVersion(planVersion);
        event.setCreatedAt(createdAt);
        return event;
    }
}
