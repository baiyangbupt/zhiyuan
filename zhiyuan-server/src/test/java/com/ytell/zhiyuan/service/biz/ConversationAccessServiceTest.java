package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.manager.cache.ConversationWsTicketStore;
import com.ytell.zhiyuan.mapper.UserMapper;
import com.ytell.zhiyuan.model.dto.conversation.TicketIdentity;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

public class ConversationAccessServiceTest {

    private ConversationAccessService service;
    private ChatSessionSharedService sessionService;
    private UserMapper userMapper;
    private ConversationWsTicketStore ticketStore;

    @BeforeEach
    void setUp() {
        service = new ConversationAccessService();
        sessionService = Mockito.mock(ChatSessionSharedService.class);
        userMapper = Mockito.mock(UserMapper.class);
        ticketStore = Mockito.mock(ConversationWsTicketStore.class);
        ReflectionTestUtils.setField(service, "chatSessionSharedService", sessionService);
        ReflectionTestUtils.setField(service, "userMapper", userMapper);
        ReflectionTestUtils.setField(service, "ticketStore", ticketStore);
        ReflectionTestUtils.setField(service, "allowedOrigins", "http://127.0.0.1:3201,https://test-wwww.gaotuzhiyuan.com");
        User owner = new User();
        owner.setId(7L);
        owner.setTenantId(1L);
        when(userMapper.selectById(7L)).thenReturn(owner);
    }

    @Test
    void aValidOwnerGetsATicketBoundToTheServerSideIdentity() {
        when(sessionService.getById(42L)).thenReturn(session(1L, 7L, 3L));
        when(ticketStore.issue(any(TicketIdentity.class))).thenReturn("ticket-value");

        String ticket = service.issueTicket(1L, 42L, 3L, 7L, "http://127.0.0.1:3201");

        assertEquals("ticket-value", ticket);
    }

    @Test
    void anotherUsersSessionIsRefused() {
        when(sessionService.getById(42L)).thenReturn(session(1L, 7L, 3L));

        // 自报另一个 userId：这是越权，不是"输错了"。
        assertEquals(403, assertThrows(ConversationAccessException.class,
                () -> service.issueTicket(1L, 42L, 3L, 999L, "http://127.0.0.1:3201")).getStatus());
    }

    @Test
    void anotherTenantsSessionIsRefused() {
        when(sessionService.getById(42L)).thenReturn(session(1L, 7L, 3L));

        assertEquals(403, assertThrows(ConversationAccessException.class,
                () -> service.issueTicket(2L, 42L, 3L, 7L, "http://127.0.0.1:3201")).getStatus());
    }

    @Test
    void anOldCrossTenantSessionOwnedByTheSameUserIsStillRefused() {
        // 旧接口曾允许 user 7（租户 1）把自己的会话建在租户 2。
        when(sessionService.getById(42L)).thenReturn(session(2L, 7L, 3L));

        ConversationAccessException ex = assertThrows(ConversationAccessException.class,
                () -> service.requireOwnedSession(2L, 42L, 7L));
        assertEquals(403, ex.getStatus());
        assertEquals("session_forbidden", ex.getMessage());
    }

    @Test
    void deletedUserCannotReuseAnOldOwnedSession() {
        when(sessionService.getById(42L)).thenReturn(session(1L, 7L, 3L));
        when(userMapper.selectById(7L)).thenReturn(null);

        ConversationAccessException ex = assertThrows(ConversationAccessException.class,
                () -> service.requireOwnedSession(1L, 42L, 7L));
        assertEquals(403, ex.getStatus());
        assertEquals("session_forbidden", ex.getMessage());
    }

    @Test
    void aMissingSessionIsRefusedWithTheSameAnswerAsAForeignOne() {
        when(sessionService.getById(42L)).thenReturn(null);

        ConversationAccessException ex = assertThrows(ConversationAccessException.class,
                () -> service.issueTicket(1L, 42L, 3L, 7L, "http://127.0.0.1:3201"));

        // 区分"不存在"与"不是你的"等于确认了一次越权探测。
        assertEquals(403, ex.getStatus());
        assertEquals("session_forbidden", ex.getMessage());
    }

    @Test
    void aWrongBotIsRefused() {
        when(sessionService.getById(42L)).thenReturn(session(1L, 7L, 3L));

        assertEquals(403, assertThrows(ConversationAccessException.class,
                () -> service.issueTicket(1L, 42L, 99L, 7L, "http://127.0.0.1:3201")).getStatus());
    }

    @Test
    void aNonAllowlistedOriginIsRefused() {
        when(sessionService.getById(42L)).thenReturn(session(1L, 7L, 3L));

        // 通配来源等于把票据的绑定意义抹掉。
        assertEquals(403, assertThrows(ConversationAccessException.class,
                () -> service.issueTicket(1L, 42L, 3L, 7L, "https://evil.example.com")).getStatus());
    }

    @Test
    void aRequestWithoutOriginIsRefused() {
        when(sessionService.getById(42L)).thenReturn(session(1L, 7L, 3L));

        // 来源不明就不能说"这张票只在该来源有效"。
        assertEquals(403, assertThrows(ConversationAccessException.class,
                () -> service.issueTicket(1L, 42L, 3L, 7L, null)).getStatus());
    }

    @Test
    void consumeReturnsNullForAnythingInvalid() {
        when(ticketStore.consume("used", "http://127.0.0.1:3201")).thenReturn(null);

        assertNull(service.consumeTicket("used", "http://127.0.0.1:3201"));
    }

    @Test
    void consumeReturnsTheServerSideIdentity() {
        when(ticketStore.consume(any(String.class), any(String.class)))
                .thenReturn(TicketIdentity.builder().tenantId(1L).sessionId(42L).userId(7L).build());

        assertNotNull(service.consumeTicket("fresh", "http://127.0.0.1:3201"));
    }

    private static ChatSession session(Long tenantId, Long userId, Long botId) {
        ChatSession session = new ChatSession();
        session.setId(42L);
        session.setTenantId(tenantId);
        session.setUserId(userId);
        session.setBotId(botId);
        return session;
    }
}
