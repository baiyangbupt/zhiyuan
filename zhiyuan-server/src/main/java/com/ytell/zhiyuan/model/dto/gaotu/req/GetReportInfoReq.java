package com.ytell.zhiyuan.model.dto.gaotu.req;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotNull;
import java.io.Serializable;

@Data
@ApiModel(value = "GetReportInfoRpcDTO", description = "获取测评报告详细信息请求参数")
public class GetReportInfoReq implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "用户id", required = true)
    @NotNull(message = "用户id不能为空")
    private Long userId;

    @ApiModelProperty(value = "报告id", required = true)
    @NotNull(message = "报告id不能为空")
    private Long reportId;
}