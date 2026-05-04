package com.ytell.zhiyuan.model.vo;


import com.ytell.zhiyuan.model.enums.DataType;
import lombok.Data;

@Data
public class ChatSessionExtraDataVo {
    private Long chatSessionId;
    private String dataKey;
    private DataType dataType;
    private Integer dataVersion;
    private Object dataValue;

}
