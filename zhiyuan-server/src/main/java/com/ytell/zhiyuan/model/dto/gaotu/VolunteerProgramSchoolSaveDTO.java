package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotNull;
import java.io.Serializable;

@Data
@ApiModel(value = "VolunteerProgramSchoolSaveDTO", description = "填报方案院校")
public class VolunteerProgramSchoolSaveDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "院校招生计划ID")
    @NotNull(message = "院校招生计划ID不能为空")
    private String planSchoolDataId;

    @ApiModelProperty(value = "方案级别")
    @NotNull(message = "方案级别不能为空")
    private String volunteerLevel;

    @ApiModelProperty(value = "排序")
    @NotNull(message = "排序不能为空")
    private Integer sortValue;
}