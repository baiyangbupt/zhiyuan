package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.List;

@Data
public class UpdateConstraintStateReq {
    /**
     * preference: soft user preference; constraint: hard/exclusive requirement.
     */
    private String intentMode = "preference";
    private PreferenceGroup majorPreferences;
    private PreferenceGroup schoolPreferences;
    private PreferenceGroup regionPreferences;

    @Data
    public static class PreferenceGroup {
        private List<String> positive;
        private List<String> negative;
    }
}
