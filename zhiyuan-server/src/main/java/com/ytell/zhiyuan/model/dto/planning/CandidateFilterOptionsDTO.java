package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CandidateFilterOptionsDTO {
    private List<String> provinceNames = Lists.newArrayList();
    private List<String> cityNames = Lists.newArrayList();
    private List<String> majorKeywords = Lists.newArrayList();
    private List<String> schoolTags = Lists.newArrayList();
    private List<String> majorTags = Lists.newArrayList();
    private List<FilterGroupDTO> groups = Lists.newArrayList();
    private List<RegionNodeDTO> regionTree = Lists.newArrayList();

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
}
