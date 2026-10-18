package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class FixProposalApplyReq {
    private String proposalId;
    private String proposalSource = "review_check";
    private Integer sourceVersionGuard;
    private Boolean regenerateOrderedPlan = true;
    private Boolean rerunReview = true;
    private String canonicalObjectiveDigest;
    private String solverVersion;
    private String solverInputDigest;
    /** 硬目标契约版本；可选。与提案侧都非空时按 major 兼容，否则回退旧的精确比对。 */
    private String hardObjectiveVersion;
    private UserGoalFixProposalReq userGoalRequest;
}
