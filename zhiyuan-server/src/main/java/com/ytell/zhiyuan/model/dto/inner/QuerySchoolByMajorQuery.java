package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

@Data
public class QuerySchoolByMajorQuery {
    private String major;
    private Long chatSessionId;
}
