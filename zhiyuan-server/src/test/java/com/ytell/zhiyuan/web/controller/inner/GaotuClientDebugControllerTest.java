package com.ytell.zhiyuan.web.controller.inner;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import com.ytell.zhiyuan.model.dto.gaotu.req.ScorePositionRangeReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.biz.ChatSessionBizService;
import com.ytell.zhiyuan.service.biz.MajorRecommendPreviewService;
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
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 内部端点（gaotu catalog 一族）的口径用例：
 * 一分一段的有数据/无数据两条，加上专业方向推荐预览的"无档案如实回空"与
 * "有档案回裁剪后的 items（字段名照实体）"两条。
 */
public class GaotuClientDebugControllerTest {

    private MockMvc mockMvc;
    private GaotuService gaotuService;
    private ChatSessionBizService chatSessionBizService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        GaotuClientDebugController controller = new GaotuClientDebugController();
        gaotuService = Mockito.mock(GaotuService.class);
        ReflectionTestUtils.setField(controller, "gaotuService", gaotuService);
        // 专业方向预览：接**真服务**，只把会话读写层换替身——端点上量的是完整合同
        // （data:null + 原因码、items 的 JSON 字段名），替身换在服务外层就只能量到替身。
        chatSessionBizService = Mockito.mock(ChatSessionBizService.class);
        MajorRecommendPreviewService previewService = new MajorRecommendPreviewService();
        ReflectionTestUtils.setField(previewService, "chatSessionBizService", chatSessionBizService);
        ReflectionTestUtils.setField(controller, "majorRecommendPreviewService", previewService);
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

    @Test
    void shouldReturnNullDataWithReasonWhenMajorRecommendHasNoProfile() throws Exception {
        // 没有 userScoreDetail 行（空会话）：data=null + 原因码，业务码仍是 0
        //（"没有这份画像"不是查询失败）。调用方据此说"不可用"，绝不拿热度榜顶替。
        doReturn(null).when(chatSessionBizService).loadSessionScoreDetail(900123L);

        mockMvc.perform(post("/gaotu-assistant-bot/inner/gaotu/catalog/major-recommend")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"chatSessionId\":900123}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.msg").value("session_profile_missing"))
                .andExpect(jsonPath("$.data").doesNotExist());

        verify(chatSessionBizService, never()).recommendMajor(any(CreateSessionReq.class));
    }

    @Test
    void shouldReturnTrimmedMajorItemsForASessionWithProfile() throws Exception {
        // items 的 JSON 字段名照 `MajorRecommendItem` 的实体注解（major_id/salary_avg…）——
        // Agent 侧工具按这套字段名取值，改了名字这里先红。
        doReturn(fullProfile()).when(chatSessionBizService).loadSessionScoreDetail(900123L);
        RecommendSubMajorResponse.MajorRecommendItem item =
                new RecommendSubMajorResponse.MajorRecommendItem();
        item.setMajorId("0809");
        item.setMajor("计算机类");
        item.setScore(88.5);
        item.setGenderIndex(70.0);
        item.setSatisfyIndex(80.0);
        item.setSalaryAvg(72.5);
        item.setHotIndex(91.0);
        doReturn(Lists.newArrayList(item)).when(chatSessionBizService).recommendMajor(any(CreateSessionReq.class));

        mockMvc.perform(post("/gaotu-assistant-bot/inner/gaotu/catalog/major-recommend")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"chatSessionId\":900123,\"topN\":3}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.msg").value("ok"))
                .andExpect(jsonPath("$.data.topN").value(3))
                .andExpect(jsonPath("$.data.items[0].major_id").value("0809"))
                .andExpect(jsonPath("$.data.items[0].major").value("计算机类"))
                .andExpect(jsonPath("$.data.items[0].score").value(88.5))
                .andExpect(jsonPath("$.data.items[0].salary_avg").value(72.5));
    }

    /** rank 算法读得动的完整画像（batch/subjectType/sex/subjectList/strengthSubjectList 齐）。 */
    private CreateSessionReq fullProfile() {
        CreateSessionReq profile = new CreateSessionReq();
        profile.setTotalScore(610);
        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setCode("17");
        batch.setLevel("01");
        profile.setBatch(batch);
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("N");
        subjectType.setDesc("综合");
        profile.setSubjectType(subjectType);
        CreateSessionReq.Sex sex = new CreateSessionReq.Sex();
        sex.setCode("male");
        profile.setSex(sex);
        profile.setSubjectList(Lists.newArrayList(
                new CreateSessionReq.SubjectItem(1, "01", "01", "物理")));
        CreateSessionReq.SubjectScore strength = new CreateSessionReq.SubjectScore();
        strength.setSubject("01");
        strength.setSubjectName("物理");
        profile.setStrengthSubjectList(Lists.newArrayList(strength));
        return profile;
    }
}
