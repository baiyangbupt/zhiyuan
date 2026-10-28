package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.manager.cache.ConversationWsTicketStore;
import com.ytell.zhiyuan.mapper.UserMapper;
import com.ytell.zhiyuan.model.dto.conversation.TicketIdentity;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Objects;

/**
 * 会话归属与 WS 票据签发。
 *
 * <p>唯一入口是"这个登录用户能不能碰这个会话"。会话租户、会话用户、
 * 当前用户的租户都必须一致；签票时还要比对机器人。任何一项不符都回**同一个** 403——
 * 区分"不存在"与"不是你的"等于确认了一次越权探测。
 */
@Service
public class ConversationAccessService {

    private static final Logger log = LoggerFactory.getLogger(ConversationAccessService.class);

    @Autowired
    private ChatSessionSharedService chatSessionSharedService;

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private ConversationWsTicketStore ticketStore;

    /** 允许的来源，逗号分隔。**不做通配**：通配等于把票据的绑定意义抹掉。 */
    @Value("${conversation.ws.allowed-origins:http://127.0.0.1:3201}")
    private String allowedOrigins;

    public ChatSession requireOwnedSession(Long tenantId, Long sessionId, Long principalUserId) {
        if (tenantId == null || sessionId == null || principalUserId == null) {
            throw new ConversationAccessException(403, "session_forbidden");
        }
        ChatSession session = chatSessionSharedService.getById(sessionId);
        if (session == null
                || !Objects.equals(session.getTenantId(), tenantId)
                || !Objects.equals(session.getUserId(), principalUserId)) {
            // 与"不存在"同一个回包：不泄露 session 是否存在。
            throw new ConversationAccessException(403, "session_forbidden");
        }
        // 旧版允许账户在任意路径租户下创建会话；即便会话行归该 user，
        // 当前账户所属租户已不匹配时也不能继续读取旧会话或取得 WS 票据。
        User user = userMapper.selectById(principalUserId);
        if (user == null || !Objects.equals(user.getTenantId(), tenantId)) {
            throw new ConversationAccessException(403, "session_forbidden");
        }
        return session;
    }

    /**
     * 从**会话行**解析归属用户（给没有登录态的内部执行路径用）。
     *
     * <p>为什么不能从请求里带 userId ✗：`/**​/inner/**` 不走登录拦截器，调用方（网关）
     * 手上的 userId 不是本服务认证过的身份。归属只能以会话行为准——解析出来的 userId
     * 恰好就是当初建会话的那个人，`requireOwnedSession` 的三元比对因此恒成立，
     * 但这不削弱任何东西：能被解析出来的前提是租户已经对上。</p>
     */
    public Long requireSessionUserId(Long tenantId, Long sessionId) {
        if (tenantId == null || sessionId == null) {
            throw new ConversationAccessException(403, "session_forbidden");
        }
        ChatSession session = chatSessionSharedService.getById(sessionId);
        if (session == null
                || !Objects.equals(session.getTenantId(), tenantId)
                || session.getUserId() == null) {
            throw new ConversationAccessException(403, "session_forbidden");
        }
        return session.getUserId();
    }

    /**
     * 为一次握手签发票据。来源由**服务端**认定，取自请求的 Origin 且必须在白名单里。
     */
    public String issueTicket(Long tenantId, Long sessionId, Long botId, Long principalUserId, String requestOrigin) {
        ChatSession session = requireOwnedSession(tenantId, sessionId, principalUserId);
        if (botId != null && !Objects.equals(session.getBotId(), botId)) {
            throw new ConversationAccessException(403, "session_forbidden");
        }
        String origin = resolveOrigin(requestOrigin);
        return ticketStore.issue(TicketIdentity.builder()
                .tenantId(session.getTenantId())
                .sessionId(session.getId())
                .userId(session.getUserId())
                .botId(session.getBotId())
                .origin(origin)
                .build());
    }

    /** 消费票据。返回 null 表示无效；调用方负责拒绝握手。 */
    public TicketIdentity consumeTicket(String ticket, String requestOrigin) {
        return ticketStore.consume(ticket, requestOrigin);
    }

    private String resolveOrigin(String requestOrigin) {
        if (requestOrigin == null || requestOrigin.trim().isEmpty()) {
            // 没有 Origin 的请求（非浏览器/脚本）不发来源绑定的票：来源不明就不能说
            // "这张票只在该来源有效"。
            throw new ConversationAccessException(403, "origin_required");
        }
        String normalized = requestOrigin.trim();
        for (String allowed : allowedOriginsList()) {
            if (allowed.equals(normalized)) {
                return normalized;
            }
        }
        log.warn("conversation ws ticket requested from a non-allowed origin");
        throw new ConversationAccessException(403, "origin_forbidden");
    }

    private List<String> allowedOriginsList() {
        List<String> allowed = new ArrayList<String>();
        for (String item : Arrays.asList(allowedOrigins.split(","))) {
            String trimmed = item.trim();
            if (!trimmed.isEmpty()) {
                allowed.add(trimmed);
            }
        }
        return allowed;
    }
}
