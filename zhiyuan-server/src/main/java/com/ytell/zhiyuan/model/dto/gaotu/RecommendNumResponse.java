package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
public class RecommendNumResponse {
    @ApiModelProperty(value = "推荐院校数量")
    private Integer schoolNum;

    @ApiModelProperty(value = "推荐专业数量")
    private Integer majorNum;

    // OTOA-老高考:1个院校+所有专业
//OTOO-新高考:1个院校+1个专业
//OTON-新高考:1个院校+多个专业
//OTOOWL-首年新高考:分文理:1个院校+1个专业
//OTONWL-首年新高考:1个院校+多个专业
    private String type;
}