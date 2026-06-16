package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class FixProposalApplyReq {
    private String proposalId;
    private String proposalSource = "review_check";
    private Integer sourceVersionGuard;
    private Boolean regenerateOrderedPlan = true;
    private Boolean rerunReview = true;
    private UserGoalFixProposalReq userGoalRequest;
}
