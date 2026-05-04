package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class CompensationApplyReq {
    private Boolean regenerateOrderedPlan = true;
    private Boolean rerunReview = true;
}
