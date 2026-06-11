package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class ReviewWorkflowRunRes {
    private String status;
    private Long sessionId;
    private Integer sourceVersion;
    private ReviewStateDTO reviewState = new ReviewStateDTO();
    private FixProposalStateDTO fixProposalState = new FixProposalStateDTO();
    private PlanningWorkflowStatusDTO workflowStatus = new PlanningWorkflowStatusDTO();
    private PlanningWorkspaceStateRes workspaceState = new PlanningWorkspaceStateRes();
}
