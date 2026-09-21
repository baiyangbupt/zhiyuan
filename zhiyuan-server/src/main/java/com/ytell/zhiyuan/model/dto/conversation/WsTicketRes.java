package com.ytell.zhiyuan.model.dto.conversation;

import lombok.Data;

/** 票据响应。**只在这一条响应里出现明文票据**，服务端此后只留哈希。 */
@Data
public class WsTicketRes {
    private String ticket;
    private Integer expiresInSeconds;
}
