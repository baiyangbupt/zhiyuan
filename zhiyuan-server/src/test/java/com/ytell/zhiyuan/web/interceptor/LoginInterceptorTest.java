package com.ytell.zhiyuan.web.interceptor;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.test.util.ReflectionTestUtils;
import com.ytell.zhiyuan.service.biz.UserBizService;
import com.ytell.zhiyuan.model.entity.biz.UserCredential;
import com.ytell.zhiyuan.model.entity.biz.UserAuth;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.slf4j.LoggerFactory;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * 未登录的传输层语义：facade/ticket 路径必须是真实 401，其余路径保持业务码 800。
 */
public class LoginInterceptorTest {

    private final LoginInterceptor interceptor = new LoginInterceptor();
    private final UserBizService users = mock(UserBizService.class);

    @BeforeEach
    void setup() {
        UserInfoThreadLocalUtil.remove();
        ReflectionTestUtils.setField(interceptor, "userBizService", users);
    }

    @AfterEach
    void cleanup() {
        UserInfoThreadLocalUtil.remove();
    }

    private MockHttpServletRequest authenticated(String token, String platform) {
        MockHttpServletRequest request = new MockHttpServletRequest("GET",
                "/gaotu-assistant-bot/chat/1/planning/session/workspace-state");
        if (token != null) request.addHeader("tk", token);
        if (platform != null) request.addHeader("pf", platform);
        return request;
    }

    private void seedPreviousUser() {
        UserBaseData prior = new UserBaseData();
        prior.setUserId(999L);
        UserInfoThreadLocalUtil.set(prior);
    }

    @Test
    void reusedWorkerThreadClearsIdentityBeforeEachAuthenticationAndOnCompletion() throws Exception {
        UserCredential alice = new UserCredential();
        alice.setUserId(11L);
        UserCredential bob = new UserCredential();
        bob.setUserId(22L);
        when(users.getUserCredentialByToken(anyString())).thenAnswer(call -> {
            assertNull(UserInfoThreadLocalUtil.get(), "old identity must be gone before lookup");
            return "alice-token".equals(call.getArgument(0)) ? alice : bob;
        });
        seedPreviousUser();
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockHttpServletRequest first = authenticated("alice-token", "WEB");
        assertTrue(interceptor.preHandle(first, response, this));
        assertEquals(11L, UserInfoThreadLocalUtil.get().getUserId());
        assertEquals(AuthTypeEnum.WEB, UserInfoThreadLocalUtil.get().getAuthType());
        interceptor.afterCompletion(first, response, this, null);
        assertNull(UserInfoThreadLocalUtil.get());
        // Also cover a stale identity from a request whose callback never ran.
        seedPreviousUser();
        MockHttpServletRequest second = authenticated("bob-token", "APP");
        assertTrue(interceptor.preHandle(second, response, this));
        assertEquals(22L, UserInfoThreadLocalUtil.get().getUserId());
        assertEquals(AuthTypeEnum.APP, UserInfoThreadLocalUtil.get().getAuthType());
        interceptor.afterCompletion(second, response, this, new RuntimeException("controller failure"));
        assertNull(UserInfoThreadLocalUtil.get());
    }

    @Test
    void everyRejectedAuthenticationClearsPreviousWorkerIdentity() {
        for (String[] headers : new String[][] {
                {null, "WEB"}, {"token", null}, {"token", ""}, {"token", "UNKNOWN_PLATFORM"},
                {"missing-token", "WEB"}, {"missing-token", "WECHAT_MP"}}) {
            seedPreviousUser();
            ConversationAccessException denied = assertThrows(ConversationAccessException.class,
                    () -> interceptor.preHandle(authenticated(headers[0], headers[1]),
                            new MockHttpServletResponse(), this));
            assertEquals(401, denied.getStatus());
            assertNull(UserInfoThreadLocalUtil.get());
        }
    }

