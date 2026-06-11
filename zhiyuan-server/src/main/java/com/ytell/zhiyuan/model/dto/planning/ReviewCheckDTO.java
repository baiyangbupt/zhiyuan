package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReviewCheckDTO {
    private String code;
    private String label;
    private String category;
    private String severityDefault;
    private List<String> targetModes = Lists.newArrayList();
    private String scopeKind;
    private String fixability;
    private List<String> supportedFixStrategies = Lists.newArrayList();
    private String defaultFixStrategy;
    private Boolean requiresConfirmation = true;
    private String evidenceSchema;
    private String postApplyValidationRule;
    private String level;
    private Boolean passed;
    private String reasonCode;
    private String summary;
    private String detail;
    private String suggestedAction;
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<CompensationActionDTO> suggestedCompensations = Lists.newArrayList();
}
