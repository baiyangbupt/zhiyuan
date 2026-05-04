package com.ytell.zhiyuan.model.dto.gaotu.req;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotNull;
import java.io.Serializable;

@Data
@ApiModel(value = "ListReportInfoRpcDTO", description = "获取测评报告列表请求参数")
public class ListReportInfoRpcReq implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "用户id", required = true)
    @NotNull(message = "用户id不能为空")
    private Long userId;

    @ApiModelProperty(value = "报告类型 1-专业测评", required = true)
    @NotNull(message = "报告类型不能为空")
    private Integer reportType;
}