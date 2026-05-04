package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class UpdateExplicitProfileReq {
    private PreferenceGroup majorPreferences = new PreferenceGroup();
    private PreferenceGroup schoolPreferences = new PreferenceGroup();
    private PreferenceGroup regionPreferences = new PreferenceGroup();
    private List<String> strengthSubjects = Lists.newArrayList();

    @Data
    public static class PreferenceGroup {
        private List<String> positive = Lists.newArrayList();
        private List<String> negative = Lists.newArrayList();
    }
}
