package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class UserGoalFixProposalReq {
    private String proposalSource = "user_goal";
    private String goalType;
    private String userOriginalText;
    private String confidence = "medium";
    private Integer sourceVersionGuard;
    private List<ScopeDTO> targetScopes = Lists.newArrayList();
    private List<ScopeDTO> negativeScopes = Lists.newArrayList();
    private List<String> qualityGuards = Lists.newArrayList();
    private List<String> tradeoffGuards = Lists.newArrayList();
    private List<String> sourceReviewIssueCodes = Lists.newArrayList();
    private Map<String, Object> context;

    @Data
    public static class ScopeDTO {
        private String scopeType;
        private String name;
        private String normalizedName;
        private String entityType;
        private String resolutionStatus;
        private String rawText;
        private Map<String, Object> evidence;
    }
}
