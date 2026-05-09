package com.ytell.zhiyuan.web.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeReq;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeRes;
import com.ytell.zhiyuan.service.biz.IntegrationSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

public class IntegrationSessionControllerTest {

    private MockMvc mockMvc;
    private IntegrationSessionService integrationSessionService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        IntegrationSessionController controller = new IntegrationSessionController();
        integrationSessionService = Mockito.mock(IntegrationSessionService.class);
        ReflectionTestUtils.setField(controller, "integrationSessionService", integrationSessionService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(objectMapper))
                .build();
    }

    @Test
    void shouldInitializeExternalSession() throws Exception {
        ExternalSessionInitializeRes res = new ExternalSessionInitializeRes();
        res.setTenantId(1L);
        res.setChatSessionId(1002L);
        res.setExternalRequestId("ext-1");
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
                .andExpect(jsonPath("$.data.created").value(true))
                .andExpect(jsonPath("$.data.planning.phase").value("ordered"))
                .andExpect(jsonPath("$.data.planning.orderedTotal").value(45));
    }
}
