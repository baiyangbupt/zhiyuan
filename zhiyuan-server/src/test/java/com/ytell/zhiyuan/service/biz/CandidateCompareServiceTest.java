package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.CandidateCompareReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateComparisonDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ComparisonCellDTO;
import com.ytell.zhiyuan.model.dto.planning.ComparisonEntityDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 按 ID 比较（只读纵切）的四条合同：**真实载入、找不到如实说、口径不齐整列不可比、只读**。
 *
 * <p>"仅构造数据"的解药就是这份测试：entityId 只给 ID，值必须从候选池行载入——
 * 断言断的是**载入结果**（cell 的值与 source 指向候选池），不是调用方传了什么。</p>
 */
public class CandidateCompareServiceTest {

    private final List<String> recommendCalls = new ArrayList<>();
    private VolunteerRecommendListResponse recommendResponse;
    private boolean recommendFails = false;
    private CandidatePoolStateDTO poolState;
    private ChatSession session;

    private CandidateCompareService buildService() {
        CandidatePreviewService previewService = new CandidatePreviewService();
        ReflectionTestUtils.setField(previewService, "volunteerBizService", new VolunteerBizService() {
            @Override
            public VolunteerRecommendListResponse recommendVolunteerList(Long tenantId, Long chatSessionId,
                                                                         boolean split, boolean saveToFile) {
                recommendCalls.add(tenantId + ":" + chatSessionId + ":saveToFile=" + saveToFile);
                if (recommendFails) {
                    throw new BusinessException(110, "下载志愿数据文件失败");
                }
                return recommendResponse;
            }
        });
        ReflectionTestUtils.setField(previewService, "planningStateService", new PlanningStateService() {
            @Override
            PlanningStateDTO loadPlanningStateReadOnly(Long chatSessionId) {
                PlanningStateDTO state = new PlanningStateDTO();
                state.setVersion(7);
                return state;
            }

            @Override
            CandidatePoolStateDTO buildCandidatePoolStateFromResponse(Long chatSessionId, PlanningStateDTO state,
                                                                      VolunteerRecommendListResponse response) {
                return poolState;
            }
        });
        ReflectionTestUtils.setField(previewService, "volunteerDataProvider", new VolunteerDataProvider() {
            @Override
            public ChatSession getChatSession(Long chatSessionId) {
                return session;
            }
        });

        CandidateCompareService service = new CandidateCompareService();
        ReflectionTestUtils.setField(service, "candidatePreviewService", previewService);
        ReflectionTestUtils.setField(service, "candidateComparisonService", new CandidateComparisonService());
        return service;
    }

    private ChatSession goingSession() {
        ChatSession chatSession = new ChatSession();
        chatSession.setSessionStatus(SessionStatus.GOING);
        return chatSession;
    }

    /** 会话口径：年份/省份/批次/填报模式四项都由这里提供（缺项即缺口径）。 */
    private VolunteerRecommendListResponse responseWithScope(Integer examYear, String provinceCode, String batchCode) {
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        CreateSessionReq detail = new CreateSessionReq();
        detail.setExamYear(examYear);
        if (provinceCode != null) {
            CreateSessionReq.Province province = new CreateSessionReq.Province();
            province.setCode(provinceCode);
            detail.setProvince(province);
        }
        if (batchCode != null) {
            CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
            batch.setCode(batchCode);
            detail.setBatch(batch);
        }
        detail.setVolunteerModel(VolunteerModel.major);
        response.setUserScoreDetail(detail);
        return response;
    }

