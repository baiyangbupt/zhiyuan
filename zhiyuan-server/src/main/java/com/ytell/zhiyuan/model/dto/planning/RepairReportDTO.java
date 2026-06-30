package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class RepairReportDTO {
    private String status = "applied";
    private String strategy;
    private String proposalId;
    private String proposalTitle;
    private String proposalSummary;
    private String proposalImpact;
    private Integer sourceVersion;
    private Integer resultVersion;
    private Integer sourceReviewVersion;
    private Integer resultReviewVersion;
    private String dryRunStatus;
    private String dryRunMessage;
    private Integer appliedActionCount = 0;
    private Integer affectedUnitCount = 0;
    private Integer affectedVolunteerCount = 0;
    private Integer addedUnitCount = 0;
    private Integer addedVolunteerCount = 0;
    private Integer removedUnitCount = 0;
    private Integer removedVolunteerCount = 0;
    private Integer beforeRiskCount = 0;
    private Integer beforeWarnCount = 0;
    private Integer afterRiskCount = 0;
    private Integer afterWarnCount = 0;
    private Boolean postValidationPassed;
    private List<String> sourceCheckCodes = Lists.newArrayList();
    private List<ActionDetail> actionDetails = Lists.newArrayList();
    private List<String> messages = Lists.newArrayList();
    private List<String> warnings = Lists.newArrayList();

    @Data
    public static class ActionDetail {
        private String actionType;
        private String sourceCheckCode;
        private String summary;
        private String detail;
        private List<String> unitIds = Lists.newArrayList();
        private List<String> volunteerIds = Lists.newArrayList();
        private List<String> removeUnitIds = Lists.newArrayList();
        private List<String> removeVolunteerIds = Lists.newArrayList();
        private List<String> candidateUnitIds = Lists.newArrayList();
        private List<String> candidateVolunteerIds = Lists.newArrayList();
        private List<ReplacementPairDTO> replacementPairs = Lists.newArrayList();
        private Integer totalUnitCount;
        private Integer totalVolunteerCount;
        private Integer totalReplacementPairCount;
    }
}
