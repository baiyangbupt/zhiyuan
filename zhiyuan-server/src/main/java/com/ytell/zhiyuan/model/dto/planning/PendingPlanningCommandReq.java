package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PendingPlanningCommandReq {
    private String operationId;
    private String pendingId;
    private String claimToken;
    private Integer expectedPlanVersion;
    private String commandType;
    private UpdateConstraintStateReq constraintUpdate;
    private Integer minTuitionPerYear;
    private Integer maxTuitionPerYear;
    private Boolean regenerateOrderedPlan = false;
    private List<String> unitIds = Lists.newArrayList();
    private List<String> volunteerIds = Lists.newArrayList();
}
