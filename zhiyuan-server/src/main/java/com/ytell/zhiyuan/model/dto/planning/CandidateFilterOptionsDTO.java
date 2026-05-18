package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CandidateFilterOptionsDTO {
    private List<String> provinceNames = Lists.newArrayList();
    private List<String> cityNames = Lists.newArrayList();
    private List<String> schoolKeywords = Lists.newArrayList();
    private List<String> majorKeywords = Lists.newArrayList();
    private List<String> schoolTags = Lists.newArrayList();
    private List<String> majorTags = Lists.newArrayList();
    private List<FilterGroupDTO> groups = Lists.newArrayList();
    private List<RegionNodeDTO> regionTree = Lists.newArrayList();
    private List<MajorDisciplineNodeDTO> majorTree = Lists.newArrayList();

    @Data
    public static class FilterGroupDTO {
        private String groupCode;
        private String groupName;
        private String filterField;
        private List<String> values = Lists.newArrayList();
    }

    @Data
    public static class RegionNodeDTO {
        private String provinceName;
        private List<String> cityNames = Lists.newArrayList();
    }

    @Data
    public static class MajorDisciplineNodeDTO {
        private String disciplineName;
        private List<MajorCategoryNodeDTO> categories = Lists.newArrayList();
    }

    @Data
    public static class MajorCategoryNodeDTO {
        private String categoryName;
        private List<String> majorNames = Lists.newArrayList();
    }
}
