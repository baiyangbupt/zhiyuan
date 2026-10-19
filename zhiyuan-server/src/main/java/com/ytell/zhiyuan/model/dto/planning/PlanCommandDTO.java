package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class PlanCommandDTO {
    private String commandType = "apply_plan_change_proposal";
    private String strategy;
    private String applyStrategy;
    private String sourceStrategy;
    private String sourceCheck;
    private String reasonCode;
    private String level;
    private Integer targetCount;
    private Map<String, Integer> tierTargetCounts = Maps.newLinkedHashMap();
    private TierAllocationConstraintDTO tierConstraint;
    private Integer safetyMinLocalProtect;
    private List<CoverageRequirementDTO> coverageRequirements = Lists.newArrayList();
    private HardConstraintsDTO constraintPatch;
    private List<EvaluationEntryRefDTO> targets = Lists.newArrayList();
    private List<EvaluationEntryRefDTO> forcedRemoveTargets = Lists.newArrayList();
    private List<ReplacementPairDTO> replacementPairs = Lists.newArrayList();
    private List<EvaluationEntryRefDTO> reorderTargets = Lists.newArrayList();
    private String evaluationVersion;
    private String commandDigest;
    private Boolean requiresConfirmation = true;
    private Boolean executable = false;
    private String note = "preview_only_until_planner_available";
}
