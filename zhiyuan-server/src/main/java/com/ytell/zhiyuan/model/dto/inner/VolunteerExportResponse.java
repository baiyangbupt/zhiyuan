package com.ytell.zhiyuan.model.dto.inner;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel("志愿导出响应")
public class VolunteerExportResponse {

    @ApiModelProperty("生成的志愿文件地址")
    private String data;

    @ApiModelProperty("响应码")
    private Integer code;

    @ApiModelProperty("响应消息")
    private String msg;
}
