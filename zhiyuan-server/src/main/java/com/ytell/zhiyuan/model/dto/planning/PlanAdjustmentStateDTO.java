package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class PlanAdjustmentStateDTO {
    private String generatedAt;
    private Integer sourceVersion = 0;
    private Integer draftVersion = 0;
    private Integer orderedVersion = 0;
    private String status = "idle";
    private PlanAdjustmentAnalysisDTO analysis = new PlanAdjustmentAnalysisDTO();
    private PlanAdjustmentSuggestionsDTO suggestions = new PlanAdjustmentSuggestionsDTO();
}
