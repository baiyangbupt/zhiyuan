package com.ytell.zhiyuan.model.dto.gaotu.req;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
@ApiModel("获取方案列表请求")
public class ProgramPageReq {
    @ApiModelProperty(value = "志愿ID", required = false)
    private Long id;
    @ApiModelProperty(value = "当前年份", required = false)
    private String year;
    @ApiModelProperty(value = "成员Id", required = true)
    private Long memberId;
    @ApiModelProperty(value = "当前填报方式，PREDICT-模拟，VOLUNTEER-智能", required = true)
    private String prepareType;

    @ApiModelProperty(value = "选科组合代码排列", required = true)
    private String subjects;

    @ApiModelProperty(value = "分数", required = true)
    private Integer score;

    @ApiModelProperty(value = "选科类型", required = true)
    private String subjectType;

    @ApiModelProperty(value = "批次编码", required = true)
    private String batch;

    @ApiModelProperty(value = "地区ID", required = true)
    private String areaId;

    @ApiModelProperty(value = "页面类型: 1：展开", required = true)
    private Integer tabType = 1;

    @ApiModelProperty("直辖市ID列表")
    private List<String> areas;

    @ApiModelProperty("地级市ID列表")
    private List<String> cities;

    @ApiModelProperty("筛选专业ID")
    private List<String> majorIdList;

    @ApiModelProperty("院校分类")
    private List<String> classifyList;

    @ApiModelProperty("院校筛选项")
    private List<String> natureList;

    @ApiModelProperty("特殊筛选列表")
    private List<String> specialFilterList;

    @ApiModelProperty("限报要求列表")
    private List<String> registrationConditionList;

    @ApiModelProperty(value = "志愿填报页面排序类型枚举code，1-录取概率、2-计划人数、3-大学排名", required = true)
    private String sortEnum;

    @ApiModelProperty("学费区间 右端点")
    private Integer maxTuitionFeeM;

    @ApiModelProperty("学费区间 左端点")
    private Integer minTuitionFeeM;
}