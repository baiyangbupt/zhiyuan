package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class StaleFlagsDTO {
    private Boolean candidatePool = false;
    private Boolean recommendationOverlay = false;
    private Boolean initialRecommendation = false;
    private Boolean orderedPlan = false;
    private Boolean planAdjustment = false;
    private Boolean review = false;
    private String reasonCode;
    private String message;
    private List<String> affectedReviewCodes = Lists.newArrayList();
}
