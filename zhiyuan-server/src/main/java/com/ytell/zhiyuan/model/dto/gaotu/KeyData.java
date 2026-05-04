package com.ytell.zhiyuan.model.dto.gaotu;

import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
public class KeyData {
    @ApiModelProperty("键")
    private String key;

    @ApiModelProperty("值")
    private String data;
}
