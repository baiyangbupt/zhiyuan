package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.List;

@Data
public class SchoolAnalysisRes {

    private List<SchoolAnalysis> schoolAnalyseList;
    @Data
    public static class SchoolAnalysis{
        private String id;
        private Boolean inChoose;
        private String summary;
        private List<VolunteerInfo> volunteerList;

    }

    @Data
    public static class VolunteerInfo{
        private String schoolName;
        private String volunteerLevel;
        private Object schoolWeightInfo;
        private List<MajorInfo> majorList;

    }

    @Data
    public static class MajorInfo{
        private String majorName;
        private String enrollRate;
        private Object majorWeightInfo;
    }
}
