package com.ytell.zhiyuan.model.dto.conversation;

import lombok.Data;

@Data
public class WsTicketReq {
    private Long sessionId;
    private Long botId;
}
