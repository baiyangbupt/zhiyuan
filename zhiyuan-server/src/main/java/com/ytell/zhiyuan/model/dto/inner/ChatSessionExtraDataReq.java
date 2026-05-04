package com.ytell.zhiyuan.model.dto.inner;

import com.ytell.zhiyuan.model.enums.DataType;
import lombok.Data;

@Data
public class ChatSessionExtraDataReq {
    private Long chatSessionId;
    private String dataKey;
    private DataType dataType;
    private Object dataValue;
    private Integer version = 0;
}
