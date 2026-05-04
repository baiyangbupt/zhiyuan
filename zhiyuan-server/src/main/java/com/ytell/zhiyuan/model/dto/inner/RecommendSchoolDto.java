package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.List;

@Data
public class RecommendSchoolDto {

    private List<SchoolInfo> sprintSchoolList;
    private List<SchoolInfo> safeSchoolList;
    private List<SchoolInfo> protectSchoolList;

    @Data
    public static class SchoolInfo {
        private String schoolId;
        private String schoolEnrollRatio;
        private String maxMajorEnrollRatio;
        private String maxEnrollRatioMajorName;


    }
}
