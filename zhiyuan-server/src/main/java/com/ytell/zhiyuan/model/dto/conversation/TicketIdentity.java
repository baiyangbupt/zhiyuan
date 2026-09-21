package com.ytell.zhiyuan.model.dto.conversation;

import lombok.Builder;
import lombok.Data;

/**
 * 一张 WS 票据换回来的身份。
 *
 * <p>**身份来自服务端查库**，不是票据里自带的字段：票里存的是服务端写入的值，
 * 而这些值的来源是 {@code ChatSession}（租户/用户/机器人逐项比对过）。
 * 浏览器无从改写——它只能出示票，不能出示身份。
 */
@Data
@Builder
public class TicketIdentity {
    private Long tenantId;
    private Long sessionId;
    private Long userId;
    private Long botId;
    /** 签发时认定的来源；消费时不一致即拒绝。 */
    private String origin;
}
