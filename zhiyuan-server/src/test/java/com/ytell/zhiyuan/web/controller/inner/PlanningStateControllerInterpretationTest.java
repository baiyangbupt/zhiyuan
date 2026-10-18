package com.ytell.zhiyuan.web.controller.inner;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationReq;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationRes;
import com.ytell.zhiyuan.model.dto.planning.LandingScenarioDTO;
import com.ytell.zhiyuan.service.biz.PlanAdmissionInterpretationFacade;
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

class PlanningStateControllerInterpretationTest {

    private MockMvc mockMvc;
    private PlanAdmissionInterpretationFacade facade;

    @BeforeEach
    void setUp() {
        PlanningStateController controller = new PlanningStateController();
        facade = Mockito.mock(PlanAdmissionInterpretationFacade.class);
        ReflectionTestUtils.setField(controller, "planAdmissionInterpretationFacade", facade);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(new ObjectMapper()))
                .build();
    }

    @Test
    void shouldReturnAdmissionInterpretationForTrustedSession() throws Exception {
        AdmissionInterpretationRes res = new AdmissionInterpretationRes();
        res.setStatus(AdmissionInterpretationRes.STATUS_COMPLETED);
        res.setPlanVersion(7);
        res.setAdmissionMode("major_group");
        LandingScenarioDTO base = new LandingScenarioDTO();
        base.setLabel(LandingScenarioDTO.LABEL_BASE);
        base.setStructureStatus(LandingScenarioDTO.STRUCTURE_FIRST_STABLE);
        res.setBaseLanding(base);
        doReturn(res).when(facade).interpret(eq(7L), eq(101L), any(AdmissionInterpretationReq.class));

        mockMvc.perform(post("/gaotu-assistant-bot/inner/planning/7/session/plan/admission-interpretation")
                        .param("chatSessionId", "101")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"planVersion\":7}")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.status").value("completed"))
                .andExpect(jsonPath("$.data.planVersion").value(7))
                .andExpect(jsonPath("$.data.baseLanding.label").value("base"));
    }
}
