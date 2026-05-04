package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class InitialPlanGenerateReq {
    private Boolean forceRegenerate = false;
    private Boolean regroupByTier = true;
    private Boolean overwriteExistingDraft = false;
}
