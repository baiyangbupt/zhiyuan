package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanAdjustmentRuleResultDTO {
    private String ruleCode;
    private String severity = "info";
    private Boolean hit = false;
    private String summary;
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<String> suggestionTypes = Lists.newArrayList();
}
