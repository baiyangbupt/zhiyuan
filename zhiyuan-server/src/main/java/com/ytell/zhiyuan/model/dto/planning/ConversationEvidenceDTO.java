package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
public class ConversationEvidenceDTO {
    private String evidenceId;
    private String sourceLevel;
    private String sourceSystem;
    private String paramsDigest;
    private String dataVersion;
    private String expiresAt;
    private String admissionMode;
    private String admissionUnitId;
    private String groupCode;
    private String algorithmVersion;
    private Integer stateVersion;
    private Map<String, Object> scope = new LinkedHashMap<String, Object>();
    private String observedAt;
    private List<String> limitations = new ArrayList<String>();
}
