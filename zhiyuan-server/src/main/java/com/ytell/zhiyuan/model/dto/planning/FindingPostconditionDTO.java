package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class FindingPostconditionDTO {
    private String findingCode;
    private String evaluationVersion;
    private Boolean satisfied = false;
    private Boolean probeSatisfied = false;
    private Boolean hardFeasible = false;
    private String reasonCode = "review_fix_evaluation_unavailable";
}
