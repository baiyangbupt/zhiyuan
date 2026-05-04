package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

@Data
public class SchoolMajorPageQuery {
    private Integer limit = 300;
    private Long chatSessionId;
}
