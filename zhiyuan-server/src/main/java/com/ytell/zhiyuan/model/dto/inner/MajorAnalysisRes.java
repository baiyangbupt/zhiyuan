package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.List;

@Data
public class MajorAnalysisRes {

    private List<MajorAnalysis> majorAnalyseList;
    @Data
    public static class MajorAnalysis{
        private String id;
        private Boolean inChoose;
        private String summary;
        private List<VolunteerInfo> volunteerList;

    }

    @Data
    public static class VolunteerInfo{
        private String schoolName;
        private String majorName;
        private String volunteerLevel;
        private String enrollRate;
        private Object weightInfo;

    }
}
