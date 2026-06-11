package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningBehaviorEventDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkflowStatusDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

import java.util.List;

final class PlanningWorkflowStatusBuilder {

    private PlanningWorkflowStatusBuilder() {
    }

    static PlanningWorkflowStatusDTO build(PlanningStateDTO state, PlanningBehaviorEventDTO latestExport) {
        PlanningWorkflowStatusDTO status = new PlanningWorkflowStatusDTO();
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        String candidateStatus = candidatePoolState == null ? null : candidatePoolState.getStatusCode();
        if (Strings.isNullOrEmpty(candidateStatus) || "not_generated".equals(candidateStatus)) {
            boolean hasGeneratedAt = candidatePoolState != null && !Strings.isNullOrEmpty(candidatePoolState.getGeneratedAt());
            boolean hasSummary = candidatePoolState != null && candidatePoolState.getSummary() != null
                    && (valueOrZero(candidatePoolState.getSummary().getTotal()) > 0
                    || valueOrZero(candidatePoolState.getSummary().getUnitTotal()) > 0);
            candidateStatus = hasGeneratedAt || hasSummary ? CandidatePoolStatusResolver.resolveStatus(candidatePoolState) : "not_generated";
        }
        applyCandidateStatus(status, candidateStatus, candidatePoolState);
        applyPlanStatus(status, state);
        applyReviewStatus(status, state);
        applyExportStatus(status, state, latestExport);
        return status;
    }

    private static void applyCandidateStatus(PlanningWorkflowStatusDTO status,
                                             String candidateStatus,
                                             CandidatePoolStateDTO candidatePoolState) {
        status.setCandidateStatus(candidateStatus);
        if ("empty".equals(candidateStatus)) {
            status.setCandidateMessage("当前可用于规划的候选池暂无可用志愿，请核验专项资格、批次、分数线、选科或身体限报等条件");
        } else if ("low_count".equals(candidateStatus)) {
            status.setCandidateMessage("当前可用于规划的候选偏少，方案选择空间有限");
        } else if ("failed".equals(candidateStatus)) {
            status.setCandidateMessage("候选生成失败，请稍后重试");
        } else if ("ready".equals(candidateStatus)) {
            status.setCandidateMessage("候选池已生成");
        } else {
            status.setCandidateStatus("not_generated");
            status.setCandidateMessage("候选池尚未生成");
        }
        if (candidatePoolState != null && !Strings.isNullOrEmpty(candidatePoolState.getStatusMessage())
                && !"not_generated".equals(candidatePoolState.getStatusCode())) {
            status.setCandidateMessage(candidatePoolState.getStatusMessage());
        }
    }

    private static void applyPlanStatus(PlanningWorkflowStatusDTO status, PlanningStateDTO state) {
        DraftPlanStateDTO workingPlan = state == null ? null : state.getWorkingPlanState();
        OrderedPlanStateDTO ordered = state == null ? null : state.getOrderedPlanState();
        boolean hasWorkingPlan = workingPlan != null && workingPlan.getItems() != null && !workingPlan.getItems().isEmpty();
        boolean hasOrdered = ordered != null && ordered.getItems() != null && !ordered.getItems().isEmpty();
        if (ordered != null && "legacy_submitted".equalsIgnoreCase(ordered.getGenerationMode())) {
            status.setPlanStatus("legacy_readonly");
            status.setPlanMessage("历史已确认方案，建议只读查看");
            status.setLegacySubmitted(true);
            status.setLegacyMessage("历史已确认方案，建议只读查看");
            return;
        }
        if (!hasWorkingPlan && !hasOrdered) {
            status.setPlanStatus("empty");
            status.setPlanMessage("当前方案为空");
            return;
        }
        if (state != null && state.getStaleFlags() != null && Boolean.TRUE.equals(state.getStaleFlags().getOrderedPlan())) {
            status.setPlanStatus("dirty");
            status.setPlanMessage("方案有待更新调整");
            return;
        }
        if (!hasOrdered) {
            status.setPlanStatus("selected");
            status.setPlanMessage("已加入方案，待生成顺序");
            return;
        }
        if (state != null && state.getStaleFlags() != null && Boolean.TRUE.equals(state.getStaleFlags().getReview())) {
            status.setPlanStatus("pending_review");
            status.setPlanMessage("方案已生成，待审查");
            return;
        }
        ReviewStateDTO review = state == null ? null : state.getReviewState();
        if (review == null || Strings.isNullOrEmpty(review.getReviewedAt())) {
            status.setPlanStatus("pending_review");
            status.setPlanMessage("方案已生成，待审查");
            return;
        }
        status.setPlanStatus("ready");
        status.setPlanMessage("方案已生成");
    }

    private static void applyReviewStatus(PlanningWorkflowStatusDTO status, PlanningStateDTO state) {
        ReviewStateDTO review = state == null ? null : state.getReviewState();
        if (state != null && state.getStaleFlags() != null && Boolean.TRUE.equals(state.getStaleFlags().getReview())
                && review != null && !Strings.isNullOrEmpty(review.getReviewedAt())) {
            status.setReviewStatus("stale");
            String message = Strings.isNullOrEmpty(state.getStaleFlags().getMessage())
                    ? "方案已调整，建议重新审查" : state.getStaleFlags().getMessage();
            status.setReviewMessage(message);
            status.setReviewReasonCode(state.getStaleFlags().getReasonCode());
            status.setReviewReasonMessage(message);
            status.setAffectedReviewCodes(defaultStringList(state.getStaleFlags().getAffectedReviewCodes()));
            return;
        }
        if (review == null || Strings.isNullOrEmpty(review.getReviewedAt())) {
            status.setReviewStatus("not_reviewed");
            status.setReviewMessage("方案尚未审查");
            return;
        }
        if ("failed".equalsIgnoreCase(review.getStatus())) {
            status.setReviewStatus("failed");
            status.setReviewMessage("审查暂未完成，请稍后重试");
            return;
        }
        int riskCount = review.getSummary() == null ? 0 : valueOrZero(review.getSummary().getRiskCount());
        int warnCount = review.getSummary() == null ? 0 : valueOrZero(review.getSummary().getWarnCount());
        if (riskCount > 0) {
            status.setReviewStatus("has_risk");
            status.setReviewMessage("审查发现风险，需要查看");
        } else if (warnCount > 0) {
            status.setReviewStatus("has_warning");
            status.setReviewMessage("审查有提醒，建议查看");
        } else {
            status.setReviewStatus("passed");
            status.setReviewMessage("审查通过，暂无明显风险");
        }
    }

    private static void applyExportStatus(PlanningWorkflowStatusDTO status,
                                          PlanningStateDTO state,
                                          PlanningBehaviorEventDTO latestExport) {
        if (latestExport == null) {
            status.setExportStatus("not_exported");
            status.setExportMessage("方案尚未导出");
            return;
        }
        status.setLastExportedAt(latestExport.getCreatedAt());
        Integer exportVersion = latestExport.getPlanVersion();
        Integer currentVersion = state == null ? null : state.getVersion();
        if (exportVersion != null && currentVersion != null && exportVersion < currentVersion) {
            status.setExportStatus("stale");
            status.setExportMessage("方案已调整，建议重新导出");
        } else {
            status.setExportStatus("exported");
            status.setExportMessage("方案已导出");
        }
    }

    private static List<String> defaultStringList(List<String> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static int valueOrZero(Integer value) {
        return value == null ? 0 : value;
    }
}
