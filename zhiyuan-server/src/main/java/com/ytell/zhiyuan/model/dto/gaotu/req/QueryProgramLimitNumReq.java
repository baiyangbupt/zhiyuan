package com.ytell.zhiyuan.model.dto.gaotu.req;

import lombok.Data;

@Data
public class QueryProgramLimitNumReq {
    private String prepareType;
    private String subjectType;
    private Integer score;
    private String subjects;
    private String areaId;
    private String batch;
    private Integer recordNumLimit;
}