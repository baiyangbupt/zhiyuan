package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class PlanAdjustmentCandidateSummaryDTO {
    private String unitId;
    private String volunteerId;
    private String schoolName;
    private String majorName;
    private String tier;
    private Double admissionRatio;
    private Double finalScore;
}
