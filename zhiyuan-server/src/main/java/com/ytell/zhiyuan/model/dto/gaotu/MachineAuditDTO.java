package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(value = "MachineAuditDTO", description = "机器审核响应数据")
public class MachineAuditDTO {

    @ApiModelProperty(value = "业务线ID")
    private String businessLineId;

    @ApiModelProperty(value = "风控服务申请渠道ID")
    private String actionId;

    @ApiModelProperty(value = "内容ID")
    private String contentId;

    @ApiModelProperty(value = "内容版本")
    private String contentVersion;

    @ApiModelProperty(value = "数据类型")
    private String dataType;

    @ApiModelProperty(value = "事件ID")
    private String eventId;

    @ApiModelProperty(value = "审核结果")
    private String auditRs;

    @ApiModelProperty(value = "审核原因")
    private String reason;
}