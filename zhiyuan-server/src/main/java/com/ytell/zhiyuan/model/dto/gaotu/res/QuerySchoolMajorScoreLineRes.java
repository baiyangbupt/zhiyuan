package com.ytell.zhiyuan.model.dto.gaotu.res;

import lombok.Data;

@Data
public class QuerySchoolMajorScoreLineRes {
    private Integer year;
    private String name;
    private String batch;
    private String batchTitle;
    private String enrollNum;
    private String maxScore;
    private String minScore;
    private String averageScore;
    private String minPos;
    private String maxPos;
    private String selectInfo;

} 