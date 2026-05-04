package com.ytell.zhiyuan.model.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 民族信息VO
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Data
@ApiModel("民族信息")
public class EthnicityVO {
    
    @ApiModelProperty("民族代码")
    private String code;
    
    @ApiModelProperty("民族名称")
    private String name;
    
    @ApiModelProperty("是否少数民族")
    private Boolean isMinority;
    
    public EthnicityVO() {}
    
    public EthnicityVO(String code, String name, Boolean isMinority) {
        this.code = code;
        this.name = name;
        this.isMinority = isMinority;
    }
}