    @Test
    void unknownPlatformUsesLegacyDenialAndNeverQueriesCredentials() {
        seedPreviousUser();
        MockHttpServletRequest request = authenticated("token", "UNKNOWN_PLATFORM");
        request.setRequestURI("/gaotu-assistant-bot/chat/1/session/detail");
        BusinessException denied = assertThrows(BusinessException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), this));
        assertEquals(800, denied.getStatus());
        assertNull(UserInfoThreadLocalUtil.get());
        verifyNoInteractions(users);
    }

    @Test
    void lookupExceptionCannotExposePreviousUserAndCompletionRemovesWechatIdentity() {
        seedPreviousUser();
        when(users.getUserCredentialByToken("database-failure")).thenThrow(new IllegalStateException("db"));
        assertThrows(IllegalStateException.class, () -> interceptor.preHandle(
                authenticated("database-failure", "WEB"), new MockHttpServletResponse(), this));
        assertNull(UserInfoThreadLocalUtil.get());
        UserAuth auth = new UserAuth();
        auth.setUserId(33L);
        auth.setUnionId("synthetic-union");
        auth.setOpenId("synthetic-open");
        when(users.getUserAuthByToken(AuthTypeEnum.WECHAT_MP, "wechat-token")).thenReturn(auth);
        MockHttpServletRequest request = authenticated("wechat-token", "WECHAT_MP");
        assertTrue(interceptor.preHandle(request, new MockHttpServletResponse(), this));
        assertEquals(33L, UserInfoThreadLocalUtil.get().getUserId());
        assertEquals("synthetic-open", UserInfoThreadLocalUtil.get().getOpenId());
        interceptor.afterCompletion(request, new MockHttpServletResponse(), this, new RuntimeException("failure"));
        assertNull(UserInfoThreadLocalUtil.get());
        seedPreviousUser();
        UserInfoThreadLocalUtil.set(null);
        assertNull(UserInfoThreadLocalUtil.get());
    }

    @Test
    void asyncHandoffClearsTheOriginalWorkerBeforeCompletion() {
        seedPreviousUser();
        interceptor.afterConcurrentHandlingStarted(authenticated("token", "WEB"),
                new MockHttpServletResponse(), this);
        assertNull(UserInfoThreadLocalUtil.get());
    }

    @Test
    void missingPlatformNeverLogsRawBearerToken() {
        String token = "synthetic-secret-must-never-appear";
        Logger logger = (Logger) LoggerFactory.getLogger(LoginInterceptor.class);
        ch.qos.logback.classic.Level previousLevel = logger.getLevel();
        logger.setLevel(ch.qos.logback.classic.Level.INFO);
        ListAppender<ILoggingEvent> logs = new ListAppender<>();
        logs.start();
        logger.addAppender(logs);
        try {
            assertThrows(ConversationAccessException.class, () -> interceptor.preHandle(
                    authenticated(token, null), new MockHttpServletResponse(), this));
            assertTrue(logs.list.stream().noneMatch(event -> event.getFormattedMessage().contains(token)));
        } finally {
            logger.detachAppender(logs);
            logger.setLevel(previousLevel);
            logs.stop();
        }
    }

    @Test
    void unauthenticatedFacadeRequestGetsAReal401() {
        MockHttpServletRequest request = new MockHttpServletRequest("GET",
                "/gaotu-assistant-bot/chat/1/planning/session/workspace-state");

        ConversationAccessException ex = assertThrows(ConversationAccessException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));

        assertEquals(401, ex.getStatus());
    }

    @Test
    void unauthenticatedWriteFacadeRequestAlsoGetsAReal401() {
        MockHttpServletRequest request = new MockHttpServletRequest("POST",
                "/gaotu-assistant-bot/chat/7/planning/session/ordered-plan/move");

        ConversationAccessException ex = assertThrows(ConversationAccessException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));

        assertEquals(401, ex.getStatus());
    }

    @Test
    void unauthenticatedLegacyChatPathKeepsTheBusinessCode() {
        MockHttpServletRequest request = new MockHttpServletRequest("GET",
                "/gaotu-assistant-bot/chat/1/session/detail");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));

        assertEquals(800, ex.getStatus());
    }

    @Test
    void theFacadeRuleDoesNotMatchInnerPlanningPaths() {
        // inner 面本来就被 excludePathPatterns 排除；这里额外证明规则本身不会吃掉它，
        // 避免将来 exclude 调整时 401 语义被误扩到 inner。
        MockHttpServletRequest request = new MockHttpServletRequest("GET",
                "/gaotu-assistant-bot/inner/planning/1/session/state");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));

        assertEquals(800, ex.getStatus());
    }

    @Test
    void theFacadeRuleDoesNotMatchOtherChatSubPaths() {
        MockHttpServletRequest request = new MockHttpServletRequest("GET",
                "/gaotu-assistant-bot/chat/1/volunteer/recommend-list");

        BusinessException ex = assertThrows(BusinessException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));

        assertEquals(800, ex.getStatus());
    }
}
