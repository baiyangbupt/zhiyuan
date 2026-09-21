package com.ytell.zhiyuan.web.controller;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.conversation.WsTicketReq;
import com.ytell.zhiyuan.model.dto.conversation.WsTicketRes;
import com.ytell.zhiyuan.service.biz.ConversationAccessService;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 浏览器换取 WebSocket 票据。
 *
 * <p>登录态仍然走既有 `LoginInterceptor`（tk/pf）；这里只多做一件事：
 * 确认**这个登录用户确实是这个会话的主人**，然后发一张 60 秒的一次性票。
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/chat/{tenantId}/conversation")
@Api(tags = "对话访问票据")
public class ConversationAccessController {

    @Autowired
    private ConversationAccessService conversationAccessService;

    @PostMapping("/ws-ticket")
    public BaseResponse<WsTicketRes> issueTicket(@PathVariable("tenantId") Long tenantId,
                                                 @RequestBody WsTicketReq req,
                                                 @RequestHeader(value = "Origin", required = false) String origin) {
        Long principalUserId = UserInfoThreadLocalUtil.get().getUserId();
        String ticket = conversationAccessService.issueTicket(
                tenantId, req == null ? null : req.getSessionId(),
                req == null ? null : req.getBotId(), principalUserId, origin);
        WsTicketRes res = new WsTicketRes();
        res.setTicket(ticket);
        res.setExpiresInSeconds(com.ytell.zhiyuan.manager.cache.ConversationWsTicketStore.TTL_SECONDS);
        return BaseResponse.success(res);
    }
}
