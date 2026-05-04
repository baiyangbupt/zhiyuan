package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class DraftPlanReorderReq {
    private Boolean forceRegenerate = true;
    private Boolean regroupByTier = true;
    private Boolean allowAutoComplete = false;
}
