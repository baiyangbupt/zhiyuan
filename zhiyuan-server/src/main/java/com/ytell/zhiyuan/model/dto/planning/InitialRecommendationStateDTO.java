package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Data
public class InitialRecommendationStateDTO {
    private String generatedAt;
    private Integer sourceVersion = 0;
    private Integer candidateViewVersion = 0;
    private Integer profileVersion = 0;
    private Summary summary = new Summary();
    private List<InitialRecommendationItemDTO> items = Lists.newArrayList();
    private List<PlanningUnitDTO> units = Lists.newArrayList();

    @Data
    public static class Summary {
        private Integer total = 0;
        private Integer expertPreferredCount = 0;
        private Map<String, Integer> tierCounts = new HashMap<String, Integer>();
        private Integer localProtectCount = 0;
        private Integer gapFixCount = 0;
        private Integer unresolvedGapCount = 0;
        private Integer unitCompletionCount = 0;
        private Integer appliedRepairCount = 0;
        private List<String> unresolvedRuleCodes = Lists.newArrayList();
    }
}
