package com.ytell.zhiyuan.model.dto.integration;

import lombok.Data;

@Data
public class ExternalGenerationOptionsDTO {
    private Boolean generateCandidatePool = true;
    private Boolean generateInitialPlan = true;
    private Boolean generateOrderedPlan = true;
    private Boolean returnWorkspaceState = true;
    private Boolean forceRegenerate = false;
}
