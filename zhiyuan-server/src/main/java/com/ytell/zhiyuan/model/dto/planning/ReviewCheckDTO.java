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
    /**
     * 审查 2.0 四级分级（2026-10-16 review §五-58）：block/action/notice/info。
     * 由 ReviewRuleRegistry 逐规则给默认，个别检查（数量校验）按口径/结果在运行时降级。
     * 旧字段 level（risk/warn/info）保留过渡，前端优先读 severity、缺省时回退 level。
     */
    private String severity;
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
