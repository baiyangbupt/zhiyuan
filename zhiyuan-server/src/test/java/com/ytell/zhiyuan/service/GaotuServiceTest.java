package com.ytell.zhiyuan.service;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.config.GaotuProperties;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.gaotu.GaotuClient;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import com.ytell.zhiyuan.model.dto.gaotu.ResponseDTO;
import com.ytell.zhiyuan.model.dto.gaotu.req.ExpertAIProgramPageReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.ProgramPageReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.RecommendNumReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.ScorePositionRangeReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import com.ytell.zhiyuan.model.dto.gaotu.res.UserInfoByTokenRes;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.net.SocketTimeoutException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.when;

class GaotuServiceTest {

    @Test
    void shouldReturnReadableMessageWhenSubjectInfoMissing() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);

        ResponseDTO<UserInfoByTokenRes> response = new ResponseDTO<>();
        response.setCode(110);
        response.setMsg("\u7528\u6237\u9009\u79d1\u4fe1\u606f\u4e0d\u5b58\u5728");
        when(gaotuClient.getUserInfoByToken("token-a")).thenReturn(response);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.getUserInfoByToken("token-a"));

        assertEquals(110, exception.getStatus());
        assertEquals("\u8bf7\u5728\u9996\u9875\u5b8c\u5584\u9ad8\u8003\u7701\u4efd\u548c\u9009\u79d1\u4fe1\u606f\u540e\u518d\u8fdb\u5165AI\u667a\u80fd\u586b\u62a5", exception.getMessage());
    }

    @Test
    void shouldReturnReadableMessageWhenVolunteerFullDataTimeout() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ProgramPageReq req = validProgramPageReq();

        when(gaotuClient.getProgramFullList(req)).thenThrow(volunteerDataTimeout());

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.queryAllProgramData(req));

        assertEquals(110, exception.getStatus());
        assertEquals("\u5fd7\u613f\u6570\u636e\u83b7\u53d6\u8d85\u65f6", exception.getMessage());
    }

    @Test
    void shouldReturnReadableMessageWhenRecommendProgramNumTimeout() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        RecommendNumReq req = new RecommendNumReq();

        when(gaotuClient.getRecommendProgramNum(req)).thenThrow(volunteerDataTimeout());

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.getRecommendProgramNum(req));

        assertEquals(110, exception.getStatus());
        assertEquals("\u5fd7\u613f\u6570\u636e\u83b7\u53d6\u8d85\u65f6", exception.getMessage());
    }

    @Test
    void shouldMergePagedProgramDataAsFullContract() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ProgramPageReq req = validProgramPageReq();

        when(gaotuClient.getProgramFullListInit(req)).thenReturn(success(initData(3, 2, 2)));
        when(gaotuClient.getProgramFullListPage(argThat(page -> isPage(page, 1L))))
                .thenReturn(success(pageData(1, details("m1", "m2"))));
        when(gaotuClient.getProgramFullListPage(argThat(page -> isPage(page, 2L))))
                .thenReturn(success(pageData(2, details("m3"))));

        JSONObject result = gaotuService.queryAllProgramData(req);

        assertEquals(3, result.getJSONArray("detailList").size());
        assertEquals("m1", result.getJSONArray("detailList").getJSONObject(0).getString("planMajorDataId"));
        assertEquals("m3", result.getJSONArray("detailList").getJSONObject(2).getString("planMajorDataId"));
        Mockito.verify(gaotuClient, Mockito.never()).getProgramFullList(req);
    }

    @Test
    void shouldFallbackToLegacyFullProgramDataWhenPagedInitFails() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ProgramPageReq req = validProgramPageReq();
        ResponseDTO<JSONObject> failed = new ResponseDTO<>();
        failed.setCode(500);
        failed.setMsg("init failed");
        JSONObject legacy = new JSONObject();
        legacy.put("detailList", details("legacy"));

        when(gaotuClient.getProgramFullListInit(req)).thenReturn(failed);
        when(gaotuClient.getProgramFullList(req)).thenReturn(success(legacy));

        JSONObject result = gaotuService.queryAllProgramData(req);

        assertEquals(1, result.getJSONArray("detailList").size());
        assertEquals("legacy", result.getJSONArray("detailList").getJSONObject(0).getString("planMajorDataId"));
    }

    @Test
    void shouldNotMaskVolunteerProgramTimeoutDuringRetry() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ProgramPageReq req = validProgramPageReq();

        when(gaotuClient.getProgramList(req)).thenThrow(volunteerDataTimeout());

        BusinessException exception = assertThrows(BusinessException.class,
                () -> gaotuService.queryAndSaveProgram(req, new RecommendNumResponse()));

        assertEquals(110, exception.getStatus());
        assertEquals("\u5fd7\u613f\u6570\u636e\u83b7\u53d6\u8d85\u65f6", exception.getMessage());
        Mockito.verify(gaotuClient, Mockito.times(1)).getProgramList(req);
    }

    // ── 位次查询的年份回退口径（2026-10-07 审查 M2）──────────────────────────
    // 只有"调用方没指定年份"才允许退回当年重试；指定了年份就不许换（否则 2025 查到的是
    // 2026 的一分一段，还会被补录链路当成 2025 的位次落库）。

    @Test
    void shouldNotRetryWithCurrentYearWhenYearPinnedAndNoDataForThatYear() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ScorePositionRangeReq req = positionReq("2025");

        // code=0 且 data=null："该省/该年份没有这份数据"的正常形状（不是错误码）。
        when(gaotuClient.getScorePositionRange(req)).thenReturn(noPositionData());

        ScorePositionRangeRes result = gaotuService.getScorePositionRange(req);

        assertNull(result);
        // 关键：一次都不许多试，更不许把请求里的年份改掉（静默换当年 = 跨年串数据）。
        Mockito.verify(gaotuClient, Mockito.times(1)).getScorePositionRange(req);
        assertEquals("2025", req.getYear());
    }

    @Test
    void shouldNotRetryWithCurrentYearWhenYearPinnedAndUpstreamFails() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ScorePositionRangeReq req = positionReq("2025");

        ResponseDTO<ScorePositionRangeRes> failed = new ResponseDTO<>();
        failed.setCode(110);
        failed.setMsg("查询失败");
        when(gaotuClient.getScorePositionRange(req)).thenReturn(failed);

        assertNull(gaotuService.getScorePositionRange(req));

        Mockito.verify(gaotuClient, Mockito.times(1)).getScorePositionRange(req);
        assertEquals("2025", req.getYear());
    }

    @Test
    void shouldRetryWithCurrentYearOnlyWhenYearNotSpecified() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ScorePositionRangeReq req = positionReq(null);

        ScorePositionRangeRes found = new ScorePositionRangeRes();
        found.setHighestRank(42000);
        found.setLowestRank(42829);
        ResponseDTO<ScorePositionRangeRes> ok = new ResponseDTO<>();
        ok.setCode(0);
        ok.setData(found);
        String currentYear = String.valueOf(java.time.Year.now().getValue());

        // 在调用发生的那一刻记下年份：实现会原地改写 req.year，事后回看对象已看不出第一次的形状。
        java.util.List<String> yearsSeen = new java.util.ArrayList<>();
        when(gaotuClient.getScorePositionRange(Mockito.any())).thenAnswer(invocation -> {
            ScorePositionRangeReq sent = invocation.getArgument(0);
            yearsSeen.add(sent.getYear());
            return sent.getYear() == null ? noPositionData() : ok;
        });

        ScorePositionRangeRes result = gaotuService.getScorePositionRange(req);

        assertEquals(Integer.valueOf(42829), result.getLowestRank());
        assertEquals(java.util.Arrays.asList(null, currentYear), yearsSeen,
                "第一次应不带年份，回退那一次才带当年");
        assertEquals(currentYear, req.getYear());
    }

    @Test
    void shouldReturnDataWithoutAnyRetryWhenYearPinnedAndFound() {
        GaotuClient gaotuClient = Mockito.mock(GaotuClient.class);
        GaotuService gaotuService = serviceWithClient(gaotuClient);
        ScorePositionRangeReq req = positionReq("2025");

        ScorePositionRangeRes found = new ScorePositionRangeRes();
        found.setLowestRank(43879);
        ResponseDTO<ScorePositionRangeRes> ok = new ResponseDTO<>();
        ok.setCode(0);
        ok.setData(found);
        when(gaotuClient.getScorePositionRange(req)).thenReturn(ok);

        assertEquals(Integer.valueOf(43879), gaotuService.getScorePositionRange(req).getLowestRank());
        Mockito.verify(gaotuClient, Mockito.times(1)).getScorePositionRange(req);
    }

    private ScorePositionRangeReq positionReq(String year) {
        ScorePositionRangeReq req = new ScorePositionRangeReq();
        req.setAreaId("330000");
        req.setSubject("N");
        req.setDataLevel("01");
        req.setScore("610");
        req.setYear(year);
        return req;
    }

    private ResponseDTO<ScorePositionRangeRes> noPositionData() {
        ResponseDTO<ScorePositionRangeRes> response = new ResponseDTO<>();
        response.setCode(0);
        response.setMsg("ok");
        response.setData(null);
        return response;
    }

    private GaotuService serviceWithClient(GaotuClient gaotuClient) {
        GaotuService gaotuService = new GaotuService();
        ReflectionTestUtils.setField(gaotuService, "gaotuClient", gaotuClient);
        ReflectionTestUtils.setField(gaotuService, "gaotuProperties", new GaotuProperties());
        return gaotuService;
    }

    private ProgramPageReq validProgramPageReq() {
        ProgramPageReq req = new ProgramPageReq();
        req.setAreaId("110000");
        req.setPrepareType("PREDICT");
        return req;
    }

    private RuntimeException volunteerDataTimeout() {
        return new RuntimeException("invoke HTTP error", new SocketTimeoutException("Read timed out"));
    }

    private ResponseDTO<JSONObject> success(JSONObject data) {
        ResponseDTO<JSONObject> response = new ResponseDTO<>();
        response.setCode(0);
        response.setData(data);
        return response;
    }

    private JSONObject initData(long total, long pages, long pageSize) {
        JSONObject data = new JSONObject();
        data.put("sessionId", "paged-session-1");
        data.put("total", total);
        data.put("pages", pages);
        data.put("pageSize", pageSize);
        data.put("model", new JSONObject());
        data.put("type", new JSONObject());
        data.put("policy", "policy-1");
        data.put("isLatestPolicy", true);
        return data;
    }

    private JSONObject pageData(long current, JSONArray details) {
        JSONObject data = new JSONObject();
        data.put("sessionId", "paged-session-1");
        data.put("current", current);
        data.put("detailList", details);
        return data;
    }

    private JSONArray details(String... ids) {
        JSONArray details = new JSONArray();
        for (String id : ids) {
            JSONObject item = new JSONObject();
            item.put("planMajorDataId", id);
            details.add(item);
        }
        return details;
    }

    private boolean isPage(ExpertAIProgramPageReq req, Long current) {
        return req != null && current.equals(req.getCurrent());
    }
}
