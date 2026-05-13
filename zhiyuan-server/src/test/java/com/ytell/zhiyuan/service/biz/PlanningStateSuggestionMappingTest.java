package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.AddSuggestionDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.DraftSelectReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentAnalyzeReq;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReorderSuggestionDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplaceSuggestionDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.when;

public class PlanningStateSuggestionMappingTest {

    private PlanningStateService planningStateService;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private VolunteerBizService volunteerBizService;

    @BeforeEach
    void setUp() {
        planningStateService = new PlanningStateService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        volunteerBizService = Mockito.mock(VolunteerBizService.class);
        ReflectionTestUtils.setField(planningStateService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(planningStateService, "volunteerBizService", volunteerBizService);
        ReflectionTestUtils.setField(planningStateService, "volunteerIntervalService", new VolunteerIntervalService());
    }

    @Test
    void shouldAnalyzePlanAdjustmentWithLegacyReviewRules() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(5, 1, 1, 3);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "天津", 2, buildMajorWithRatio("m2", "专业B", "35"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "河北", 3, buildMajorWithRatio("m3", "专业C", "80")),
                buildSchool("ps4", "s4", "学校D", "河南", 4, buildMajorWithRatio("m4", "专业D", "58"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("draft");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        assertTrue(adjustmentState.getSuggestions().getAddSuggestions().stream()
                .anyMatch(item -> "count_validation".equals(item.getRuleCode()) && !item.getCandidateVolunteerIds().isEmpty()));
        assertTrue(adjustmentState.getSuggestions().getAddSuggestions().stream()
                .anyMatch(item -> "probability_gap".equals(item.getRuleCode()) && !item.getCandidateSummaries().isEmpty()));
        assertTrue(adjustmentState.getSuggestions().getReplaceSuggestions().stream()
                .anyMatch(item -> "probability_gap".equals(item.getRuleCode())
                        && !item.getRemoveVolunteerIds().isEmpty()
                        && !item.getCandidateVolunteerIds().isEmpty()
                        && !item.getReplacementPairs().isEmpty()));
    }

    @Test
    void shouldAnalyzePlanAdjustmentProbabilityInversionWithReorderSuggestion() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "35"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "80"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        com.ytell.zhiyuan.model.dto.planning.OrderedMoveReq moveReq = new com.ytell.zhiyuan.model.dto.planning.OrderedMoveReq();
        moveReq.setVolunteerId("ps3_m3");
        moveReq.setTargetPosition(2);
        planningStateService.moveOrderedItem(1L, moveReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        assertTrue(adjustmentState.getSuggestions().getReorderSuggestions().stream()
                .anyMatch(item -> "probability_inversion".equals(item.getRuleCode())
                        && item.getOrderedVolunteerIds().size() == 3
                        && "ps2_m2".equals(item.getOrderedVolunteerIds().get(1))));
    }

    @Test
    void shouldAnalyzePlanAdjustmentProbabilityInversionWithReplaceSuggestion() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 3, 0));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "北京", 1, buildMajorWithRatio("m2", "专业B", "40")),
                buildSchool("ps3", "s3", "学校C", "北京", 2, buildMajorWithRatio("m3", "专业C", "54")),
                buildSchool("ps4", "s4", "学校D", "北京", 3, buildMajorWithRatio("m4", "专业D", "36"))));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        com.ytell.zhiyuan.model.dto.planning.OrderedMoveReq moveReq = new com.ytell.zhiyuan.model.dto.planning.OrderedMoveReq();
        moveReq.setVolunteerId("ps3_m3");
        moveReq.setTargetPosition(2);
        planningStateService.moveOrderedItem(1L, moveReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        assertTrue(adjustmentState.getSuggestions().getReplaceSuggestions().stream()
                .anyMatch(item -> "probability_inversion".equals(item.getRuleCode())
                        && item.getRemoveVolunteerIds().contains("ps3_m3")
                        && item.getCandidateVolunteerIds().contains("ps4_m4")
                        && item.getReplacementPairs().stream().anyMatch(pair ->
                        "ps3_m3".equals(pair.getFromVolunteerId()) && "ps4_m4".equals(pair.getToVolunteerId()))));
    }

    @Test
    void shouldKeepUnitFieldsEmptyInMajorPlanAdjustmentSuggestions() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(5, 3, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18")),
                buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "26")),
                buildSchool("ps4", "s4", "学校D", "北京", 4, buildMajorWithRatio("m4", "专业D", "30"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "学校E", "北京", 1, buildMajorWithRatio("m5", "专业E", "46"))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps6", "s6", "学校F", "北京", 1, buildMajorWithRatio("m6", "专业F", "78")),
                buildSchool("ps7", "s7", "学校G", "北京", 2, buildMajorWithRatio("m7", "专业G", "82"))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4", "ps5_m5"));
        planningStateService.selectDraftItems(1L, selectReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("draft");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        AddSuggestionDTO addSuggestion = adjustmentState.getSuggestions().getAddSuggestions().stream()
                .filter(item -> "ratio_distribution".equals(item.getRuleCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(addSuggestion);
        assertTrue(addSuggestion.getAffectedUnitIds().isEmpty());
        assertTrue(addSuggestion.getCandidateUnitIds().isEmpty());

        ReplaceSuggestionDTO replaceSuggestion = adjustmentState.getSuggestions().getReplaceSuggestions().stream()
                .filter(item -> "ratio_distribution".equals(item.getRuleCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(replaceSuggestion);
        assertTrue(replaceSuggestion.getAffectedUnitIds().isEmpty());
        assertTrue(replaceSuggestion.getRemoveUnitIds().isEmpty());
        assertTrue(replaceSuggestion.getCandidateUnitIds().isEmpty());
        assertTrue(replaceSuggestion.getReplacementPairs().stream().allMatch(pair ->
                pair.getFromUnitId() == null && pair.getToUnitId() == null));
    }

    @Test
    void shouldEmitUnitFieldsInMajorGroupAddSuggestion() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(3, 1, 1, 1);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(3);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1, buildMajorWithRatio("m1", "专业A1", "40"));
        sprintGroup.setEnroll_ratio("20");
        sprintGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m1", "专业A1", "40"), buildMajorWithRatio("m2", "专业A2", "32")));
        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1, buildMajorWithRatio("m3", "专业B1", "60"));
        safeGroup.setEnroll_ratio("45");
        safeGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m3", "专业B1", "60"), buildMajorWithRatio("m4", "专业B2", "50")));
        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps3", "s3", "专业组C", "河南", 1, buildMajorWithRatio("m5", "专业C1", "95"));
        protectGroup.setEnroll_ratio("80");
        protectGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m5", "专业C1", "95"), buildMajorWithRatio("m6", "专业C2", "88")));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Arrays.asList(protectGroup));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m3", "ps2_m4"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        AddSuggestionDTO addSuggestion = adjustmentState.getSuggestions().getAddSuggestions().stream()
                .filter(item -> "count_validation".equals(item.getRuleCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(addSuggestion);
        assertEquals(java.util.Arrays.asList("ps3"), addSuggestion.getCandidateUnitIds());
        assertTrue(addSuggestion.getCandidateVolunteerIds().contains("ps3_m5"));
        assertTrue(addSuggestion.getCandidateVolunteerIds().contains("ps3_m6"));
        assertTrue(addSuggestion.getCandidateSummaries().stream().allMatch(item -> "ps3".equals(item.getUnitId())));
    }

    @Test
    void shouldEmitUnitFieldsInMajorGroupReplaceSuggestion() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(3, 1, 1, 1);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(4);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1, buildMajorWithRatio("m1", "专业A1", "40"));
        sprintGroup.setEnroll_ratio("20");
        sprintGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m1", "专业A1", "40"), buildMajorWithRatio("m2", "专业A2", "35")));
        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1, buildMajorWithRatio("m3", "专业B1", "62"));
        safeGroup.setEnroll_ratio("45");
        safeGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m3", "专业B1", "62"), buildMajorWithRatio("m4", "专业B2", "56")));
        VolunteerRecommendListResponse.VolunteerSchool bridgeGroup = buildSchool("ps3", "s3", "专业组C", "天津", 1, buildMajorWithRatio("m5", "专业C1", "52"));
        bridgeGroup.setEnroll_ratio("32");
        bridgeGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m5", "专业C1", "52"), buildMajorWithRatio("m6", "专业C2", "48")));
        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps4", "s4", "专业组D", "河南", 1, buildMajorWithRatio("m7", "专业D1", "90"));
        protectGroup.setEnroll_ratio("80");
        protectGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m7", "专业D1", "90"), buildMajorWithRatio("m8", "专业D2", "84")));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Arrays.asList(bridgeGroup, protectGroup));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m3", "ps2_m4", "ps4_m7", "ps4_m8"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        ReplaceSuggestionDTO replaceSuggestion = adjustmentState.getSuggestions().getReplaceSuggestions().stream()
                .filter(item -> "probability_gap".equals(item.getRuleCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(replaceSuggestion);
        assertEquals(java.util.Arrays.asList("ps1", "ps2"), replaceSuggestion.getAffectedUnitIds());
        assertEquals(java.util.Arrays.asList("ps3"), replaceSuggestion.getCandidateUnitIds());
        assertEquals(1, replaceSuggestion.getRemoveUnitIds().size());
        assertTrue(replaceSuggestion.getReplacementPairs().stream().allMatch(pair ->
                pair.getFromUnitId() != null && "ps3".equals(pair.getToUnitId())));
    }

    @Test
    void shouldEmitUnitFieldsInMajorGroupRatioDistributionReplaceSuggestion() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(5, 3, 1, 1);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(7);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool sprintGroupA = buildSchool("ps1", "s1", "专业组A", "北京", 1, buildMajorWithRatio("m1", "专业A1", "22"));
        sprintGroupA.setEnroll_ratio("12");
        sprintGroupA.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m1", "专业A1", "22"), buildMajorWithRatio("m2", "专业A2", "18")));
        VolunteerRecommendListResponse.VolunteerSchool sprintGroupB = buildSchool("ps2", "s2", "专业组B", "北京", 2, buildMajorWithRatio("m3", "专业B1", "30"));
        sprintGroupB.setEnroll_ratio("18");
        sprintGroupB.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m3", "专业B1", "30"), buildMajorWithRatio("m4", "专业B2", "24")));
        VolunteerRecommendListResponse.VolunteerSchool sprintGroupC = buildSchool("ps3", "s3", "专业组C", "北京", 3, buildMajorWithRatio("m5", "专业C1", "38"));
        sprintGroupC.setEnroll_ratio("24");
        sprintGroupC.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m5", "专业C1", "38"), buildMajorWithRatio("m6", "专业C2", "32")));
        VolunteerRecommendListResponse.VolunteerSchool sprintGroupD = buildSchool("ps4", "s4", "专业组D", "北京", 4, buildMajorWithRatio("m7", "专业D1", "42"));
        sprintGroupD.setEnroll_ratio("28");
        sprintGroupD.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m7", "专业D1", "42"), buildMajorWithRatio("m8", "专业D2", "36")));
        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps5", "s5", "专业组E", "北京", 1, buildMajorWithRatio("m9", "专业E1", "58"));
        safeGroup.setEnroll_ratio("46");
        safeGroup.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m9", "专业E1", "58"), buildMajorWithRatio("m10", "专业E2", "50")));
        VolunteerRecommendListResponse.VolunteerSchool protectGroupA = buildSchool("ps6", "s6", "专业组F", "北京", 1, buildMajorWithRatio("m11", "专业F1", "85"));
        protectGroupA.setEnroll_ratio("78");
        protectGroupA.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m11", "专业F1", "85"), buildMajorWithRatio("m12", "专业F2", "80")));
        VolunteerRecommendListResponse.VolunteerSchool protectGroupB = buildSchool("ps7", "s7", "专业组G", "北京", 2, buildMajorWithRatio("m13", "专业G1", "88"));
        protectGroupB.setEnroll_ratio("82");
        protectGroupB.setMajors(java.util.Arrays.asList(buildMajorWithRatio("m13", "专业G1", "88"), buildMajorWithRatio("m14", "专业G2", "84")));

        response.setSprints(java.util.Arrays.asList(sprintGroupA, sprintGroupB, sprintGroupC, sprintGroupD));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Arrays.asList(protectGroupA, protectGroupB));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1","ps1_m2","ps2_m3","ps2_m4","ps3_m5","ps3_m6","ps4_m7","ps4_m8","ps5_m9","ps5_m10"));
        planningStateService.selectDraftItems(1L, selectReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("draft");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        ReplaceSuggestionDTO replaceSuggestion = adjustmentState.getSuggestions().getReplaceSuggestions().stream()
                .filter(item -> "ratio_distribution".equals(item.getRuleCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(replaceSuggestion);
        assertFalse(replaceSuggestion.getAffectedUnitIds().isEmpty());
        assertFalse(replaceSuggestion.getRemoveUnitIds().isEmpty());
        assertTrue(replaceSuggestion.getCandidateUnitIds().contains("ps6"));
        assertTrue(replaceSuggestion.getReplacementPairs().stream().anyMatch(pair ->
                pair.getFromUnitId() != null
                        && pair.getToUnitId() != null
                        && replaceSuggestion.getCandidateUnitIds().contains(pair.getToUnitId())));
    }

    @Test
    void shouldEmitUnitFieldsInMajorGroupReorderSuggestion() {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_inversion");
        check.setLevel("warn");
        check.setSummary("当前排序存在录取概率倒挂");
        check.setSuggestedAction("建议检查相邻专业组顺序，确认是否符合真实风险梯度。");
        check.setAffectedUnitIds(java.util.Arrays.asList("ps2", "ps1"));
        check.setAffectedVolunteerIds(java.util.Arrays.asList("ps2_m3", "ps1_m1"));

        OrderedItemDTO item1 = new OrderedItemDTO();
        item1.setVolunteerId("ps2_m3");
        item1.setSchoolName("专业组B");
        item1.setMajorName("专业B1");
        item1.setPosition(1);

        OrderedItemDTO item2 = new OrderedItemDTO();
        item2.setVolunteerId("ps1_m1");
        item2.setSchoolName("专业组A");
        item2.setMajorName("专业A1");
        item2.setPosition(2);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.setItems(java.util.Arrays.asList(item1, item2));
        OrderedUnitDTO unit1 = new OrderedUnitDTO();
        unit1.setUnitId("ps2");
        unit1.setSchoolName("专业组B");
        unit1.setPosition(1);
        OrderedUnitDTO unit2 = new OrderedUnitDTO();
        unit2.setUnitId("ps1");
        unit2.setSchoolName("专业组A");
        unit2.setPosition(2);
        orderedPlanState.setUnits(java.util.Arrays.asList(unit1, unit2));

        CandidateItemDTO candidate1 = new CandidateItemDTO();
        candidate1.setVolunteerId("ps1_m1");
        candidate1.setPlanSchoolDataId("ps1");
        candidate1.setSchoolName("专业组A");
        candidate1.setAdmissionRatio(20D);
        CandidateItemDTO candidate2 = new CandidateItemDTO();
        candidate2.setVolunteerId("ps2_m3");
        candidate2.setPlanSchoolDataId("ps2");
        candidate2.setSchoolName("专业组B");
        candidate2.setAdmissionRatio(45D);

        @SuppressWarnings("unchecked")
        ReorderSuggestionDTO reorderSuggestion = ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildProbabilityInversionReorderSuggestion",
                check,
                "ordered",
                orderedPlanState,
                java.util.Arrays.asList(candidate1, candidate2));
        assertNotNull(reorderSuggestion);
        assertEquals(java.util.Arrays.asList("ps2", "ps1"), reorderSuggestion.getAffectedUnitIds());
        assertEquals(java.util.Arrays.asList("ps2", "ps1"), reorderSuggestion.getOrderedUnitIds());
        assertEquals(2, reorderSuggestion.getOrderedVolunteerIds().size());
    }

    @Test
    void shouldSortOrderedPlanBySchoolRankThenAdmissionRatioAndFinalScore() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 4, 0, 0));
        response.setUserScoreDetail(buildScoreDetail());
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "20"));
        schoolA.setSchool_rank(10);
        schoolA.getAlgTagMap().put("volunteer_score", 70D);
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "10"));
        schoolB.setSchool_rank(10);
        schoolB.getAlgTagMap().put("volunteer_score", 60D);
        VolunteerRecommendListResponse.VolunteerSchool schoolC = buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "10"));
        schoolC.setSchool_rank(10);
        schoolC.getAlgTagMap().put("volunteer_score", 80D);
        VolunteerRecommendListResponse.VolunteerSchool schoolD = buildSchool("ps4", "s4", "学校D", "北京", 4, buildMajorWithRatio("m4", "专业D", "90"));
        schoolD.setSchool_rank(20);
        schoolD.getAlgTagMap().put("volunteer_score", 95D);
        response.setSprints(java.util.Arrays.asList(schoolD, schoolA, schoolB, schoolC));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq sortReq = new com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq();
        sortReq.setSortField("schoolRank");
        PlanningStateDTO state = planningStateService.sortOrderedPlan(1L, sortReq);

        assertEquals(java.util.Arrays.asList("ps3_m3", "ps2_m2", "ps1_m1", "ps4_m4"), orderedVolunteerIds(state));
    }

    @Test
    void shouldSortOrderedPlanByAdmissionRatioThenSchoolRankAndFinalScore() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 3, 0, 0));
        response.setUserScoreDetail(buildScoreDetail());
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "20"));
        schoolA.setSchool_rank(20);
        schoolA.getAlgTagMap().put("volunteer_score", 95D);
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "20"));
        schoolB.setSchool_rank(10);
        schoolB.getAlgTagMap().put("volunteer_score", 60D);
        VolunteerRecommendListResponse.VolunteerSchool schoolC = buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "30"));
        schoolC.setSchool_rank(1);
        schoolC.getAlgTagMap().put("volunteer_score", 99D);
        response.setSprints(java.util.Arrays.asList(schoolA, schoolC, schoolB));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq sortReq = new com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq();
        sortReq.setSortField("admissionRatio");
        PlanningStateDTO state = planningStateService.sortOrderedPlan(1L, sortReq);

        assertEquals(java.util.Arrays.asList("ps2_m2", "ps1_m1", "ps3_m3"), orderedVolunteerIds(state));
    }

    @Test
    void shouldSortOrderedPlanByFinalScoreThenAdmissionRatioAndSchoolRank() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 3, 0, 0));
        response.setUserScoreDetail(buildScoreDetail());
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "20"));
        schoolA.setSchool_rank(20);
        schoolA.getAlgTagMap().put("volunteer_score", 80D);
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "10"));
        schoolB.setSchool_rank(10);
        schoolB.getAlgTagMap().put("volunteer_score", 80D);
        VolunteerRecommendListResponse.VolunteerSchool schoolC = buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "5"));
        schoolC.setSchool_rank(1);
        schoolC.getAlgTagMap().put("volunteer_score", 70D);
        response.setSprints(java.util.Arrays.asList(schoolC, schoolA, schoolB));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq sortReq = new com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq();
        sortReq.setSortField("finalScore");
        PlanningStateDTO state = planningStateService.sortOrderedPlan(1L, sortReq);

        assertEquals(java.util.Arrays.asList("ps2_m2", "ps1_m1", "ps3_m3"), orderedVolunteerIds(state));
    }

    @Test
    void shouldSortLegacyOrderedPlanWithMismatchedVolunteerIds() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 3, 0, 0));
        response.setUserScoreDetail(buildScoreDetail());
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithPlanMajorDataId("101", "pm1", "专业A", "20"));
        schoolA.setSchool_rank(20);
        schoolA.getAlgTagMap().put("volunteer_score", 80D);
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithPlanMajorDataId("102", "pm2", "专业B", "20"));
        schoolB.setSchool_rank(10);
        schoolB.getAlgTagMap().put("volunteer_score", 70D);
        VolunteerRecommendListResponse.VolunteerSchool schoolC = buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithPlanMajorDataId("103", "pm3", "专业C", "10"));
        schoolC.setSchool_rank(30);
        schoolC.getAlgTagMap().put("volunteer_score", 90D);
        response.setSprints(java.util.Arrays.asList(schoolA, schoolB, schoolC));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        orderedPlanState.setItems(java.util.Arrays.asList(
                buildOrderedItem("ps1_pm1_101", "学校A", "专业A"),
                buildOrderedItem("ps2_pm2_102", "学校B", "专业B"),
                buildOrderedItem("ps3_pm3_103", "学校C", "专业C")));
        state.setOrderedPlanState(orderedPlanState);
        savePlanningState(1L, state);

        com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq sortReq = new com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq();
        sortReq.setSortField("schoolRank");
        PlanningStateDTO sorted = planningStateService.sortOrderedPlan(1L, sortReq);

        assertEquals(java.util.Arrays.asList("ps2_pm2_102", "ps1_pm1_101", "ps3_pm3_103"), orderedVolunteerIds(sorted));
    }

    @Test
    void shouldMarkReviewStaleAfterOrderedPlanSort() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 3, 0, 0));
        response.setUserScoreDetail(buildScoreDetail());
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "20"));
        schoolA.setSchool_rank(20);
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "10"));
        schoolB.setSchool_rank(10);
        VolunteerRecommendListResponse.VolunteerSchool schoolC = buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "30"));
        schoolC.setSchool_rank(30);
        response.setSprints(java.util.Arrays.asList(schoolA, schoolB, schoolC));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());
        planningStateService.runReview(1L, 1L);

        com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq sortReq = new com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq();
        sortReq.setSortField("schoolRank");
        PlanningStateDTO sorted = planningStateService.sortOrderedPlan(1L, sortReq);
        com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes workspaceState =
                planningStateService.buildPlanningWorkspaceStateRes(sorted);

        assertTrue(sorted.getStaleFlags().getReview());
        assertEquals("stale", workspaceState.getWorkflowStatus().getReviewStatus());
        assertEquals("方案已调整，建议重新审查", workspaceState.getWorkflowStatus().getReviewMessage());
    }

    @Test
    void shouldReturnWorkspaceCandidateDetailsForLegacyMismatchedVolunteerIds() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(2, 2, 0, 0));
        response.setUserScoreDetail(buildScoreDetail());
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithPlanMajorDataId("101", "pm1", "专业A", "20"));
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithPlanMajorDataId("102", "pm2", "专业B", "40"));
        response.setSprints(java.util.Arrays.asList(schoolA, schoolB));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        orderedPlanState.setItems(java.util.Arrays.asList(
                buildOrderedItem("ps1_pm1_101", "学校A", "专业A"),
                buildOrderedItem("ps2_pm2_102", "学校B", "专业B")));
        state.setOrderedPlanState(orderedPlanState);
        savePlanningState(1L, state);

        com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes workspaceState =
                planningStateService.getPlanningWorkspaceState(1L);

        assertEquals(2, workspaceState.getCandidatePoolState().getItems().size());
        assertEquals(java.util.Arrays.asList("ps1_pm1_101", "ps2_pm2_102"),
                workspaceState.getCandidatePoolState().getItems().stream()
                        .map(CandidateItemDTO::getVolunteerId)
                        .collect(Collectors.toList()));
    }

    @Test
    void shouldAnalyzePlanAdjustmentRatioDistributionWithReplaceSuggestion() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(5, 3, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18")),
                buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "26")),
                buildSchool("ps4", "s4", "学校D", "北京", 4, buildMajorWithRatio("m4", "专业D", "30"))
        ));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps5", "s5", "学校E", "北京", 1, buildMajorWithRatio("m5", "专业E", "46"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps6", "s6", "学校F", "北京", 1, buildMajorWithRatio("m6", "专业F", "78")),
                buildSchool("ps7", "s7", "学校G", "北京", 2, buildMajorWithRatio("m7", "专业G", "82"))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4", "ps5_m5"));
        planningStateService.selectDraftItems(1L, selectReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("draft");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        assertTrue(adjustmentState.getSuggestions().getAddSuggestions().stream()
                .anyMatch(item -> "ratio_distribution".equals(item.getRuleCode())));
        assertTrue(adjustmentState.getSuggestions().getReplaceSuggestions().stream()
                .anyMatch(item -> "ratio_distribution".equals(item.getRuleCode())
                        && !item.getRemoveVolunteerIds().isEmpty()
                        && !item.getCandidateVolunteerIds().isEmpty()
                        && !item.getReplacementPairs().isEmpty()));
    }

    private VolunteerRecommendListResponse.VolunteerSchool buildSchool(String planSchoolDataId, String schoolId,
                                                                       String schoolName, String provinceName,
                                                                       Integer rankInTier,
                                                                       VolunteerRecommendListResponse.VolunteerMajor major) {
        VolunteerRecommendListResponse.VolunteerSchool school = new VolunteerRecommendListResponse.VolunteerSchool();
        school.setPlanSchoolDataId(planSchoolDataId);
        school.setSchoolId(schoolId);
        school.setSchool_name(schoolName);
        school.setProvince_name(provinceName);
        school.setCity_name(provinceName);
        school.setRank_in_tier(rankInTier);
        school.setMajors(java.util.Arrays.asList(major));
        return school;
    }

    private VolunteerRecommendListResponse.VolunteerMajor buildMajorWithRatio(String majorId, String majorName, String enrollRatio) {
        VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
        major.setMajorId(majorId);
        major.setPlanMajorDataId(majorId);
        major.setMajor_name(majorName);
        major.setEnroll_ratio(enrollRatio);
        return major;
    }

    private VolunteerRecommendListResponse.VolunteerMajor buildMajorWithPlanMajorDataId(String majorId,
                                                                                        String planMajorDataId,
                                                                                        String majorName,
                                                                                        String enrollRatio) {
        VolunteerRecommendListResponse.VolunteerMajor major = buildMajorWithRatio(majorId, majorName, enrollRatio);
        major.setPlanMajorDataId(planMajorDataId);
        return major;
    }

    private CreateSessionReq buildScoreDetail() {
        CreateSessionReq scoreDetail = new CreateSessionReq();
        scoreDetail.setHeight("170");
        scoreDetail.setSpecialPlan(true);
        scoreDetail.setAcceptForeignSchool(false);
        scoreDetail.setColorSistuation(java.util.Arrays.asList("normal"));

        CreateSessionReq.VisionAbility visionAbility = new CreateSessionReq.VisionAbility();
        visionAbility.setLeft("4.8");
        visionAbility.setRight("5.0");
        scoreDetail.setVisionAbility(visionAbility);

        CreateSessionReq.PreferredMajor major1 = new CreateSessionReq.PreferredMajor();
        major1.setMajorSubName("计算机");
        CreateSessionReq.PreferredMajor major2 = new CreateSessionReq.PreferredMajor();
        major2.setMajorSubName("电子信息");
        scoreDetail.setPreferredMajors(java.util.Arrays.asList(major1, major2));

        CreateSessionReq.UnacceptableMajor unacceptableMajor = new CreateSessionReq.UnacceptableMajor();
        unacceptableMajor.setMajorName("临床医学");
        scoreDetail.setUnacceptableMajors(java.util.Arrays.asList(unacceptableMajor));

        CreateSessionReq.PreferredRegion region1 = new CreateSessionReq.PreferredRegion();
        region1.setProvinceName("北京");
        CreateSessionReq.PreferredRegion region2 = new CreateSessionReq.PreferredRegion();
        region2.setProvinceName("上海");
        scoreDetail.setPreferredRegions(java.util.Arrays.asList(region1, region2));

        CreateSessionReq.SubjectScore subject1 = new CreateSessionReq.SubjectScore();
        subject1.setSubjectName("物理");
        CreateSessionReq.SubjectScore subject2 = new CreateSessionReq.SubjectScore();
        subject2.setSubjectName("化学");
        scoreDetail.setStrengthSubjectList(java.util.Arrays.asList(subject1, subject2));
        return scoreDetail;
    }

    private java.util.List<String> orderedVolunteerIds(PlanningStateDTO state) {
        return state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toList());
    }

    private OrderedItemDTO buildOrderedItem(String volunteerId, String schoolName, String majorName) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setSchoolName(schoolName);
        item.setMajorName(majorName);
        item.setTier("冲");
        return item;
    }

    private void savePlanningState(Long chatSessionId, PlanningStateDTO state) {
        ChatSessionExtraData data = new ChatSessionExtraData();
        data.setChatSessionId(chatSessionId);
        data.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        data.setDataValue(com.alibaba.fastjson.JSON.toJSONString(state));
        chatSessionExtraDataSharedService.save(data);
    }

    private VolunteerRecommendListResponse.BaseData buildBaseData(int needCount, int sprintCount, int safeCount, int protectCount) {
        VolunteerRecommendListResponse.BaseData baseData = new VolunteerRecommendListResponse.BaseData();
        baseData.setNeed_count(needCount);
        java.util.Map<String, Integer> targetMap = new java.util.HashMap<String, Integer>();
        targetMap.put("sprints_count", sprintCount);
        targetMap.put("safes_count", safeCount);
        targetMap.put("protects_count", protectCount);
        baseData.setThree_target_count_map(targetMap);
        return baseData;
    }

    private AtomicReference<ChatSessionExtraData> bindPlanningStateStore() {
        AtomicReference<ChatSessionExtraData> planningStateRef = new AtomicReference<ChatSessionExtraData>();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenAnswer(invocation -> planningStateRef.get());
        doAnswer(invocation -> {
            ChatSessionExtraData data = invocation.getArgument(0);
            ChatSessionExtraData stored = new ChatSessionExtraData();
            stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            stored.setDataValue(data.getDataValue());
            planningStateRef.set(stored);
            return true;
        }).when(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        doAnswer(invocation -> {
            ChatSessionExtraData data = invocation.getArgument(0);
            ChatSessionExtraData stored = new ChatSessionExtraData();
            stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            stored.setDataValue(data.getDataValue());
            planningStateRef.set(stored);
            return true;
        }).when(chatSessionExtraDataSharedService).updateById(any(ChatSessionExtraData.class));
        return planningStateRef;
    }
}
