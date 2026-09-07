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
    /** 规范化招生类型：major 或 major_group。 */
    private String admissionMode = "major";
    private String planningStage = "";
    private Map<String, Object> scoreContext = new LinkedHashMap<String, Object>();
    private Map<String, Object> confirmedConstraints = new LinkedHashMap<String, Object>();
    private Map<String, Object> preferences = new LinkedHashMap<String, Object>();
    private Map<String, Object> activeProposal;
    private List<String> missingFacts = new ArrayList<String>();
    private List<String> allowedCapabilities = new ArrayList<String>();
    private List<ConversationEvidenceDTO> evidence = new ArrayList<ConversationEvidenceDTO>();
    private List<AdmissionFactDTO> admissionFacts = new ArrayList<AdmissionFactDTO>();
}
