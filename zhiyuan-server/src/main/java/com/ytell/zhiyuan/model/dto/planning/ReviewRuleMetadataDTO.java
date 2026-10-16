package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReviewRuleMetadataDTO {
    private String code;
    private String label;
    private String category;
    private String severityDefault;
    /** 审查 2.0 四级默认（2026-10-16 review §五-58）：block/action/notice/info。 */
    private String severity;
    private List<String> targetModes = Lists.newArrayList();
    private String scopeKind;
    private String fixability;
    private List<String> supportedFixStrategies = Lists.newArrayList();
    private String defaultFixStrategy;
    private Boolean requiresConfirmation = true;
    private String evidenceSchema;
    private String postApplyValidationRule;
}
