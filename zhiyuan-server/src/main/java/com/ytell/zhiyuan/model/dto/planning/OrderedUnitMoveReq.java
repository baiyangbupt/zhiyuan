package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class OrderedUnitMoveReq {
    private String unitId;
    private Integer targetPosition;
}
