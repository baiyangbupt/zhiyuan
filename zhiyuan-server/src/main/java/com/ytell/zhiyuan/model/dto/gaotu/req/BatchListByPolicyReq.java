package com.ytell.zhiyuan.model.dto.gaotu.req;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotNull;
import java.io.Serializable;

@Data
@ApiModel(value = "VolunteerProgramBatchQueryDTO", description = "批次数据查询入参")
public class BatchListByPolicyReq implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "省份ID")
    @NotNull(message = "省份ID不能为空")
    private Long areaId;

    @ApiModelProperty(value = "填报类型")
    @NotNull(message = "填报类型不能为空")
    private String prepareType;

    @ApiModelProperty(value = "选科类型")
    @NotNull(message = "选科类型不能为空")
    private String subject;
}