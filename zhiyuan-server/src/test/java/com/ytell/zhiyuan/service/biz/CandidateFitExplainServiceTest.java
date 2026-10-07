package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.CandidateFitExplainReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateFitExplainRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 适配性解释（只读纵切）的五条合同：**按 ID 载入真实行、匹配点带来源、缺字段不猜、
 * 概率恒不可用、只读（版本不动）**。
 */
public class CandidateFitExplainServiceTest {

    private final List<String> recommendCalls = new ArrayList<>();
    private boolean recommendFails = false;
    private VolunteerRecommendListResponse recommendResponse;
    private CandidatePoolStateDTO poolState;
    private ChatSession session;
    private PlanningStateDTO planningState = new PlanningStateDTO();

    private CandidateFitExplainService buildService() {
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
                return planningState;
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

        CandidateFitExplainService service = new CandidateFitExplainService();
        ReflectionTestUtils.setField(service, "candidatePreviewService", previewService);
        return service;
    }

    private ChatSession goingSession() {
        ChatSession chatSession = new ChatSession();
        chatSession.setSessionStatus(SessionStatus.GOING);
        return chatSession;
    }

    private CandidateItemDTO candidate(String volunteerId) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier("冲");
        item.setRankInTier(3);
        item.setSchoolName("浙江大学");
        item.setDisplaySchoolName("浙江大学");
        item.setProvinceName("浙江");
        item.setCityName("杭州");
        item.setMajorId("774");
        item.setMajorName("计算机科学与技术");
        item.setTuitionPerYear(6000);
        item.setMustSubjects(Lists.newArrayList("物和化"));
        item.setRiskFlags(Lists.newArrayList("保研率一般"));
        item.setReasonCodes(Lists.newArrayList("城市发展好"));
        return item;
    }

    /** 档案：选科物理/化学/生物 + 学费区间 [3000, 9000]。 */
    private VolunteerRecommendListResponse responseWithProfile() {
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        CreateSessionReq detail = new CreateSessionReq();
        detail.setSubjectList(Lists.newArrayList(
                new CreateSessionReq.SubjectItem(1, "WL", "01", "物理"),
                new CreateSessionReq.SubjectItem(0, "WL", "05", "化学"),
                new CreateSessionReq.SubjectItem(0, "WL", "06", "生物")));
        detail.setTuitionRange(new CreateSessionReq.TuitionRange(3000, 9000));
        response.setUserScoreDetail(detail);
        return response;
    }

    private CandidatePoolStateDTO poolOf(CandidateItemDTO... items) {
        CandidatePoolStateDTO state = new CandidatePoolStateDTO();
        state.setItems(Lists.newArrayList(items));
        return state;
    }

    private PlanningStateDTO stateWithVersion() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        return state;
    }

    private CandidateFitExplainReq request(String entityId) {
        CandidateFitExplainReq req = new CandidateFitExplainReq();
        req.setChatSessionId(900047L);
        req.setEntityId(entityId);
        return req;
    }

    private CandidateFitExplainRes.Dimension dimension(CandidateFitExplainRes res, String name) {
        for (CandidateFitExplainRes.Dimension dimension : res.getFitDimensions()) {
            if (name.equals(dimension.getDimension())) {
                return dimension;
            }
        }
        return null;
    }

    private Set<String> matchedSources(CandidateFitExplainRes res) {
        Set<String> sources = new HashSet<>();
        for (CandidateFitExplainRes.MatchedPoint point : res.getMatched()) {
            sources.add(point.getSource());
        }
        return sources;
    }

    @Test
    void explainLoadsRealRowAndEveryMatchedPointCarriesItsSource() {
        session = goingSession();
        recommendResponse = responseWithProfile();
        poolState = poolOf(candidate("v1"));
        planningState = stateWithVersion();
        planningState.getConstraintState().getSoftPreferences().getPreferRegions().add("长三角");
        planningState.getProfileState().getExplicitProfile().getPositiveRegions().add("浙江");
        planningState.getProfileState().getExplicitProfile().getPositiveMajors().add("计算机");
        planningState.getProfileState().getExplicitProfile().getPositiveSchools().add("浙江大学");
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v1"));

        assertTrue(res.isFound());
        assertEquals("v1", res.getEntityId());
        assertEquals("浙江大学", res.getSchoolName());
        assertEquals("计算机科学与技术", res.getMajorName());
        assertEquals("冲", res.getTier());
        assertEquals(7, res.getProfileVersion());

        // 五个维度全部评出状态。
        assertEquals(CandidateFitExplainService.STATUS_MATCHED,
                dimension(res, CandidateFitExplainService.DIM_SUBJECT_REQUIREMENT).getStatus());
        assertEquals(CandidateFitExplainService.STATUS_MATCHED,
                dimension(res, CandidateFitExplainService.DIM_REGION_PREFERENCE).getStatus());
        assertEquals(CandidateFitExplainService.STATUS_MATCHED,
                dimension(res, CandidateFitExplainService.DIM_MAJOR_INTENT).getStatus());
        assertEquals(CandidateFitExplainService.STATUS_MATCHED,
                dimension(res, CandidateFitExplainService.DIM_SCHOOL_INTENT).getStatus());
        assertEquals(CandidateFitExplainService.STATUS_MATCHED,
                dimension(res, CandidateFitExplainService.DIM_TUITION_RANGE).getStatus());

        // 匹配点逐条带来源：没有来源的匹配点不许存在。
        assertEquals(6, res.getMatched().size(), "选科/地域×2/专业/院校/学费");
        Set<String> sources = matchedSources(res);
        for (CandidateFitExplainRes.MatchedPoint point : res.getMatched()) {
            assertTrue(point.getSource() != null && !point.getSource().trim().isEmpty(),
                    "每条匹配点都必须带 source");
            assertTrue(point.getStatement() != null && !point.getStatement().trim().isEmpty());
        }
        assertTrue(sources.contains(CandidateFitExplainService.SOURCE_SUBJECT));
        assertTrue(sources.contains(CandidateFitExplainService.SOURCE_TUITION));
        assertTrue(sources.contains(CandidateFitExplainService.SOURCE_SOFT_PREFER_REGIONS));
        assertTrue(sources.contains(CandidateFitExplainService.SOURCE_PROFILE_POSITIVE_REGIONS));
        assertTrue(sources.contains(CandidateFitExplainService.SOURCE_PROFILE_POSITIVE_MAJORS));
        assertTrue(sources.contains(CandidateFitExplainService.SOURCE_PROFILE_POSITIVE_SCHOOLS));

        // 风险：候选行标志逐字透传 + 事实陈述。
        assertEquals(Lists.newArrayList("保研率一般"), res.getRisks().getFlags());
        assertEquals(Lists.newArrayList("城市发展好"), res.getRisks().getReasonCodes());
        assertEquals(2, res.getRisks().getFacts().size());
        assertEquals("tier", res.getRisks().getFacts().get(0).getField());
        assertEquals("冲", res.getRisks().getFacts().get(0).getValue());
        assertEquals("rankInTier", res.getRisks().getFacts().get(1).getField());
        assertEquals("3", res.getRisks().getFacts().get(1).getValue());

        // 概率恒不可用：本服务没有任何权威概率来源。
        assertEquals("unavailable", res.getProbability().getStatus());
        assertEquals("no_authoritative_probability_source", res.getProbability().getReason());

        // 只读：载入走 saveToFile=false，版本自始至终没被动过。
        assertEquals(1, recommendCalls.size());
        assertTrue(recommendCalls.get(0).endsWith("saveToFile=false"));
        assertEquals(7, planningState.getVersion());
    }

    @Test
    void unmetSubjectRequirementIsConflictAndMissingCandidateFieldIsUnknown() {
        session = goingSession();
        recommendResponse = responseWithProfile();
        CandidateItemDTO item = candidate("v1");
        item.setTuitionPerYear(null);
        poolState = poolOf(item);
        planningState = stateWithVersion();
        // 档案只有物理：满足不了"物和化"。
        recommendResponse.getUserScoreDetail().setSubjectList(Lists.newArrayList(
                new CreateSessionReq.SubjectItem(1, "WL", "01", "物理")));
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v1"));

        CandidateFitExplainRes.Dimension subject =
                dimension(res, CandidateFitExplainService.DIM_SUBJECT_REQUIREMENT);
        assertEquals(CandidateFitExplainService.STATUS_CONFLICT, subject.getStatus());
        assertTrue(subject.getDetail().contains("化学"), "缺哪一科要说清楚");
        CandidateFitExplainRes.Dimension tuition =
                dimension(res, CandidateFitExplainService.DIM_TUITION_RANGE);
        assertEquals(CandidateFitExplainService.STATUS_UNKNOWN, tuition.getStatus());
        assertTrue(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_CANDIDATE_FIELD_MISSING_PREFIX + "tuitionPerYear"));
        for (CandidateFitExplainRes.MatchedPoint point : res.getMatched()) {
            assertFalse(CandidateFitExplainService.SOURCE_SUBJECT.equals(point.getSource()));
            assertFalse(CandidateFitExplainService.SOURCE_TUITION.equals(point.getSource()));
        }
        assertEquals("unavailable", res.getProbability().getStatus());
    }

    @Test
    void missingProfileFieldMakesDimensionUnknownAndHardConflictIsAttributedHonestly() {
        session = goingSession();
        recommendResponse = responseWithProfile();
        recommendResponse.getUserScoreDetail().setSubjectList(Lists.newArrayList());
        poolState = poolOf(candidate("v1"));
        planningState = stateWithVersion();
        // 带标签的硬性院校要求（"性质:985"）本切片不逐条求值：如实标注，且聚合判定
        // 说"不满足"时维度没有冲突可归因——解释不完整也是事实。
        planningState.getConstraintState().getHardConstraints().getMustIncludeSchools().add("性质:985");
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v1"));

        CandidateFitExplainRes.Dimension subject =
                dimension(res, CandidateFitExplainService.DIM_SUBJECT_REQUIREMENT);
        assertEquals(CandidateFitExplainService.STATUS_UNKNOWN, subject.getStatus());
        assertTrue(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_PROFILE_FIELD_MISSING_PREFIX + "subjectList"));
        assertTrue(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_SCOPE_LABEL_NOT_EVALUATED_PREFIX + "性质:985"));
        assertTrue(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_HARD_CONSTRAINTS_CONFLICT_UNATTRIBUTED));
        assertEquals(CandidateFitExplainService.STATUS_NO_MATCH,
                dimension(res, CandidateFitExplainService.DIM_SCHOOL_INTENT).getStatus());
    }

    @Test
    void excludeRulesAreAttributedAsConflictWithoutUnattributedLimitation() {
        session = goingSession();
        recommendResponse = responseWithProfile();
        poolState = poolOf(candidate("v1"));
        planningState = stateWithVersion();
        planningState.getConstraintState().getHardConstraints().getMustExcludeRegions().add("浙江");
        planningState.getConstraintState().getHardConstraints().getMustExcludeMajorIds().add("774");
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v1"));

        assertEquals(CandidateFitExplainService.STATUS_CONFLICT,
                dimension(res, CandidateFitExplainService.DIM_REGION_PREFERENCE).getStatus());
        assertEquals(CandidateFitExplainService.STATUS_CONFLICT,
                dimension(res, CandidateFitExplainService.DIM_MAJOR_INTENT).getStatus());
        assertFalse(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_HARD_CONSTRAINTS_CONFLICT_UNATTRIBUTED),
                "冲突已被逐维度归因，不该再说解释不了");
    }

    @Test
    void unparsableSubjectRequirementIsReportedNotGuessed() {
        session = goingSession();
        recommendResponse = responseWithProfile();
        CandidateItemDTO item = candidate("v1");
        item.setMustSubjects(Lists.newArrayList("物理或化学"));
        poolState = poolOf(item);
        planningState = stateWithVersion();
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v1"));

        CandidateFitExplainRes.Dimension subject =
                dimension(res, CandidateFitExplainService.DIM_SUBJECT_REQUIREMENT);
        assertEquals(CandidateFitExplainService.STATUS_UNKNOWN, subject.getStatus());
        assertTrue(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_SUBJECT_REQUIREMENT_UNPARSED_PREFIX + "物理或化学"));
    }

    @Test
    void unknownEntityIdReturnsHonestEmptyResultWithLimitation() {
        session = goingSession();
        recommendResponse = responseWithProfile();
        poolState = poolOf(candidate("v1"));
        planningState = stateWithVersion();
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v9"));

        assertFalse(res.isFound());
        assertEquals("v9", res.getEntityId());
        assertEquals(7, res.getProfileVersion());
        assertTrue(res.getMatched().isEmpty());
        assertTrue(res.getFitDimensions().isEmpty());
        assertTrue(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_ENTITY_NOT_FOUND_PREFIX + "v9"));
        assertEquals("unavailable", res.getProbability().getStatus());
    }

    @Test
    void blankEntityIdIsRejected() {
        session = goingSession();
        CandidateFitExplainService service = buildService();

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.explain(1L, 900047L, request("  ")));
        assertEquals(400, error.getStatus());
        assertTrue(recommendCalls.isEmpty(), "参数都没给全，候选池都不该载入");
    }

    @Test
    void sourceUnavailableReturnsLimitationsInsteadOfError() {
        session = goingSession();
        recommendFails = true;
        poolState = poolOf(candidate("v1"));
        planningState = stateWithVersion();
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v1"));

        assertFalse(res.isFound());
        assertTrue(res.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE));
        assertFalse(res.getLimitations().contains(
                CandidateFitExplainService.LIMITATION_ENTITY_NOT_FOUND_PREFIX + "v1"),
                "来源都没有就不该说'找不到这个 ID'");
    }

    @Test
    void finishedSessionDoesNotRecalculateCandidates() {
        ChatSession finished = new ChatSession();
        finished.setSessionStatus(SessionStatus.FINISHED);
        session = finished;
        recommendResponse = responseWithProfile();
        poolState = poolOf(candidate("v1"));
        planningState = stateWithVersion();
        CandidateFitExplainService service = buildService();

        CandidateFitExplainRes res = service.explain(1L, 900047L, request("v1"));

        assertFalse(res.isFound());
        assertTrue(res.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE));
        assertTrue(recommendCalls.isEmpty(), "已提交会话连推荐都不该重算");
    }

    @Test
    void subjectParsingMirrorsFilterChainAbbreviations() {
        assertEquals(Lists.newArrayList("物理", "化学"),
                CandidateFitExplainService.parseSelectInfo("物和化"));
        assertEquals(Lists.newArrayList("物理"), CandidateFitExplainService.parseSelectInfo("物理"));
        assertEquals(Lists.newArrayList("历史"), CandidateFitExplainService.parseSelectInfo("史"));
        assertTrue(CandidateFitExplainService.parseSelectInfo("不限").isEmpty());
    }
}
