package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Data
public class CandidatePoolStateDTO {
    private String generatedAt;
    private Integer sourceVersion;
    private Integer requiredCount;
    private Map<String, Integer> requiredTierCounts = new HashMap<String, Integer>();
    private Integer requiredUnitCount;
    private Integer requiredMajorCount;
    private Integer userScore;
    private Integer batchScore;
    private String sourceProvinceName;
    private String volunteerModel;
    private List<CandidateItemDTO> items = Lists.newArrayList();
    private Summary summary = new Summary();

    @Data
    public static class Summary {
        private Integer entryTotal = 0;
        private Integer unitTotal = 0;
        private Integer total = 0;
        private Map<String, Integer> entryTierCounts = new HashMap<String, Integer>();
        private Map<String, Integer> unitTierCounts = new HashMap<String, Integer>();
        private Map<String, Integer> tierCounts = new HashMap<String, Integer>();
    }
}
