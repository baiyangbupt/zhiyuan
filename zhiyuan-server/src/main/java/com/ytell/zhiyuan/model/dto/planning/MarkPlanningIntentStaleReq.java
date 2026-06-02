package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class MarkPlanningIntentStaleReq {
    /**
     * preference: soft user preference; constraint: hard/exclusive requirement.
     */
    private String intentMode = "preference";
}
