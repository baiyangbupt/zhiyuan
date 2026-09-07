package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Data
public class ConversationStatePatchDTO {
    private Integer baseVersion;
    private Integer targetVersion;
    private List<Map<String, Object>> changes = new ArrayList<Map<String, Object>>();
    private List<Map<String, Object>> invalidations = new ArrayList<Map<String, Object>>();
}
