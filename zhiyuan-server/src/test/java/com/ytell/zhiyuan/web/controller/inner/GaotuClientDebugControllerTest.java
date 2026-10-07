package com.ytell.zhiyuan.web.controller.inner;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.gaotu.req.ScorePositionRangeReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import com.ytell.zhiyuan.service.GaotuService;
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
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doReturn;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 分数 → 位次（一分一段）内部端点的两条口径用例：
 * 有数据（回区间最高/最低位次）与无数据（如实回空，不估算）。
 */
public class GaotuClientDebugControllerTest {

    private MockMvc mockMvc;
    private GaotuService gaotuService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        GaotuClientDebugController controller = new GaotuClientDebugController();
        gaotuService = Mockito.mock(GaotuService.class);
        ReflectionTestUtils.setField(controller, "gaotuService", gaotuService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(objectMapper))
                .build();
    }

    @Test
    void shouldReturnTheRankRangeForZhejiang610() throws Exception {
        // 2026-10-07 实测读数（浙江 610，dataLevel=01）：students=1051、
        // 42829~43879——同分 1051 人，区间即口径。
        ScorePositionRangeRes data = new ScorePositionRangeRes();
        data.setScore("610");
        data.setStudents(1051);
        data.setHighestRank(42829);
        data.setLowestRank(43879);
        data.setDataLevel("01");
        doReturn(data).when(gaotuService).getScorePositionRange(any(ScorePositionRangeReq.class));

        mockMvc.perform(post("/gaotu-assistant-bot/inner/gaotu/catalog/score-position")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"areaId\":\"330000\",\"subject\":\"N\",\"dataLevel\":\"01\","
                                + "\"year\":\"2026\",\"score\":\"610\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.score").value("610"))
                .andExpect(jsonPath("$.data.students").value(1051))
                .andExpect(jsonPath("$.data.highestRank").value(42829))
                .andExpect(jsonPath("$.data.lowestRank").value(43879))
                .andExpect(jsonPath("$.data.dataLevel").value("01"));

        // 请求参数按上游口径原样进 service（areaId/subject/dataLevel/year/score）。
        ArgumentCaptor<ScorePositionRangeReq> captor =
                ArgumentCaptor.forClass(ScorePositionRangeReq.class);
        Mockito.verify(gaotuService).getScorePositionRange(captor.capture());
        assertEquals("330000", captor.getValue().getAreaId());
        assertEquals("N", captor.getValue().getSubject());
        assertEquals("01", captor.getValue().getDataLevel());
        assertEquals("2026", captor.getValue().getYear());
        assertEquals("610", captor.getValue().getScore());
    }

    @Test
    void shouldReturnNullDataWhenTheProvinceHasNoScorePosition() throws Exception {
        // 上游没有该省的一分一段数据（如安徽）：data=null 如实回空，业务码仍是 0
        // （"没有这份数据"不是查询失败）。调用方据此说"不可用"，绝不估算。
        doReturn(null).when(gaotuService).getScorePositionRange(any(ScorePositionRangeReq.class));

        mockMvc.perform(post("/gaotu-assistant-bot/inner/gaotu/catalog/score-position")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"areaId\":\"340000\",\"subject\":\"N\",\"dataLevel\":\"01\","
                                + "\"year\":\"2026\",\"score\":\"610\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data").doesNotExist());
    }
}
