package com.ytell.zhiyuan.web.controller.inner;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPrepareReq;
import com.ytell.zhiyuan.service.biz.PlanningStateService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** J5.5b 端点契约：路径、requestId、请求体摘要。 */
class PlanningStateControllerReviewFixPrepareTest {

    private MockMvc mockMvc;
    private PlanningStateService service;

    @BeforeEach
    void setUp() {
        service = mock(PlanningStateService.class);
        PrepareResultDTO prepared = new PrepareResultDTO();
        prepared.setStatus("prepared");
        prepared.setPendingId("pending-1");
        prepared.setOperationId("0123456789abcdef0123456789abcdef");
        when(service.prepareReviewFixProposal(anyLong(), anyLong(), anyString(), anyString(), any()))
                .thenReturn(prepared);

        PlanningStateController controller = new PlanningStateController();
        ReflectionTestUtils.setField(controller, "planningStateService", service);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(new ObjectMapper()))
                .build();
    }

    @Test
    void preparesThroughTheReviewPrepareEndpointWithMd5RequestBodyDigest() throws Exception {
        String body = "{\"proposalId\":\"fp_1\",\"previewDigest\":\"pd\",\"commandDigest\":\"cd\","
                + "\"evaluationVersion\":\"ev\",\"sourceVersionGuard\":7,"
                + "\"regenerateOrderedPlan\":true,\"rerunReview\":true}";

        mockMvc.perform(post("/gaotu-assistant-bot/inner/planning/7/session/fix-proposals/review/prepare")
                        .param("chatSessionId", "101")
                        .param("requestId", "req-1")
                        .contentType("application/json")
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("prepared"))
                .andExpect(jsonPath("$.data.pendingId").value("pending-1"));

        ArgumentCaptor<String> digest = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<ReviewFixPrepareReq> request = ArgumentCaptor.forClass(ReviewFixPrepareReq.class);
        verify(service).prepareReviewFixProposal(eq(7L), eq(101L), eq("req-1"),
                digest.capture(), request.capture());
        assertEquals(32, digest.getValue().length());
        assertTrue(digest.getValue().matches("[0-9a-f]{32}"));
        assertEquals("fp_1", request.getValue().getProposalId());
        assertEquals("pd", request.getValue().getPreviewDigest());
        assertEquals("cd", request.getValue().getCommandDigest());
        assertEquals("ev", request.getValue().getEvaluationVersion());
        assertEquals(Integer.valueOf(7), request.getValue().getSourceVersionGuard());
    }
}
