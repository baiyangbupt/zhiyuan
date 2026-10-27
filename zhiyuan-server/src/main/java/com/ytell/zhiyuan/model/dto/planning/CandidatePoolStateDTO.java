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
    private String statusCode = "not_generated";
    private String statusMessage = "候选池尚未生成";
    private List<String> riskHints = Lists.newArrayList();
    private Integer requiredCount;
    private Map<String, Integer> requiredTierCounts = new HashMap<String, Integer>();
    private Integer requiredUnitCount;
    private Integer requiredMajorCount;
    private Integer userScore;
    private Integer batchScore;
    private String sourceProvinceName;
    /** 用户专项资格只读投影（权威仍在 userScoreDetail）；null=未回答，false=明确无专项。 */
    private Boolean specialPlan;
    private String volunteerModel;
    private List<CandidateItemDTO> items = Lists.newArrayList();
    private SourceSummary sourceSummary = new SourceSummary();
    private Summary summary = new Summary();

    @Data
    public static class SourceSummary {
        private Integer externalEntryTotal = 0;
        private Integer externalUnitTotal = 0;
        private Map<String, Integer> externalEntryTierCounts = new HashMap<String, Integer>();
        private Map<String, Integer> externalUnitTierCounts = new HashMap<String, Integer>();
        private Integer normalizedEntryTotal = 0;
        private Integer normalizedUnitTotal = 0;
        private Map<String, Integer> normalizedEntryTierCounts = new HashMap<String, Integer>();
        private Map<String, Integer> normalizedUnitTierCounts = new HashMap<String, Integer>();
    }

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
