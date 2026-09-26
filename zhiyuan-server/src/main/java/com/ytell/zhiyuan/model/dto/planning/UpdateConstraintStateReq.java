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
    /** 区域 ID（与 `regionPreferences` 同序语义 ✓）：解析出 ID 时一并下发 ✓，匹配以 ID 为准 ✓。 */
    private PreferenceGroup regionPreferenceIds;
    /** 专业 ID（与 `majorPreferences` 同序语义 ✓）：解析出 ID 时一并下发 ✓，匹配以 ID 为准 ✓。 */
    private PreferenceGroup majorPreferenceIds;

    @Data
    public static class PreferenceGroup {
        private List<String> positive;
        private List<String> negative;
    }
}
