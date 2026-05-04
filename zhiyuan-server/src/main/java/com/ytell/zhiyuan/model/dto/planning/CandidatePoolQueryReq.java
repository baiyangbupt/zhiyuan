package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CandidatePoolQueryReq {
    private Filters filters = new Filters();
    private Sort sort = new Sort();
    private Integer page = 1;
    private Integer pageSize = 20;

    @Data
    public static class Filters {
        private List<String> tiers = Lists.newArrayList();
        private List<String> provinceNames = Lists.newArrayList();
        private List<String> negativeProvinceNames = Lists.newArrayList();
        private List<String> cityNames = Lists.newArrayList();
        private List<String> negativeCityNames = Lists.newArrayList();
        private List<String> schoolKeywords = Lists.newArrayList();
        private List<String> negativeSchoolKeywords = Lists.newArrayList();
        private List<String> majorKeywords = Lists.newArrayList();
        private List<String> negativeMajorKeywords = Lists.newArrayList();
        private List<String> schoolTags = Lists.newArrayList();
        private List<String> negativeSchoolTags = Lists.newArrayList();
        private List<String> majorTags = Lists.newArrayList();
        private List<String> negativeMajorTags = Lists.newArrayList();
    }

    @Data
    public static class Sort {
        private String field = "finalScore";
        private String order = "desc";
    }
}
