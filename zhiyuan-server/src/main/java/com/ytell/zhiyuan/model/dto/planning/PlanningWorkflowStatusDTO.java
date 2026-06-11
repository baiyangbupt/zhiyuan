package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanningWorkflowStatusDTO {
    private String candidateStatus = "not_generated";
    private String candidateMessage = "候选池尚未生成";
    private String planStatus = "empty";
    private String planMessage = "当前方案为空";
    private Boolean legacySubmitted = false;
    private String legacyMessage;
    private String reviewStatus = "not_reviewed";
    private String reviewMessage = "方案尚未审查";
    private String reviewReasonCode;
    private String reviewReasonMessage;
    private List<String> affectedReviewCodes = Lists.newArrayList();
    private String exportStatus = "not_exported";
    private String exportMessage = "方案尚未导出";
    private String lastExportedAt;
}
