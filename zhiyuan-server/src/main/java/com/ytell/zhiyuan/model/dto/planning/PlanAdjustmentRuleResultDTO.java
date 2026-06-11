package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanAdjustmentRuleResultDTO {
    private String ruleCode;
    private String label;
    private String category;
    private String scopeKind;
    private String fixability;
    private List<String> supportedFixStrategies = Lists.newArrayList();
    private String defaultFixStrategy;
    private String severity = "info";
    private Boolean hit = false;
    private String reasonCode;
    private String summary;
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<String> suggestionTypes = Lists.newArrayList();
}
