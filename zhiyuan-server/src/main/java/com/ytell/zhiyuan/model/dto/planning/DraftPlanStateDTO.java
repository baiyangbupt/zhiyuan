package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Internal legacy DTO name kept for persisted-state compatibility.
 * Public JSON/API naming should use workingPlanState; draftPlanState is only a legacy alias.
 */
@Data
public class DraftPlanStateDTO {
    private List<DraftItemDTO> items = Lists.newArrayList();
    private List<DraftUnitDTO> units = Lists.newArrayList();
    private List<String> bannedVolunteerIds = Lists.newArrayList();
    private Summary summary = new Summary();

    @Data
    public static class Summary {
        private Integer unitTotal = 0;
        private Integer targetUnitCount = 0;
        private Integer total = 0;
        private Integer targetCount = 0;
        private Map<String, Integer> unitTierCounts = new HashMap<String, Integer>();
        private Map<String, Integer> tierCounts = new HashMap<String, Integer>();
    }
}
