package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanChangePostconditionReportDTO {
    private String goalType;
    private String proposalSource;
    private String proposalId;
    private String proposalStrategy;
    private String canonicalObjectiveDigest;
    private String solverVersion;
    private String solverInputDigest;
    private List<PlanSolverResultDTO.ObjectiveResultDTO> objectiveResults = Lists.newArrayList();
    private List<String> sourceReviewIssueCodes = Lists.newArrayList();
    private Boolean postValidationPassed;
    private Integer appliedActionCount = 0;
    private Integer affectedUnitCount = 0;
    private Integer addedVolunteerCount = 0;
    private Integer removedVolunteerCount = 0;
    private String countMode;
    private Integer targetCount;
    private Integer actualCount;
    private Integer requirementCount = 0;
    private Integer satisfiedRequirementCount = 0;
    private List<RequirementResultDTO> requirementResults = Lists.newArrayList();
    private Integer priorityRuleCount = 0;
    private Integer satisfiedPriorityRuleCount = 0;
    private List<PriorityRuleResultDTO> priorityRuleResults = Lists.newArrayList();
    private TierQuotaResultDTO tierQuotaResult;
    private Boolean satisfied = false;

    @Data
    public static class RequirementResultDTO {
        private String kind;
        private String domain;
        private String key;
        private List<String> values = Lists.newArrayList();
        private Integer minCount;
        private Integer matchedCount = 0;
        private Boolean planSatisfied = false;
        private Boolean persisted = false;
        private Boolean satisfied = false;
    }

    @Data
    public static class PriorityRuleResultDTO {
        private String domain;
        private String key;
        private List<String> values = Lists.newArrayList();
        private String orderingTarget;
        private String scope;
        private Integer matchedCount = 0;
        private Integer inversionCount = 0;
        private Boolean planSatisfied = false;
        private Boolean persisted = false;
        private Boolean satisfied = false;
    }

    @Data
    public static class TierQuotaResultDTO {
        private String type;
        private Integer sprintCount;
        private Integer stableCount;
        private Integer protectCount;
        private Integer actualSprintCount = 0;
        private Integer actualStableCount = 0;
        private Integer actualProtectCount = 0;
        private TierQuotaGoalDTO effectiveGoal;
        private TierAllocationResolutionDTO resolution;
        private TierCountsDTO actualCounts;
        private Boolean planSatisfied = false;
        private Boolean persisted = false;
        private Boolean satisfied = false;
    }
}
