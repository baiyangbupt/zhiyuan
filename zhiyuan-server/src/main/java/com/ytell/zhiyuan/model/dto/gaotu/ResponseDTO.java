package com.ytell.zhiyuan.model.dto.gaotu;

import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.io.Serializable;
import java.util.List;

@Data
@ApiModel(value = "ResponseDTO", description = "高途服务通用响应格式")
public class ResponseDTO<T> implements Serializable {

    private static final long serialVersionUID = 1L;

    @ApiModelProperty(value = "响应码")
    private Integer code;

    @ApiModelProperty(value = "响应消息")
    private String msg;

    @ApiModelProperty(value = "响应数据")
    private T data;

    @ApiModelProperty(value = "上游数据版本；缺失表示上游未提供版本，不签发证据")
    private String dataVersion;

    @ApiModelProperty(value = "Java 签发的权威证据；缺失表示本次未签发，调用方不得自行补造")
    private List<ConversationEvidenceDTO> evidence;

}