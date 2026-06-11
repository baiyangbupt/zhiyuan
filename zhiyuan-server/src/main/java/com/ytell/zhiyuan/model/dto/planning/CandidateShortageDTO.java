package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class CandidateShortageDTO {
    private String strategy;
    private String sourceCheckCode;
    private String scope;
    private String reasonCode;
    private String targetTier;
    private Integer requiredCount;
    private Integer currentCount;
    private Integer shortageCount;
    private Integer availableCount;
    private String message;
}
