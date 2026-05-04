package com.ytell.zhiyuan.model.vo;

import lombok.Data;

@Data
public class LimitSituationRes {

    private SettingAndUsage createSession;
    private SettingAndUsage modifyUserInfo;

    @Data
    public static class SettingAndUsage {
        private Integer settingCount;
        private Integer useCount;
    }
}
