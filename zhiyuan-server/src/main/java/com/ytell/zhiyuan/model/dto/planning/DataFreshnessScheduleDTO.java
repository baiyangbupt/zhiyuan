package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class DataFreshnessScheduleDTO {
    private Long chatSessionId;
    private Long tenantId;
    private String prepareType;
    private String provinceCode;
    private String provinceName;
    private Integer examYear;
    private String sessionStatus;
    private String createTime;
    private String lastAccessedAt;
    private String lastCheckedAt;
    private String nextCheckAt;
    private Integer checkIntervalMinutes;
    private String lastCheckSource;
    private String lastCheckStatus;
    private String sourceDataHash;
    private String latestSourceDataHash;
    private Integer failCount;
    private String lastError;
    private String lastFailedAt;
    private Boolean enabled;
}
