package com.ytell.zhiyuan.web.controller;

import com.ytell.zhiyuan.common.config.GlobalExceptionHandler;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.model.vo.MessageVo;
import com.ytell.zhiyuan.service.biz.ChatMessageBizService;
import com.ytell.zhiyuan.service.biz.ChatSessionBizService;
import com.ytell.zhiyuan.service.biz.ConversationAccessService;
import com.ytell.zhiyuan.service.biz.UserBizService;
import com.ytell.zhiyuan.service.biz.UserProfileService;
import com.ytell.zhiyuan.service.biz.VolunteerBizService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ChatControllerAccessTest {

    private MockMvc mvc;
    private ChatSessionBizService sessions;
    private ChatMessageBizService messages;
    private UserProfileService profiles;
    private VolunteerBizService volunteers;
    private ConversationAccessService access;
    private UserBizService users;

    @BeforeEach
    void setUp() {
        ChatController controller = new ChatController();
        sessions = Mockito.mock(ChatSessionBizService.class);
        messages = Mockito.mock(ChatMessageBizService.class);
        profiles = Mockito.mock(UserProfileService.class);
        volunteers = Mockito.mock(VolunteerBizService.class);
        access = Mockito.mock(ConversationAccessService.class);
        users = Mockito.mock(UserBizService.class);
        ReflectionTestUtils.setField(controller, "chatSessionBizService", sessions);
        ReflectionTestUtils.setField(controller, "chatMessageBizService", messages);
        ReflectionTestUtils.setField(controller, "userProfileService", profiles);
        ReflectionTestUtils.setField(controller, "volunteerBizService", volunteers);
        ReflectionTestUtils.setField(controller, "conversationAccessService", access);
        ReflectionTestUtils.setField(controller, "userBizService", users);
        mvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        UserBaseData principal = new UserBaseData();
        principal.setUserId(7L);
        UserInfoThreadLocalUtil.set(principal);
        User user = new User();
        user.setId(7L);
        user.setTenantId(1L);
        when(users.getUserInfo(7L)).thenReturn(user);
    }

    @AfterEach
    void tearDown() {
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void foreignSessionCannotReadOrMutateAnyLegacySessionResource() throws Exception {
        when(access.requireOwnedSession(1L, 42L, 7L))
                .thenThrow(new ConversationAccessException(403, "session_forbidden"));

        mvc.perform(get("/gaotu-assistant-bot/chat/1/session/detail").param("chatSessionId", "42"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/session/update-tuition-range")
                        .param("chatSessionId", "42").contentType(MediaType.APPLICATION_JSON).content("{\"min\":1,\"max\":2}"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/session/update-score-detail")
                        .param("chatSessionId", "42").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/message/page")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"chatSessionId\":42}"))
                .andExpect(status().isForbidden());
        mvc.perform(get("/gaotu-assistant-bot/chat/1/volunteer/recommend-list").param("chatSessionId", "42"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/volunteer/submit").param("chatSessionId", "42"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/volunteer/export").param("chatSessionId", "42"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/user-basic-profile").param("chatSessionId", "42"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/user-dynastic-profile").param("chatSessionId", "42"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/1/user-dynastic-profile/save")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"chatSessionId\":42}"))
                .andExpect(status().isForbidden());

        Mockito.verifyNoInteractions(sessions, profiles, volunteers);
        Mockito.verifyNoInteractions(messages);
    }

    @Test
    void missingSessionIdCannotPageAllMessages() throws Exception {
        mvc.perform(post("/gaotu-assistant-bot/chat/1/message/page")
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.msg").value("session_forbidden"));
        Mockito.verifyNoInteractions(messages);
    }

    @Test
    void messageFeedbackChecksTheMessageSessionBeforeMutation() throws Exception {
        MessageVo foreign = new MessageVo();
        foreign.setId(9L);
        foreign.setChatSessionId(42L);
        when(messages.getMessageById(1L, 9L)).thenReturn(foreign);
        when(access.requireOwnedSession(1L, 42L, 7L))
                .thenThrow(new ConversationAccessException(403, "session_forbidden"));

        mvc.perform(post("/gaotu-assistant-bot/chat/1/message/feedback")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"messageId\":9,\"feedback\":1}"))
                .andExpect(status().isForbidden());
        Mockito.verify(messages, Mockito.never()).updateMessageFeedback(any(), any(), any());
    }

    @Test
    void crossTenantAccountCannotCreateOrPageSessions() throws Exception {
        mvc.perform(post("/gaotu-assistant-bot/chat/2/session/create")
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/gaotu-assistant-bot/chat/2/session/page")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"userId\":8}"))
                .andExpect(status().isForbidden());
        Mockito.verifyNoInteractions(sessions);
    }

    @Test
    void ownedSessionDelegatesWithThePrincipalFromLoginContext() throws Exception {
        mvc.perform(get("/gaotu-assistant-bot/chat/1/session/detail").param("chatSessionId", "42"))
                .andExpect(status().isOk());
        Mockito.verify(access).requireOwnedSession(1L, 42L, 7L);
        Mockito.verify(sessions).getUserSessionDetail(1L, 42L);
    }
}
