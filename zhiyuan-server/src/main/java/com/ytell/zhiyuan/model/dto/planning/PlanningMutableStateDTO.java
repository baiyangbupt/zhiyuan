package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class PlanningMutableStateDTO {
    private Integer version;
    private String phase;
    private StaleFlagsDTO staleFlags;
    private DraftPlanStateDTO draftPlanState;
    private OrderedPlanStateDTO orderedPlanState;
    private String updatedAt;
}
