package com.ytell.zhiyuan.model.dto.integration;

import lombok.Data;

import java.util.HashMap;
import java.util.Map;

@Data
public class ExternalSessionInitializeRes {
    private Long tenantId;
    private Long chatSessionId;
    private String externalRequestId;
    private Boolean created = true;
    private String sessionUrl;
    private String legacySessionUrl;
    private Planning planning = new Planning();
    private Map<String, String> apis = new HashMap<String, String>();

    @Data
    public static class Planning {
        private String phase;
        private Integer version;
        private Integer candidateTotal = 0;
        private Integer draftTotal = 0;
        private Integer orderedTotal = 0;
        private Map<String, Integer> tierCounts = new HashMap<String, Integer>();
    }
}
