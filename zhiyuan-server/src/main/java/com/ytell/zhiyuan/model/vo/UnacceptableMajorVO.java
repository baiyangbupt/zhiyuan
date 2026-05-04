package com.ytell.zhiyuan.model.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;

/**
 * 不能接受的专业信息VO
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Data
@AllArgsConstructor
@ApiModel("不能接受的专业信息")
public class UnacceptableMajorVO {
    
    @ApiModelProperty("专业ID")
    private String majorId;

    
    @ApiModelProperty("专业二级名称")
    private String majorName;

    @ApiModelProperty("填报类型")
    private String subjectType;

    @ApiModelProperty("学历层次 (01-本科, 02-专科)")
    private String educationLevel;

}
