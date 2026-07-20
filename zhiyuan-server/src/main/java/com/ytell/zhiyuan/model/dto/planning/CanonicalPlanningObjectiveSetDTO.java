package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CanonicalPlanningObjectiveSetDTO {
    private String schemaVersion = "4.1.0-m2";
    private Integer sourceVersion;
    private String countMode;
    private Integer targetCount;
    private HardConstraintsDTO eligibilityConstraints = new HardConstraintsDTO();
    private List<CoverageRequirementDTO> coverageConstraints = Lists.newArrayList();
    private TierQuotaGoalDTO tierAllocationGoal;
    private TierAllocationConstraintDTO tierAllocationConstraint;
    private TierAllocationResolutionDTO tierAllocationResolution;
    private Boolean tierAllocationStateChanged = false;
    private List<PriorityRuleDTO> orderingConstraints = Lists.newArrayList();
    private String objectiveDigest;
}
