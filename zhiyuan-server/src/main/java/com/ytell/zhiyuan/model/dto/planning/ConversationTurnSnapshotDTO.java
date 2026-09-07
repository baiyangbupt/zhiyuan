package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
public class ConversationTurnSnapshotDTO {
    private Integer snapshotVersion;
    private Long sessionId;
    private String planningStage = "";
    private Map<String, Object> scoreContext = new LinkedHashMap<String, Object>();
    private Map<String, Object> confirmedConstraints = new LinkedHashMap<String, Object>();
    private Map<String, Object> preferences = new LinkedHashMap<String, Object>();
    private Map<String, Object> activeProposal;
    private List<String> missingFacts = new ArrayList<String>();
    private List<String> allowedCapabilities = new ArrayList<String>();
    private List<ConversationEvidenceDTO> evidence = new ArrayList<ConversationEvidenceDTO>();
}
