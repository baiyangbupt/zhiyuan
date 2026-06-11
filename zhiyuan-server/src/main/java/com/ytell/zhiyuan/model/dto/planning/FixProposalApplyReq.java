package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class FixProposalApplyReq {
    private String proposalId;
    private Integer sourceVersionGuard;
    private Boolean regenerateOrderedPlan = true;
    private Boolean rerunReview = true;
}
