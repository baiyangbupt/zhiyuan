package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class InitialRecommendationItemDTO {
    private String volunteerId;
    private String expertComboTag = "专家优选组合";
    private Double comboScore;
    private String recommendTier;
    private List<String> reasonCodes = Lists.newArrayList();
}
