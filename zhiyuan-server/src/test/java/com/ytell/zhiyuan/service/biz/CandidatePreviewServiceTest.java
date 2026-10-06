package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePreviewReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePreviewRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 候选预览（只读纵切）的四条合同：**页上限、只读不落盘、缺来源不 500、字段能进工作集**。
 *
 * <p>为什么要单测这几条而不是只靠真栈：真栈能证明"这一次没写"，但边界（25 条只回 20、
 * 第 2 页、FINISHED 会话连推荐都不该调）要在受控输入下才看得清。</p>
 */
public class CandidatePreviewServiceTest {

    private final List<String> recommendCalls = new ArrayList<>();
    private boolean recommendFails = false;

    private CandidatePreviewService buildService(ChatSession session, CandidatePoolStateDTO poolState) {
        CandidatePreviewService service = new CandidatePreviewService();
        ReflectionTestUtils.setField(service, "volunteerBizService", new VolunteerBizService() {
            @Override
            public VolunteerRecommendListResponse recommendVolunteerList(Long tenantId, Long chatSessionId,
                                                                         boolean split, boolean saveToFile) {
                recommendCalls.add(tenantId + ":" + chatSessionId + ":saveToFile=" + saveToFile);
                if (recommendFails) {
                    throw new BusinessException(110, "下载志愿数据文件失败");
                }
                return new VolunteerRecommendListResponse();
            }
        });
        ReflectionTestUtils.setField(service, "planningStateService", new PlanningStateService() {
            @Override
            PlanningStateDTO loadPlanningStateReadOnly(Long chatSessionId) {
                PlanningStateDTO state = new PlanningStateDTO();
                state.setVersion(7);
                state.getDataFreshnessState().setDataVersion("dv-1");
                return state;
            }

            @Override
            CandidatePoolStateDTO buildCandidatePoolStateFromResponse(Long chatSessionId, PlanningStateDTO state,
                                                                      VolunteerRecommendListResponse response) {
                return poolState;
            }
        });
        ReflectionTestUtils.setField(service, "volunteerDataProvider", new VolunteerDataProvider() {
            @Override
            public ChatSession getChatSession(Long chatSessionId) {
                return session;
            }
        });
        return service;
    }

    private ChatSession goingSession() {
        ChatSession session = new ChatSession();
        session.setSessionStatus(SessionStatus.GOING);
        return session;
    }

    private CandidatePoolStateDTO poolOf(CandidateItemDTO... items) {
        CandidatePoolStateDTO poolState = new CandidatePoolStateDTO();
        poolState.setItems(Lists.newArrayList(items));
        return poolState;
    }

    private CandidateItemDTO candidate(String volunteerId, String tier, double finalScore) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setFinalScore(finalScore);
        item.setSchoolId("s-" + volunteerId);
        item.setSchoolName("学校" + volunteerId);
        item.setMajorName("专业" + volunteerId);
        item.setRankInTier(1);
        item.setPlanNum(2);
        item.setTuitionPerYear(5000);
        item.setMustSubjects(Lists.newArrayList("物理"));
        item.setRiskFlags(Lists.newArrayList("risk"));
        item.setReasonCodes(Lists.newArrayList("reason"));
        return item;
    }

    private CandidateItemDTO[] candidates(int count) {
        CandidateItemDTO[] items = new CandidateItemDTO[count];
        for (int index = 0; index < count; index++) {
            items[index] = candidate("v" + index, index % 2 == 0 ? "冲" : "稳", 90 - index);
        }
        return items;
    }

    @Test
    void previewCapsAtTwentyAndKeepsFullTotalOnServer() {
        CandidatePreviewService service = buildService(goingSession(), poolOf(candidates(25)));
        CandidatePreviewReq req = new CandidatePreviewReq();
        req.setPageSize(100);

        CandidatePreviewRes res = service.preview(1L, 900047L, req);

        assertEquals(20, res.getItems().size(), "预览硬上限 20 条");
        assertEquals(20, res.getPageSize());
        assertEquals(25, res.getTotal(), "total 是全量条数，不是这一页");
        assertEquals(7, res.getProfileVersion());
        assertEquals("dv-1", res.getDataVersion());
        assertEquals(1, recommendCalls.size());
        assertTrue(recommendCalls.get(0).endsWith("saveToFile=false"), "只读路径不允许落 OSS");
        CandidatePreviewRes.Item first = res.getItems().get(0);
        assertEquals("v0", first.getEntityId(), "entityId 是工作集记忆的键");
        assertEquals("v0", first.getVolunteerId());
        assertEquals("冲", first.getTier());
        assertNotNull(first.getFinalScore());
        assertNotNull(first.getSchoolName());
    }

    @Test
    void previewSecondPageReturnsRemainder() {
        CandidatePreviewService service = buildService(goingSession(), poolOf(candidates(25)));
        CandidatePreviewReq req = new CandidatePreviewReq();
        req.setPage(2);

        CandidatePreviewRes res = service.preview(1L, 900047L, req);

        assertEquals(5, res.getItems().size());
        assertEquals(25, res.getTotal());
        assertEquals(2, res.getPage());
    }

    @Test
    void previewAppliesTierFilterAndReportsUnsupportedTagFilter() {
        CandidatePreviewService service = buildService(goingSession(), poolOf(candidates(25)));
        CandidatePreviewReq req = new CandidatePreviewReq();
        req.setPageSize(20);
        req.getFilters().setTiers(Lists.newArrayList("冲"));
        req.getFilters().setSchoolTags(Lists.newArrayList("985"));

        CandidatePreviewRes res = service.preview(1L, 900047L, req);

        assertEquals(13, res.getTotal(), "冲档 25 条里占 13 条");
        assertTrue(res.getItems().stream().allMatch(item -> "冲".equals(item.getTier())));
        assertTrue(res.getLimitations().contains("filter_unsupported:schoolTags"),
                "不支持的过滤要如实报出来，而不是静默忽略");
    }

    @Test
    void previewFinishedSessionDoesNotCallRecommendation() {
        ChatSession finished = new ChatSession();
        finished.setSessionStatus(SessionStatus.FINISHED);
        CandidatePreviewService service = buildService(finished, poolOf(candidates(3)));

        CandidatePreviewRes res = service.preview(1L, 900047L, new CandidatePreviewReq());

        assertTrue(res.getItems().isEmpty());
        assertEquals(0, res.getTotal());
        assertTrue(res.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE));
        assertTrue(recommendCalls.isEmpty(), "FINISHED 会话连推荐都不该重算");
    }

    @Test
    void previewMissingVolunteerFileReturnsLimitationInsteadOfError() {
        recommendFails = true;
        CandidatePreviewService service = buildService(goingSession(), poolOf(candidates(3)));

        CandidatePreviewRes res = service.preview(1L, 900047L, new CandidatePreviewReq());

        assertTrue(res.getItems().isEmpty());
        assertEquals(0, res.getTotal());
        assertTrue(res.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE));
    }

    @Test
    void previewEmptyPoolCarriesSourceUnavailableLimitation() {
        CandidatePreviewService service = buildService(goingSession(), poolOf());

        CandidatePreviewRes res = service.preview(1L, 900047L, new CandidatePreviewReq());

        assertTrue(res.getItems().isEmpty());
        assertFalse(res.getLimitations().isEmpty());
        assertTrue(res.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE));
    }
}
