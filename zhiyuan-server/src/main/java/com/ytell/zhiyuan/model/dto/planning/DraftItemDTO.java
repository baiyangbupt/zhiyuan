package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class DraftItemDTO {
    private String volunteerId;
    private String tier;
    private String schoolName;
    private String majorName;
    private Boolean locked = false;
    private String source;
}
