package com.ytell.zhiyuan.model.dto.gaotu.req;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(value = "MachineAuditReq", description = "机器审核请求参数")
public class MachineAuditReq {

    @ApiModelProperty(value = "风控服务申请渠道ID", required = true)
    private String actionId;

    @ApiModelProperty(value = "业务线ID，高途固定是702", required = true)
    private String businessLineId = "702";

    @ApiModelProperty(value = "审核内容", required = true)
    private String content;

    @ApiModelProperty(value = "内容ID，用于区分和幂等", required = true)
    private String contentId;

    @ApiModelProperty(value = "内容版本", required = true)
    private String contentVersion;

    @ApiModelProperty(value = "数据类型，文本固定为TXT01", required = true)
    private String dataType = "TXT01";

    @ApiModelProperty(value = "是否匿名", required = true)
    private Boolean ifAnonymous = false;

    @ApiModelProperty(value = "是否富文本", required = true)
    private Boolean ifRichText = false;

    @ApiModelProperty(value = "发布时间", required = true)
    private String publishTime;

    @ApiModelProperty(value = "用户ID", required = true)
    private String userId;
}