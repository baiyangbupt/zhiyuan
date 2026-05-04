package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class ReviewSummaryDTO {
    private Integer totalRuleCount = 0;
    private Integer passedRuleCount = 0;
    private Integer warnRuleCount = 0;
    private Integer riskRuleCount = 0;
    private Integer total = 0;
    private Integer passedCount = 0;
    private Integer warnCount = 0;
    private Integer riskCount = 0;
}
