package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanningUnitMajorDTO {
    private String volunteerId;
    private String majorId;
    private String majorName;
    private String majorCode;
    private String majorCategoryId;
    private String majorSubCategoryId;
    private String tier;
    private Double admissionRatio;
    private Double finalScore;
    private Double intentScore;
    private Boolean preferred = false;
    private Boolean selected = false;
    private Boolean safetyMajor = false;
    private Integer tuitionPerYear;
    private Integer rankInTier;
    private List<String> reasonCodes = Lists.newArrayList();
    private List<String> majorPlanTags = Lists.newArrayList();
}
