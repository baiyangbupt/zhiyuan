package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class StaleFlagsDTO {
    private Boolean candidatePool = false;
    private Boolean recommendationOverlay = false;
    private Boolean initialRecommendation = false;
    private Boolean orderedPlan = false;
    private Boolean planAdjustment = false;
    private Boolean review = false;
}
