package com.ytell.zhiyuan.model.dto.gaotu.res;

import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
public class SchoolRecordDTO {

    @ApiModelProperty(value = "学校ID")
    private String schoolId;

    @ApiModelProperty(value = "录取比例")
    private String enrollRatio;

    @ApiModelProperty(value = "录取建议")
    private String enrollAdvice;

    @ApiModelProperty(value = "学校单位名称")
    private String schoolUnitName;

    @ApiModelProperty(value = "选科信息")
    private String selectInfo;

    @ApiModelProperty(value = "学校分数")
    private String schoolScore;

    @ApiModelProperty(value = "学校位次")
    private Integer schoolPos;

    @ApiModelProperty(value = "招生专业列表")
    private List<EnrollmentInfoDTO> subVOList;
} 