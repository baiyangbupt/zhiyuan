package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.List;

@Data
public class UpdateExplicitProfileReq {
    private PreferenceGroup majorPreferences;
    private PreferenceGroup schoolPreferences;
    private PreferenceGroup regionPreferences;
    private List<String> strengthSubjects;

    @Data
    public static class PreferenceGroup {
        private List<String> positive;
        private List<String> negative;
    }
}
