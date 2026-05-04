package com.ytell.zhiyuan.model.dto.gaotu.req;

import lombok.Data;

@Data
public class QuerySchoolMajorScoreLineReq {
    private String areaId;
    private String batch;
    private String majorId;
    private String schoolId;
    private Integer year;
    private String subjectType;
}