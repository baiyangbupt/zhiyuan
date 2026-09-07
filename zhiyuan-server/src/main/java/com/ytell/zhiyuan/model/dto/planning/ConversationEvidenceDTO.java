package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class ConversationEvidenceDTO {
    private String evidenceId;
    private String sourceLevel;
    private String dataVersion;
    private List<String> limitations = new ArrayList<String>();
}
