package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

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
}
