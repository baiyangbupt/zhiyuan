package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class DataFreshnessCheckRes {
    private Integer version;
    private StaleFlagsDTO staleFlags = new StaleFlagsDTO();
    private DataFreshnessStateDTO dataFreshnessState = new DataFreshnessStateDTO();
    private PlanningWorkspaceStateRes workspaceState;
}
