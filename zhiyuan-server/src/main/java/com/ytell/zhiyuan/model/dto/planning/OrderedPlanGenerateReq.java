package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class OrderedPlanGenerateReq {
    private Boolean forceRegenerate = false;
    private Boolean regroupByTier = false;
}
