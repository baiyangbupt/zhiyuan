package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReplaceSuggestionDTO {
    private String id;
    private String type = "replace";
    private String ruleCode;
    private String title;
    private String description;
    private String severity = "info";
    private String target = "ordered";
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<String> reasonCodes = Lists.newArrayList();
    private List<String> removeUnitIds = Lists.newArrayList();
    private List<String> removeVolunteerIds = Lists.newArrayList();
    private List<String> candidateUnitIds = Lists.newArrayList();
    private List<String> candidateVolunteerIds = Lists.newArrayList();
    private List<ReplacementPairDTO> replacementPairs = Lists.newArrayList();
    private String preferredApplyMode = "replace_and_reorder";
}
