package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Data
public class RecommendationOverlayStateDTO {
    private String generatedAt;
    private Integer sourceVersion;
    private Integer profileVersion;
    private List<Item> items = Lists.newArrayList();
    private Summary summary = new Summary();

    @Data
    public static class Item {
        private String volunteerId;
        private Double baseScore;
        private Double intentScore;
        private Double finalScore;
        private Integer rankInTier;
        private Boolean preferred;
        private List<String> reasonCodes = Lists.newArrayList();
        private List<String> schoolRankTags = Lists.newArrayList();
        private List<String> majorRankTags = Lists.newArrayList();
        private List<String> preferenceTags = Lists.newArrayList();
    }

    @Data
    public static class Summary {
        private Integer total = 0;
        private Integer preferredCount = 0;
        private Map<String, Integer> tierPreferredCounts = new HashMap<String, Integer>();
    }
}
