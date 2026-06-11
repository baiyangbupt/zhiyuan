package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
public class InitialPlanStrategyReportDTO {
    private TargetProfile targetProfile = new TargetProfile();
    private List<ObjectiveWeight> objectiveWeights = Lists.newArrayList();
    private Integer selectedCount = 0;
    private List<AppliedRepair> appliedRepairs = Lists.newArrayList();
    private List<FixProposalActionDTO> actions = Lists.newArrayList();
    private List<Tradeoff> tradeoffs = Lists.newArrayList();
    private List<UnresolvedRisk> unresolvedRisks = Lists.newArrayList();
    private List<CandidateShortageDTO> candidateShortages = Lists.newArrayList();
    private List<String> userAttentionMessages = Lists.newArrayList();

    @Data
    public static class TargetProfile {
        private Integer targetCount = 0;
        private Map<String, Integer> targetTierCounts = new LinkedHashMap<String, Integer>();
        private String sourceProvinceName;
        private String volunteerModel;
        private Integer requiredMajorCount;
    }

    @Data
    public static class ObjectiveWeight {
        private String code;
        private String label;
        private Double relativeWeight;
        private Integer priority;
        private String description;
    }

    @Data
    public static class AppliedRepair {
        private String ruleCode;
        private String actionType;
        private String reasonCode;
        private String fromVolunteerId;
        private String fromLabel;
        private String toVolunteerId;
        private String toLabel;
        private String detail;
        private String tradeoffSummary;
    }

    @Data
    public static class UnresolvedRisk {
        private String ruleCode;
        private String detail;
    }

    @Data
    public static class Tradeoff {
        private String ruleCode;
        private String actionType;
        private String reasonCode;
        private String fromVolunteerId;
        private String fromLabel;
        private String toVolunteerId;
        private String toLabel;
        private Double finalScoreDelta;
        private Double admissionRatioDelta;
        private Double hotIndexDelta;
        private Integer schoolRankDelta;
        private Boolean preferredDowngraded = false;
        private Boolean preferredUpgraded = false;
        private List<String> gains = Lists.newArrayList();
        private List<String> costs = Lists.newArrayList();
        private String summary;
    }
}
