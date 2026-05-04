package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class OrderedItemDTO {
    private Integer position;
    private String volunteerId;
    private String tier;
    private String schoolName;
    private String majorName;
    private Boolean locked = false;
    private Boolean pinned = false;
    private Integer pinnedPosition;
    private String orderedBy;
    private String orderReason;
    private String source;
}
