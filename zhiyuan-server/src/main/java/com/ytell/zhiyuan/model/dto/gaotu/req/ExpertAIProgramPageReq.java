package com.ytell.zhiyuan.model.dto.gaotu.req;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel("全量AI方案分页请求")
public class ExpertAIProgramPageReq {
    @ApiModelProperty(value = "分页会话ID", required = true)
    private String sessionId;

    @ApiModelProperty(value = "当前页码，从1开始", required = true)
    private Long current;

    @ApiModelProperty(value = "每页条数", required = false)
    private Long size;
}
