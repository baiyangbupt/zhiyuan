package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class PlanGenerationStateDTO {
    private String mode = "idle";
    private Integer sourceVersion;
    private String generatedAt;
    private Integer usedOverlayVersion;
    private Boolean allowAutoComplete = false;
    private Integer respectedPinnedCount = 0;
    private Integer preservedManualOrderCount = 0;
}
