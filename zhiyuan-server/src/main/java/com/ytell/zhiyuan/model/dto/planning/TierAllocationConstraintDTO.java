package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
public class TierAllocationConstraintDTO extends TierQuotaGoalDTO {
    private String sourceType;
}
