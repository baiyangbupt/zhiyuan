package com.ytell.zhiyuan.web.controller.inner;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingRes;
import com.ytell.zhiyuan.model.dto.planning.CodexThreadBindingContextRes;
import com.ytell.zhiyuan.service.biz.CodexThreadBindingService;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

public class CodexConversationControllerTest {

    private MockMvc mockMvc;
    private CodexThreadBindingService service;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        CodexConversationController controller = new CodexConversationController();
        service = Mockito.mock(CodexThreadBindingService.class);
        ReflectionTestUtils.setField(controller, "bindingService", service);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(objectMapper))
                .build();
    }

    @Test
    void shouldRegisterBinding() throws Exception {
        CodexThreadBindingRes response = new CodexThreadBindingRes();
        response.setThreadId("thr_test");
        response.setHandle("opaque");
        doReturn(response).when(service).registerResponse(eq(1L), any());

        mockMvc.perform(post("/gaotu-assistant-bot/inner/codex/1/thread-binding")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"chatSessionId\":101,\"userId\":202,\"threadId\":\"thr_test\","
                                + "\"handle\":\"opaque\",\"allowedCapabilities\":[\"catalog.search_schools\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.threadId").value("thr_test"))
                .andExpect(jsonPath("$.data.handle").value("opaque"));
    }

    @Test
    void shouldReturnCurrentBindingForRecovery() throws Exception {
        CodexThreadBindingContextRes response = new CodexThreadBindingContextRes();
        response.setTenantId(1L);
        response.setChatSessionId(101L);
        response.setThreadId("thr_test");
        doReturn(response).when(service).current(eq(1L), eq(101L));

        mockMvc.perform(get("/gaotu-assistant-bot/inner/codex/1/thread-binding/current")
                        .param("chatSessionId", "101"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.tenantId").value(1))
                .andExpect(jsonPath("$.data.threadId").value("thr_test"));
    }

    @Test
    void shouldReturnNullDataWhenThereIsNoCurrentBinding() throws Exception {
        // "没有绑定"要走 200 + data=null，不是错误：Gateway 拿到它就该新建。
        // 换成错误码的话，恢复链路会把"可以新建"当成"后端坏了"，于是一律不新建。
        doReturn(null).when(service).current(eq(1L), eq(101L));

        mockMvc.perform(get("/gaotu-assistant-bot/inner/codex/1/thread-binding/current")
                        .param("chatSessionId", "101"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data").doesNotExist());
    }

    @Test
    void shouldRevokeBinding() throws Exception {
        mockMvc.perform(delete("/gaotu-assistant-bot/inner/codex/1/thread-binding")
                        .param("threadId", "thr_test"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));
        Mockito.verify(service).revoke(1L, "thr_test");
    }

    @Test
    void shouldResolveBindingContext() throws Exception {
        CodexThreadBindingContextRes response = new CodexThreadBindingContextRes();
        response.setChatSessionId(101L);
        response.setUserId(202L);
        response.setThreadId("thr_test");
        doReturn(response).when(service).resolveResponse(eq(1L), any());

        mockMvc.perform(post("/gaotu-assistant-bot/inner/codex/1/thread-binding/resolve")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"chatSessionId\":101,\"threadId\":\"thr_test\","
                                + "\"handle\":\"opaque\",\"capability\":\"catalog.search_schools\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.chatSessionId").value(101))
                .andExpect(jsonPath("$.data.userId").value(202));
    }
}
