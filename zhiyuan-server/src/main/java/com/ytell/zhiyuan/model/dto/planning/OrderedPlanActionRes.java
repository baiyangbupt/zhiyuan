package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class OrderedPlanActionRes {
    private Long sessionId;
    private Integer version;
    private String phase;
    private StaleFlagsDTO staleFlags = new StaleFlagsDTO();
    private OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
}
