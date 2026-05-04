package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotNull;
import java.io.Serializable;

@Data
@ApiModel(value = "VolunteerProgramMajorSaveDTO", description = "填报方案专业")
public class VolunteerProgramMajorSaveDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "专业招生计划Id")
    @NotNull(message = "专业招生计划Id不能为空")
    private Long planMajorDataId;

    @ApiModelProperty(value = "方案级别")
    @NotNull(message = "方案级别不能为空")
    private String volunteerLevel;

    @ApiModelProperty(value = "排序")
    @NotNull(message = "排序不能为空")
    private Integer sortValue;
}