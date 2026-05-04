package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class OrderedPinReq {
    private String volunteerId;
    private Integer targetPosition;
}