    private CandidateItemDTO candidate(String volunteerId) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId(volunteerId);
        item.setSchoolId("s-" + volunteerId);
        item.setDisplaySchoolName("学校" + volunteerId);
        item.setMajorId("m-" + volunteerId);
        item.setMajorName("专业" + volunteerId);
        item.setCityName("杭州");
        item.setFinalScore(88.5);
        item.setAdmissionRatio(45.0);
        item.setSchoolEnrollRatio(72.0);
        item.setPlanNum(20);
        item.setTuitionPerYear(6000);
        return item;
    }

    private CandidatePoolStateDTO poolOf(CandidateItemDTO... items) {
        CandidatePoolStateDTO state = new CandidatePoolStateDTO();
        state.setItems(Lists.newArrayList(items));
        return state;
    }

    private CandidateCompareReq request(String... entityIds) {
        CandidateCompareReq req = new CandidateCompareReq();
        req.setChatSessionId(900047L);
        req.setEntityIds(Lists.newArrayList(entityIds));
        return req;
    }

    private ComparisonCellDTO cellFor(CandidateComparisonDTO result, String entityId, String dimension) {
        for (ComparisonCellDTO cell : result.getCells()) {
            if (entityId.equals(cell.getEntityId()) && dimension.equals(cell.getDimension())) {
                return cell;
            }
        }
        return null;
    }

    @Test
    void compareLoadsRealCandidateRowsAndFillsDimensionsFromThePool() {
        session = goingSession();
        recommendResponse = responseWithScope(2026, "330000", "17");
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        CandidateComparisonDTO result = service.compare(1L, 900047L, request("v1", "v2"));

        assertEquals(2, result.getEntities().size());
        ComparisonEntityDTO first = result.getEntities().get(0);
        assertEquals("v1", first.getEntityId());
        assertEquals("学校v1", first.getSchoolName());
        assertEquals("专业v1", first.getMajorName());
        // 口径身份取自会话：年份/省份/批次/模式/率单位五项齐。
        assertEquals(2026, first.getAdmissionYear());
        assertEquals("330000", first.getAreaId());
        assertEquals("17", first.getBatch());
        assertEquals("major", first.getAdmissionMode());
        assertEquals("percent", first.getRateUnit());
        // 值是候选池行里**真实的那份**，不是调用方传的。
        assertEquals(88.5, first.getFinalScore());
        assertEquals(45.0, first.getAdmissionRatio());
        assertEquals(20, first.getPlanNum());
        assertEquals(6000, first.getTuitionPerYear());
        assertEquals(72.0, first.getSchoolEnrollRatio());

        assertTrue(result.getUnavailableDimensions().isEmpty(), "同口径下六列都能比");
        ComparisonCellDTO scoreCell = cellFor(result, "v1", "finalScore");
        assertNotNull(scoreCell);
        assertEquals(88.5, scoreCell.getValue());
        assertEquals("score", scoreCell.getUnit());
        // source 指向候选池：值是从这里载入的，就得在这里能核对。
        assertEquals("candidatePool.finalScore", scoreCell.getSource());
        assertEquals("percent", cellFor(result, "v1", "admissionRatio").getUnit());

        assertEquals(1, recommendCalls.size());
        assertTrue(recommendCalls.get(0).endsWith("saveToFile=false"), "比较与预览同一只读载入路径");
    }

    @Test
    void unknownIdIsReportedInLimitationsInsteadOfSilentlyDropped() {
        session = goingSession();
        recommendResponse = responseWithScope(2026, "330000", "17");
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        CandidateComparisonDTO result = service.compare(1L, 900047L, request("v1", "v2", "v9"));

        assertTrue(result.getLimitations().contains(CandidateCompareService.LIMITATION_ENTITY_NOT_FOUND_PREFIX + "v9"),
                "找不到的 ID 要如实列出——静默丢一个，读者会以为表里就是他要比的那几个");
        assertEquals(2, result.getEntities().size());
        assertNotNull(cellFor(result, "v2", "finalScore"));
    }

    @Test
    void fewerThanTwoResolvedIdsCannotBeCompared() {
        session = goingSession();
        recommendResponse = responseWithScope(2026, "330000", "17");
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        CandidateComparisonDTO result = service.compare(1L, 900047L, request("v1", "v9"));

        assertEquals(1, result.getEntities().size());
        assertTrue(result.getCells().isEmpty(), "不足两个实体不硬凑一张表");
        assertTrue(result.getLimitations().contains(CandidateCompareService.LIMITATION_ENTITY_COUNT_INVALID));
        assertTrue(result.getLimitations().contains(CandidateCompareService.LIMITATION_ENTITY_NOT_FOUND_PREFIX + "v9"));
    }

    @Test
    void aMissingScopeFieldMarksNumericColumnsUnavailable() {
        session = goingSession();
        // 会话里没有批次：不知道口径是否相同，就不许当相同。
        recommendResponse = responseWithScope(2026, "330000", null);
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        CandidateComparisonDTO result = service.compare(1L, 900047L, request("v1", "v2"));

        assertTrue(result.getUnavailableDimensions().contains("finalScore"));
        assertTrue(result.getUnavailableDimensions().contains("planNum"));
        assertTrue(result.getUnavailableDimensions().contains("admissionRatio"));
        assertTrue(result.getLimitations().contains("comparison_scope_mismatch"));
        // 名称类维度不受口径影响，仍然可用。
        assertNotNull(cellFor(result, "v1", "cityName"));
        assertEquals("杭州", cellFor(result, "v1", "cityName").getValue());
        // 整列不可比时值为 null：不是 0，也不是那一行里"看起来"的那个数。
        assertNull(cellFor(result, "v1", "finalScore").getValue());
        assertEquals("scope_mismatch", cellFor(result, "v1", "finalScore").getUnavailableReason());
    }

    @Test
    void candidateSourceUnavailableReturnsLimitationsInsteadOfError() {
        session = goingSession();
        recommendFails = true;
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        CandidateComparisonDTO result = service.compare(1L, 900047L, request("v1", "v2"));

        assertTrue(result.getEntities().isEmpty());
        assertTrue(result.getCells().isEmpty());
        assertTrue(result.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE));
    }

    @Test
    void finishedSessionDoesNotRecalculateCandidates() {
        ChatSession finished = new ChatSession();
        finished.setSessionStatus(SessionStatus.FINISHED);
        session = finished;
        recommendResponse = responseWithScope(2026, "330000", "17");
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        CandidateComparisonDTO result = service.compare(1L, 900047L, request("v1", "v2"));

        assertTrue(result.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE));
        assertTrue(recommendCalls.isEmpty(), "已提交会话连推荐都不该重算");
    }

    @Test
    void entityCountAndDimensionsAreBounded() {
        session = goingSession();
        recommendResponse = responseWithScope(2026, "330000", "17");
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.compare(1L, 900047L, request("v1"))).getStatus());
        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.compare(1L, 900047L, request("v1", "v2", "v3", "v4", "v5", "v6"))).getStatus());
        CandidateCompareReq badDimension = request("v1", "v2");
        badDimension.setDimensions(Lists.newArrayList("secretField"));
        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.compare(1L, 900047L, badDimension)).getStatus());
    }

    @Test
    void blankEntityIdsAreReportedInsteadOfSilentlyDropped() {
        session = goingSession();
        recommendResponse = responseWithScope(2026, "330000", "17");
        poolState = poolOf(candidate("v1"), candidate("v2"));
        CandidateCompareService service = buildService();

        // 三个 ID 里有一个是空白：允许丢，但要在 limitations 里说一声。
        CandidateComparisonDTO result = service.compare(1L, 900047L, request("v1", "v2", "  "));

        assertEquals(2, result.getEntities().size());
        assertTrue(result.getLimitations().contains(CandidateCompareService.LIMITATION_BLANK_ENTITY_ID));
    }
}
