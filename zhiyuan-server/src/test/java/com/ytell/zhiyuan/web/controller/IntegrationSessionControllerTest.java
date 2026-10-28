package com.ytell.zhiyuan.web.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.common.config.GlobalExceptionHandler;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeReq;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeRes;
import com.ytell.zhiyuan.model.entity.biz.User;
import com.ytell.zhiyuan.service.biz.IntegrationSessionService;
import com.ytell.zhiyuan.service.biz.UserBizService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

public class IntegrationSessionControllerTest {

    private MockMvc mockMvc;
    private IntegrationSessionService integrationSessionService;
    private UserBizService userBizService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        IntegrationSessionController controller = new IntegrationSessionController();
        integrationSessionService = Mockito.mock(IntegrationSessionService.class);
        userBizService = Mockito.mock(UserBizService.class);
        ReflectionTestUtils.setField(controller, "integrationSessionService", integrationSessionService);
        ReflectionTestUtils.setField(controller, "userBizService", userBizService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(objectMapper))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        UserBaseData principal = new UserBaseData();
        principal.setUserId(7L);
        UserInfoThreadLocalUtil.set(principal);
        User user = new User();
        user.setId(7L);
        user.setTenantId(1L);
        doReturn(user).when(userBizService).getUserInfo(7L);
    }

    @AfterEach
    void tearDown() {
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void rejectsCrossTenantInitializationBeforeCreatingSession() throws Exception {
        mockMvc.perform(post("/gaotu-assistant-bot/chat/2/integration/session/initialize")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"externalRequestId\":\"ext-1\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.msg").value("session_forbidden"));
        Mockito.verifyNoInteractions(integrationSessionService);
    }

    @Test
    void shouldInitializeExternalSession() throws Exception {
        ExternalSessionInitializeRes res = new ExternalSessionInitializeRes();
        res.setTenantId(1L);
        res.setChatSessionId(1002L);
        res.setExternalRequestId("ext-1");
        res.setStudentName("高翔");
        res.setCreated(true);
        res.setSessionUrl("https://example.com/assistant-pc/sessionDetailV2?chatSessionId=1002");
        res.getPlanning().setPhase("ordered");
        res.getPlanning().setOrderedTotal(45);
        doReturn(res).when(integrationSessionService).initializeSession(eq(1L), any(ExternalSessionInitializeReq.class));

        ExternalSessionInitializeReq req = new ExternalSessionInitializeReq();
        req.setExternalRequestId("ext-1");

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/integration/session/initialize")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.chatSessionId").value(1002))
                .andExpect(jsonPath("$.data.externalRequestId").value("ext-1"))
                .andExpect(jsonPath("$.data.studentName").value("高翔"))
                .andExpect(jsonPath("$.data.created").value(true))
                .andExpect(jsonPath("$.data.planning.phase").value("ordered"))
                .andExpect(jsonPath("$.data.planning.orderedTotal").value(45));
    }

    @Test
    void shouldInitializeExternalSessionWithV1Path() throws Exception {
        ExternalSessionInitializeRes res = new ExternalSessionInitializeRes();
        res.setTenantId(1L);
        res.setChatSessionId(1002L);
        res.setExternalRequestId("ext-1");
        res.setStudentName("高翔");
        res.setCreated(true);
        doReturn(res).when(integrationSessionService).initializeSession(eq(1L), any(ExternalSessionInitializeReq.class));

        ExternalSessionInitializeReq req = new ExternalSessionInitializeReq();
        req.setExternalRequestId("ext-1");

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/integration/v1/session/initialize")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.chatSessionId").value(1002))
                .andExpect(jsonPath("$.data.studentName").value("高翔"));
    }

    @Test
    void shouldBindSnakeCaseStrategyTypeOnExternalSessionRequest() throws Exception {
        ExternalSessionInitializeRes res = new ExternalSessionInitializeRes();
        res.setTenantId(1L);
        res.setChatSessionId(1002L);
        res.setExternalRequestId("ext-1");
        res.setCreated(true);
        doReturn(res).when(integrationSessionService).initializeSession(eq(1L), any(ExternalSessionInitializeReq.class));

        String body = "{"
                + "\"externalRequestId\":\"ext-1\","
                + "\"createSession\":{"
                + "\"strategy_type\":{\"code\":\"cautious\",\"name\":\"稳妥型\"}"
                + "}"
                + "}";

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/integration/session/initialize")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.chatSessionId").value(1002));

        ArgumentCaptor<ExternalSessionInitializeReq> reqCaptor = ArgumentCaptor.forClass(ExternalSessionInitializeReq.class);
        Mockito.verify(integrationSessionService).initializeSession(eq(1L), reqCaptor.capture());
        assertNotNull(reqCaptor.getValue().getCreateSession());
        assertNotNull(reqCaptor.getValue().getCreateSession().getStrategyType());
        assertEquals("cautious", reqCaptor.getValue().getCreateSession().getStrategyType().getCode());
        assertEquals("稳妥型", reqCaptor.getValue().getCreateSession().getStrategyType().getName());
    }
}
