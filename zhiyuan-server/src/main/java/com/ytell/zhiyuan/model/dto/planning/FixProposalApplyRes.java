package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class FixProposalApplyRes {
    private String status;
    private String message;
    private FixProposalDTO proposal;
    private RepairReportDTO repairReport;
    private PlanningStateDTO state;
}
