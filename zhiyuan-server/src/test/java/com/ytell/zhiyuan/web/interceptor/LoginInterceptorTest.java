package com.ytell.zhiyuan.web.interceptor;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * 未登录的传输层语义：facade/ticket 路径必须是真实 401，其余路径保持业务码 800。
 */
public class LoginInterceptorTest {

    private final LoginInterceptor interceptor = new LoginInterceptor();

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
