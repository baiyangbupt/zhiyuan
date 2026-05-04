package com.ytell.zhiyuan.model.dto.catalog;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CatalogFilterTagsTreeDTO {
    private SchoolFilterTagsDTO school = new SchoolFilterTagsDTO();
    private MajorFilterTagsDTO major = new MajorFilterTagsDTO();
    private AdmissionFilterTagsDTO admission = new AdmissionFilterTagsDTO();
    private ConstraintFilterTagsDTO constraint = new ConstraintFilterTagsDTO();

    @Data
    public static class SchoolFilterTagsDTO {
        private List<String> category = Lists.newArrayList();
        private List<String> nature = Lists.newArrayList();
        private List<String> feature = Lists.newArrayList();
        private List<String> level = Lists.newArrayList();
    }

    @Data
    public static class MajorFilterTagsDTO {
        private List<String> discipline = Lists.newArrayList();
        private List<CatalogMajorTreeNodeDTO> category = Lists.newArrayList();
    }

    @Data
    public static class AdmissionFilterTagsDTO {
        private List<String> type = Lists.newArrayList();
    }

    @Data
    public static class ConstraintFilterTagsDTO {
        private List<String> limit = Lists.newArrayList();
    }
}
