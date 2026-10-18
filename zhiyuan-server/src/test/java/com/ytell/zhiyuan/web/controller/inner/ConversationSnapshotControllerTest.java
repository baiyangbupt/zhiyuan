package com.ytell.zhiyuan.web.controller.inner;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.planning.ConversationTurnSnapshotDTO;
import com.ytell.zhiyuan.service.biz.ConversationSnapshotService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

public class ConversationSnapshotControllerTest {

    private MockMvc mockMvc;
    private ConversationSnapshotService snapshotService;

    @BeforeEach
    void setUp() {
        PlanningStateController controller = new PlanningStateController();
        snapshotService = Mockito.mock(ConversationSnapshotService.class);
        ReflectionTestUtils.setField(controller, "conversationSnapshotService", snapshotService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(new ObjectMapper()))
                .build();
    }

    @Test
    void shouldReturnTurnSnapshotForSkill() throws Exception {
        ConversationTurnSnapshotDTO snapshot = new ConversationTurnSnapshotDTO();
        snapshot.setSnapshotVersion(42);
        snapshot.setSessionId(101L);
        snapshot.setPlanningStage("candidate_exploration");
        doReturn(snapshot).when(snapshotService).getTurnSnapshot(eq(7L), eq(101L));

        mockMvc.perform(get("/gaotu-assistant-bot/inner/planning/7/session/turn-snapshot")
                        .param("chatSessionId", "101")
                        .param("skill", "candidate-recommendation")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.snapshotVersion").value(42))
                .andExpect(jsonPath("$.data.sessionId").value(101));
    }
}
