package com.ytell.zhiyuan.model.dto.inner;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;
import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class MajorTagBean {
    private Long id;
    @JsonProperty("major_id")
    private Integer majorId;

    @JsonProperty("major_name")
    private String majorName;

    @JsonProperty("major_code")
    private String majorCode;

    @JsonProperty("major_level")
    private Integer majorLevel;

    @JsonProperty("category_id")
    private Integer categoryId;

    private String category;

    @JsonProperty("sub_category_id")
    private Integer subCategoryId;

    @JsonProperty("sub_category")
    private String subCategory;

    @JsonProperty("w_ratio")
    private Float wRatio;

    @JsonProperty("l_ratio")
    private Float lRatio;

    @JsonProperty("male_ratio")
    private Float maleRatio;

    @JsonProperty("female_ratio")
    private Float femaleRatio;

    @JsonProperty("study_time")
    private String studyTime;

    private List<String> degree;

    @JsonProperty("synopsis_info")
    private String synopsisInfo;

    @JsonProperty("train_objective")
    private String trainObjective;

    @JsonProperty("train_demand")
    private String trainDemand;

    @JsonProperty("subject_demand")
    private String subjectDemand;

    private String knowledge;

    private List<String> postgraduate;

    private List<String> course;

    @JsonProperty("job_orientation")
    private String jobOrientation;

    @JsonProperty("public_figure")
    private String publicFigure;

    private String internship;

    private String qualification;

    @JsonProperty("upgrad_orientation")
    private String upgradOrientation;

    @JsonProperty("select_info")
    private List<String> selectInfo;

    @JsonProperty("select_group")
    private List<String> selectGroup;

    @JsonProperty("tenant_code")
    private String tenantCode;

    @JsonProperty("subject_tendency_source")
    private List<String> subjectTendencySource;

    @JsonProperty("subject_tendency")
    private List<String> subjectTendency;

    @JsonProperty("subject_division_tendency")
    private List<String> subjectDivisionTendency;

    @JsonProperty("gender_tendency")
    private List<String> genderTendency;

    @JsonProperty("personality_tendency")
    private List<String> personalityTendency;

    @JsonProperty("graduate_tendency")
    private List<String> graduateTendency;

    @JsonProperty("profession_tendency")
    private List<String> professionTendency;

    @JsonProperty("industry_tendency")
    private List<String> industryTendency;

    @JsonProperty("work_unit_tendency")
    private List<String> workUnitTendency;

    @JsonProperty("work_style_tendency")
    private List<String> workStyleTendency;

    @JsonProperty("pivot_school")
    private List<String> pivotSchool;

    @JsonProperty("interest_tendency")
    private List<String> interestTendency;

    @JsonProperty("job_hotness_weight")
    private Float jobHotnessWeight;

    @JsonProperty("create_time")
    private Date createTime;

    @JsonProperty("update_time")
    private Date updateTime;
}