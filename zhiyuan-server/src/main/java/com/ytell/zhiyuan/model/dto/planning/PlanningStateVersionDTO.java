package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class PlanningStateVersionDTO {
    private Integer version;
    private StaleFlagsDTO staleFlags = new StaleFlagsDTO();
}
