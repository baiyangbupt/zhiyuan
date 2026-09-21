package com.ytell.zhiyuan.model.dto.conversation;

import lombok.Data;

/** 只给内部可信 Gateway：消费票据后换回的身份。 */
@Data
public class WsTicketConsumeRes {
    private Long tenantId;
    private Long sessionId;
    private Long userId;
    private Long botId;
    private String origin;
}
