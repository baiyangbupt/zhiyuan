package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class TierQuotaGoalDTO {
    private String type;
    private Integer sprintCount;
    private Integer stableCount;
    private Integer protectCount;
    private TierCountRangeDTO sprint;
    private TierCountRangeDTO stable;
    private TierCountRangeDTO protect;
    private Integer sprintWeight;
    private Integer stableWeight;
    private Integer protectWeight;
}
