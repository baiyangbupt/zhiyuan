package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.List;

@Data
public class QuerySchoolByMajorRes {
    private List<SchoolInfo> sprint;
    private List<SchoolInfo> safe;
    private List<SchoolInfo> protect;

    @Data
    public static class SchoolInfo {
        private String schoolName;
        private String majorEnrollRatio;
    }
}
