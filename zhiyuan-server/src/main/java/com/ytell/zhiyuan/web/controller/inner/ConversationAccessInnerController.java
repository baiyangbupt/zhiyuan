package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.model.dto.conversation.TicketIdentity;
import com.ytell.zhiyuan.model.dto.conversation.WsTicketConsumeRes;
import com.ytell.zhiyuan.service.biz.ConversationAccessService;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 票据消费。**只给内部可信 Gateway**（前缀 `/inner/`，公网入口必须拒绝它）。
 *
 * <p>身份从票里换回来，不让 Gateway 自己解析 query 串——解析权在服务端。
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/inner/conversation")
@Api(tags = "对话票据消费")
public class ConversationAccessInnerController {

    @Autowired
    private ConversationAccessService conversationAccessService;

    @PostMapping("/ws-ticket/consume")
    public BaseResponse<WsTicketConsumeRes> consume(@RequestParam("ticket") String ticket,
                                                    @RequestHeader(value = "Origin", required = false) String origin) {
        TicketIdentity identity = conversationAccessService.consumeTicket(ticket, origin);
        if (identity == null) {
            // 无效/已用/过期/来源不符：**同一个回包**，不告诉对方是哪一种。
            throw new ConversationAccessException(403, "ticket_invalid");
        }
        WsTicketConsumeRes res = new WsTicketConsumeRes();
        res.setTenantId(identity.getTenantId());
        res.setSessionId(identity.getSessionId());
        res.setUserId(identity.getUserId());
        res.setBotId(identity.getBotId());
        res.setOrigin(identity.getOrigin());
        return BaseResponse.success(res);
    }
}
