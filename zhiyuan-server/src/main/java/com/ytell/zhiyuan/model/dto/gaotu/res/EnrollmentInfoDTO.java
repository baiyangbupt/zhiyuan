package com.ytell.zhiyuan.model.dto.gaotu.res;

import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
public class EnrollmentInfoDTO {

    @ApiModelProperty(value = "年份")
    private String year;

    @ApiModelProperty(value = "招生专业子标题")
    private String enrollMajorSubtitle;

    @ApiModelProperty(value = "计划招生人数")
    private String planNum;

    @ApiModelProperty(value = "录取分数")
    private String enrollScore;

    @ApiModelProperty(value = "录取位次")
    private String enrollPos;
} 