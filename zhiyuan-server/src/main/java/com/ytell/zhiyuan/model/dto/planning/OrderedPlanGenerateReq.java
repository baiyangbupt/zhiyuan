package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class OrderedPlanGenerateReq {
    private Boolean forceRegenerate = false;
    private Boolean regroupByTier = false;
    /**
     * 仅 initial_auto 使用：把初始数量目标临时交给 staged solver；
     * 不写入 constraintState，不作为 durable 用户目标。
     */
    private Integer initialSelectionTargetCount;
}
