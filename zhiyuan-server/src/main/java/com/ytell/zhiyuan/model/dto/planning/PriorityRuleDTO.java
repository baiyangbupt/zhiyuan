package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PriorityRuleDTO {
    private String domain;
    private String key;
    private List<String> values = Lists.newArrayList();
    private String orderingTarget = "rank_before";
    private String scope = "within_tier";
    private String rawText;
}
