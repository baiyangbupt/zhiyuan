package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class PlanAdjustmentAnalyzeReq {
    private String target = "ordered";
    private Boolean includeReview = true;
}
