package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class HardPlanningObjectivesDTO {
    private List<CoverageRequirementDTO> coverageRequirements = Lists.newArrayList();
    private List<PriorityRuleDTO> priorityRules = Lists.newArrayList();
    private TierQuotaGoalDTO tierQuotaGoal;
}
