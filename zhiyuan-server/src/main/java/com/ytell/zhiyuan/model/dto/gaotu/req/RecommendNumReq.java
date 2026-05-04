package com.ytell.zhiyuan.model.dto.gaotu.req;

import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotNull;

@Data
public class RecommendNumReq {
    @ApiModelProperty(value = "省份ID", required = true)
    @NotNull(message = "省份ID不能为空")
    private String areaId;

    @ApiModelProperty(value = "选科类型", required = true)
    @NotNull(message = "选科类型不能为空")
    private String subjectType;

    @ApiModelProperty(value = "批次", required = true)
    @NotNull(message = "批次不能为空")
    private String batch;
}