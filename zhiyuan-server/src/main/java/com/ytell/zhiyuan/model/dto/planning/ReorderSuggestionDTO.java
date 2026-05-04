package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReorderSuggestionDTO {
    private String id;
    private String type = "reorder";
    private String ruleCode;
    private String title;
    private String description;
    private String severity = "info";
    private String target = "ordered";
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<String> reasonCodes = Lists.newArrayList();
    private List<Integer> fromPositions = Lists.newArrayList();
    private List<Integer> toPositions = Lists.newArrayList();
    private List<String> orderedUnitIds = Lists.newArrayList();
    private List<String> orderedVolunteerIds = Lists.newArrayList();
    private String preferredApplyMode = "reorder_only";
}
