package com.ytell.zhiyuan.model.dto.inner;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel("志愿提交响应")
public class VolunteerSubmitResponse {

    @ApiModelProperty("响应数据")
    private String data;

    @ApiModelProperty("响应码")
    private Integer code;

    @ApiModelProperty("响应消息")
    private String msg;
}
