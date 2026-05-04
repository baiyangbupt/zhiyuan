package com.ytell.zhiyuan.model.dto.inner;

import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
public class UserIntentQueryReq {
    @ApiModelProperty("包含省份")
    private List<String> includeAreaIdList;
    @ApiModelProperty("排除省份")
    private List<String> excludeProvinceIdList;

    @ApiModelProperty("包含地级市")
    private List<String> includeCityIdList;

    @ApiModelProperty("排除地级市")
    private List<String> excludeCityIdList;

    @ApiModelProperty("包含院校")
    private List<String> includeSchoolIdList;
    @ApiModelProperty("排除院校")
    private List<String> excludeSchoolIdList;

    @ApiModelProperty("包含三级专业ID")
    private List<String> includeMajorIdList;

    @ApiModelProperty("排除三级专业ID")
    private List<String> excludeMajorIdList;

    @ApiModelProperty("包含专业二级id")
    private List<String> includeMajorSecondLevelIdList;

    @ApiModelProperty("包含专业二级id")
    private List<String> excludeMajorSecondLevelIdList;

    @ApiModelProperty("院校分类")
    private List<String> classifyList;

    @ApiModelProperty("院校筛选项")
    private List<String> natureList;

    @ApiModelProperty("限报要求列表")
    private List<String> registrationConditionList;

    @ApiModelProperty("学费区间 右端点")
    private Integer maxTuitionFeeM;

    @ApiModelProperty("学费区间 左端点")
    private Integer minTuitionFeeM;

    @ApiModelProperty("色盲色弱")
    private Boolean needCheckSemangSpecial;

    @ApiModelProperty("专项计划")
    private Boolean hasZhuanXiangSpecial;

    @ApiModelProperty("是否少数民族")
    private Boolean hasMinority;

    @ApiModelProperty("是否接受中外合作")
    private Boolean acceptForeignSchool;
    @ApiModelProperty("用户选科")
    private List<String> subjects;

    private Integer maxSchoolEnrollRatio;
    private Integer minSchoolEnrollRatio;
    private Integer minMajorEnrollRatio;
    private Integer maxMajorEnrollRatio;

    private String majorName;
}
