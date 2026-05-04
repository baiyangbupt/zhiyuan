package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Data
public class OrderedPlanStateDTO {
    private List<OrderedItemDTO> items = Lists.newArrayList();
    private List<OrderedUnitDTO> units = Lists.newArrayList();
    private Summary summary = new Summary();
    private String generationMode = "manual";
    private Boolean autoCompleted = false;
    private Boolean gradientAdjusted = false;
    private Integer preservedPinnedCount = 0;
    private Integer preservedManualOrderCount = 0;

    @Data
    public static class Summary {
        private Integer unitTotal = 0;
        private Integer targetUnitCount = 0;
        private Integer total = 0;
        private Integer targetCount = 0;
        private Map<String, Integer> unitTierCounts = new HashMap<String, Integer>();
        private Map<String, Integer> tierCounts = new HashMap<String, Integer>();
        private Boolean sequenceOk = false;
        private Boolean gradientOk = false;
        private Boolean safetyOk = false;
    }
}
