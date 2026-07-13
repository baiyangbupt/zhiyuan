package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PendingPlanningCommandRes {
    private String operationId;
    private String pendingId;
    private String commandType;
    private Integer sourcePlanVersion;
    private Integer resultPlanVersion;
    private Boolean replayed = false;
    private List<String> completedSteps = Lists.newArrayList();
    private PlanningStateDTO planningState;
}
