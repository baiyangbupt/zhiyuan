package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class OrderedMoveReq {
    private String volunteerId;
    private Integer targetPosition;
}
