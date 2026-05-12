package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Data
public class PlanningBehaviorEventDTO {
    private String eventId;
    private Long chatSessionId;
    private Long tenantId;
    private String eventType;
    private String mode;
    private Integer planVersion;
    private String generationMode;
    private List<String> volunteerIds = Lists.newArrayList();
    private List<String> unitIds = Lists.newArrayList();
    private Map<String, Integer> fromPositions = new HashMap<String, Integer>();
    private Map<String, Integer> toPositions = new HashMap<String, Integer>();
    private String tier;
    private Double admissionRatio;
    private String schoolName;
    private String majorName;
    private String sortKey;
    private Boolean positiveFeedback = false;
    private String snapshotDigest;
    private String createdAt;
}
