package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class TierQuotaChangeDTO {
    private TierQuotaGoalDTO beforeGoal;
    private TierQuotaGoalRequestDTO requestedGoal;
    private TierQuotaGoalDTO effectiveGoal;
    private TierAllocationResolutionDTO resolution;
    private Boolean stateChanged = false;
}
