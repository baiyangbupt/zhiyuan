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
    private String solverObjectiveDigest;
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
    /** 命令执行前的方案规模（unit 模式=专业组数，volunteer 模式=条目数）。 */
    private Integer countBefore;
    private Integer targetCount;
    private Integer actualCount;
    /**
     * 数量缺口（`max(0, countBefore - actualCount)`，只对**应保持总数**的约束计算）：
     * 纯学费清理把 51 组换成 36 组时，这里必须是 15，而不是靠调用方再读一遍方案才发现。
     */
    private Integer shortage = 0;
    private Integer requirementCount = 0;
    private Integer satisfiedRequirementCount = 0;
    private List<RequirementResultDTO> requirementResults = Lists.newArrayList();
    private Integer priorityRuleCount = 0;
    private Integer satisfiedPriorityRuleCount = 0;
    private List<PriorityRuleResultDTO> priorityRuleResults = Lists.newArrayList();
    private TierQuotaResultDTO tierQuotaResult;
    /**
     * J5.4：safety 只报告、不参与 satisfied/回滚（solver 软层 + review 硬诊断）。
     */
    private SafetyResultDTO safetyResult;
    private Boolean satisfied = false;

    @Data
    public static class SafetyResultDTO {
        private String mode;
        private Integer requiredCount = 0;
        private Integer actualCount = 0;
        private Boolean satisfied = false;
        private String reasonCode;
    }
    // 判"不满足"时留下**原因码** ✓（如 `plan_empty_vacuous` ✓）：
    // 光有 `satisfied=false` 时下游只能猜"是违反了什么、还是根本没有可比对象" ✗。
    private String reasonCode;

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
        /** 不满足的**原因码** ✓（`plan_empty_vacuous` ✓＝空方案没有可比对象 ✗，不是"违反" ✗）。 */
        private String reasonCode;
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
