package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.List;

@Data
public class UpdateConstraintStateReq {
    /**
     * preference: soft user preference（**legacy 只读通道**——4.0 起写链恒发 constraint，
     * 此取值仅为兼容旧会话，见 {@code PlanningStateService#updateConstraintState} 围栏）;
     * constraint: hard/exclusive requirement（4.0 唯一现网取值）。
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
