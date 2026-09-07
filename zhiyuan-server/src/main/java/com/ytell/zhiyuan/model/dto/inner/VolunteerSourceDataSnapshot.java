package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

@Data
public class VolunteerSourceDataSnapshot {
    private Long chatSessionId;
    private String fetchedAt;
    private String sourceDataHash;
    private String sourceDataJson;
    private String localFilePath;
    private String ossFileName;
    private VolunteerDataDTO volunteerData;
}
