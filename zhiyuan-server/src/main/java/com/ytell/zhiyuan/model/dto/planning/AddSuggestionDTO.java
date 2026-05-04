package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class AddSuggestionDTO {
    private String id;
    private String type = "add";
    private String ruleCode;
    private String title;
    private String description;
    private String severity = "info";
    private String target = "draft";
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<String> reasonCodes = Lists.newArrayList();
    private List<String> candidateUnitIds = Lists.newArrayList();
    private List<String> candidateVolunteerIds = Lists.newArrayList();
    private List<PlanAdjustmentCandidateSummaryDTO> candidateSummaries = Lists.newArrayList();
    private String insertAfterUnitId;
    private String insertAfterVolunteerId;
    private String preferredApplyMode = "append_only";
}
