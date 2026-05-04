package com.ytell.zhiyuan.model.req;

import lombok.Data;

@Data
public class MessageRiskDataReq {

    private Long chatSessionId;

    private String content;

}
