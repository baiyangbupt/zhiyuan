package com.ytell.zhiyuan.model.req;

import lombok.Data;

@Data
public class MessageFeedbackReq {
    private Long messageId;
    private Integer feedback;
}
