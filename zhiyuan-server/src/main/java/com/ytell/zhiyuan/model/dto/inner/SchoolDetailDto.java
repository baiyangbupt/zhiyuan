package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.List;

@Data
public class SchoolDetailDto {

    private Boolean canJoin;

    private List<MajorInfo> sprintMajorList;
    private List<MajorInfo> safeMajorList;
    private List<MajorInfo> protectMajorList;

    @Data
    public static class MajorInfo {
        private String majorId;
        private String majorName;
        private String majorEnrollRatio;
        private Integer majorPlanNum;
    }
}
