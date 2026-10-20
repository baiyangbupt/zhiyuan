package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FutureDevelopmentDTO;
import com.ytell.zhiyuan.model.dto.planning.InitialPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentAnalyzeReq;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UpdateLatentProfileReq;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.entity.biz.PlanningDataFreshnessScheduleEntity;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.service.shared.PlanningDataFreshnessScheduleSharedService;
import com.ytell.zhiyuan.service.shared.PlanningBehaviorEventSharedService;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.when;

public class PlanningInitialPlanGenerationTest {

    private PlanningStateService planningStateService;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private ChatSessionSharedService chatSessionSharedService;
    private PlanningBehaviorEventSharedService planningBehaviorEventSharedService;
    private PlanningDataFreshnessScheduleSharedService planningDataFreshnessScheduleSharedService;
    private VolunteerSourceDataSyncService volunteerSourceDataSyncService;
    private VolunteerBizService volunteerBizService;

    @BeforeEach
    void setUp() {
        planningStateService = new PlanningStateService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);
        planningBehaviorEventSharedService = Mockito.mock(PlanningBehaviorEventSharedService.class);
        planningDataFreshnessScheduleSharedService = Mockito.mock(PlanningDataFreshnessScheduleSharedService.class);
        volunteerSourceDataSyncService = Mockito.mock(VolunteerSourceDataSyncService.class);
        volunteerBizService = Mockito.mock(VolunteerBizService.class);
        when(planningDataFreshnessScheduleSharedService.saveOrUpdateSchedule(any(PlanningDataFreshnessScheduleEntity.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        ReflectionTestUtils.setField(planningStateService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(planningStateService, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(planningStateService, "planningBehaviorEventSharedService", planningBehaviorEventSharedService);
        ReflectionTestUtils.setField(planningStateService, "planningDataFreshnessScheduleSharedService", planningDataFreshnessScheduleSharedService);
        ReflectionTestUtils.setField(planningStateService, "volunteerSourceDataSyncService", volunteerSourceDataSyncService);
        ReflectionTestUtils.setField(planningStateService, "volunteerBizService", volunteerBizService);
        ReflectionTestUtils.setField(planningStateService, "volunteerIntervalService", new VolunteerIntervalService());
    }

    @Test
    void shouldGenerateInitialPlanFromCandidatePoolAndPersistGenerationState() {
        AtomicReference<ChatSessionExtraData> planningStateRef = bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "20"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "55"))));
        response.setProtects(java.util.Arrays.asList(buildSchool("ps3", "s3", "学校C", "河北", 3, buildMajorWithRatio("m3", "专业C", "82"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        InitialPlanGenerateReq req = new InitialPlanGenerateReq();
        req.setRegroupByTier(true);
        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, req);

        assertEquals("initial_auto", state.getPlanGenerationState().getMode());
        assertTrue(Boolean.TRUE.equals(state.getPlanGenerationState().getAllowAutoComplete()));
        assertEquals(Integer.valueOf(3), state.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(3), state.getOrderedPlanState().getSummary().getTotal());
        assertEquals("initial_auto", state.getOrderedPlanState().getGenerationMode());
        assertTrue(state.getDraftPlanState().getItems().stream().allMatch(item -> "initial_auto".equals(item.getSource())));
        assertEquals("ordered", state.getPhase());
        assertNotNull(planningStateRef.get());
    }

    @Test
    void initialPlanMustRunStagedSelectionWhenConfirmedTargetDiffersFromHeuristic() {
        AtomicReference<ChatSessionExtraData> planningStateRef = bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "20"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "55"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "河北", 3, buildMajorWithRatio("m3", "专业C", "82"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO first = planningStateService.generateInitialPlan(
                1L, 1L, new InitialPlanGenerateReq());
        assertEquals(Integer.valueOf(3), first.getOrderedPlanState().getSummary().getTotal());

        // 下一次初始生成前：启发式仍会选 3 条，但已确认目标只有 2 条；
        // 初始方案必须强制重算排序并让 staged solver 收敛到 2，而不是沿用
        // saveWorkingPlanState 顺手同步出的 3 条 ordered。
        first.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(2);
        first.getWorkingPlanState().getItems().clear();
        first.getWorkingPlanState().getUnits().clear();
        first.getOrderedPlanState().getItems().clear();
        first.getOrderedPlanState().getUnits().clear();
        first.setInitialRecommendationState(null);
        first.getStaleFlags().setInitialRecommendation(true);
        first.getStaleFlags().setOrderedPlan(true);
        planningStateRef.get().setDataValue(com.alibaba.fastjson.JSON.toJSONString(first));

        InitialPlanGenerateReq req = new InitialPlanGenerateReq();
        req.setOverwriteExistingDraft(true);
        PlanningStateDTO second = planningStateService.generateInitialPlan(1L, 1L, req);

        assertEquals(Integer.valueOf(3),
                second.getInitialRecommendationState().getSummary().getTotal(),
                "启发式初荐仍是 3 条，用来证明后续确实发生了 solver 重选");
        assertEquals(Integer.valueOf(2), second.getOrderedPlanState().getSummary().getTotal());
        assertEquals(2, second.getOrderedPlanState().getItems().size());
    }

    @Test
    void initialSolverFlagCanRunWithoutConfirmedTarget() {
        AtomicReference<ChatSessionExtraData> planningStateRef = bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "20"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "55"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "河北", 3, buildMajorWithRatio("m3", "专业C", "82"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO first = planningStateService.generateInitialPlan(
                1L, 1L, new InitialPlanGenerateReq());
        assertEquals(3, first.getInitialRecommendationState().getItems().size());
        assertTrue(first.getConstraintState().getHardPlanningObjectives().getSelectionTargetCount() == null);

        // 模拟初荐只留下 2 条、但 requiredCount=3；无 durable selectionTarget。
        // flag 打开后 initial_auto 应把 requiredCount 作为临时目标交给 solver，
        // 因此最终 ordered 必须是 3 条；初荐仍保持 2 条，证明是 solver 补齐。
        while (first.getInitialRecommendationState().getItems().size() > 2) {
            first.getInitialRecommendationState().getItems().remove(
                    first.getInitialRecommendationState().getItems().size() - 1);
        }
        first.getWorkingPlanState().getItems().clear();
        first.getWorkingPlanState().getUnits().clear();
        first.getOrderedPlanState().getItems().clear();
        first.getOrderedPlanState().getUnits().clear();
        first.getStaleFlags().setInitialRecommendation(false);
        first.getStaleFlags().setOrderedPlan(true);
        planningStateRef.get().setDataValue(com.alibaba.fastjson.JSON.toJSONString(first));

        System.setProperty(InitialPlanSolverFlags.PROPERTY, "true");
        try {
            InitialPlanGenerateReq req = new InitialPlanGenerateReq();
            req.setOverwriteExistingDraft(true);
            PlanningStateDTO second = planningStateService.generateInitialPlan(1L, 1L, req);

            assertEquals(2, second.getInitialRecommendationState().getItems().size(),
                    "初荐仍是 2 条，solver 不得改写初荐域");
            assertEquals(Integer.valueOf(3), second.getOrderedPlanState().getSummary().getTotal(),
                    "initial solver 必须按 requiredCount 补到 3");
            assertEquals(3, second.getOrderedPlanState().getItems().size());
            assertTrue(second.getConstraintState().getHardPlanningObjectives()
                    .getSelectionTargetCount() == null, "临时初始目标不得落成 durable 目标");
        } finally {
            System.clearProperty(InitialPlanSolverFlags.PROPERTY);
        }
    }

    @Test
    void shouldGenerateInitialPlanFromRepairedInitialRecommendation() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 2, 2, 0));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "稳A", "北京", 1, buildMajorWithRatio("m3", "专业C", "42")),
                buildSchool("ps4", "s4", "稳B", "北京", 2, buildMajorWithRatio("m4", "专业D", "48")),
                buildSchool("ps5", "s5", "稳C", "北京", 3, buildMajorWithRatio("m5", "专业E", "26")),
                buildSchool("ps6", "s6", "稳D", "北京", 4, buildMajorWithRatio("m6", "专业F", "34"))));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        InitialPlanGenerateReq req = new InitialPlanGenerateReq();
        req.setRegroupByTier(true);
        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, req);

        java.util.List<String> draftIds = state.getDraftPlanState().getItems().stream()
                .map(item -> item.getVolunteerId())
                .collect(java.util.stream.Collectors.toList());

        assertEquals(Integer.valueOf(4), state.getInitialRecommendationState().getSummary().getTotal());
        assertTrue(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps2_m2"));
        assertTrue(draftIds.contains("ps5_m5"));
        assertTrue(draftIds.contains("ps6_m6"));
        assertFalse(draftIds.contains("ps3_m3"));
        assertFalse(draftIds.contains("ps4_m4"));
        assertEquals("initial_auto", state.getOrderedPlanState().getGenerationMode());
        assertEquals("ordered", state.getPhase());
    }

    @Test
    void shouldUseMajorVolunteerCountWhenNeedCountAndTierTargetsAreMissing() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(0, 0, 0, 0);
        baseData.setNeed_count(null);
        baseData.setThree_target_count_map(new java.util.HashMap<String, Integer>());
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setMajorCount(3);
        volunteerCount.setSchoolCount(0);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.major);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "25")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "30"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "稳A", "北京", 1, buildMajorWithRatio("m3", "专业C", "50")),
                buildSchool("ps4", "s4", "稳B", "北京", 2, buildMajorWithRatio("m4", "专业D", "55"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "保A", "河北", 1, buildMajorWithRatio("m5", "专业E", "80"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(5, state.getCandidatePoolState().getItems().size());
        assertEquals(Integer.valueOf(3), state.getCandidatePoolState().getRequiredMajorCount());
        assertEquals(Integer.valueOf(3), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(3), state.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(3), state.getOrderedPlanState().getSummary().getTotal());
    }

    @Test
    void shouldUseUnitVolunteerCountInMajorGroupWhenNeedCountAndTierTargetsAreMissing() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(0, 0, 0, 0);
        baseData.setNeed_count(null);
        baseData.setThree_target_count_map(new java.util.HashMap<String, Integer>());
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(2);
        volunteerCount.setMajorCount(4);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1, buildMajorWithRatio("m1", "专业A1", "42"));
        sprintGroup.setEnroll_ratio("40");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "42"),
                buildMajorWithRatio("m2", "专业A2", "45")));

        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1, buildMajorWithRatio("m3", "专业B1", "62"));
        safeGroup.setEnroll_ratio("60");
        safeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m3", "专业B1", "62"),
                buildMajorWithRatio("m4", "专业B2", "65")));

        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps3", "s3", "专业组C", "河北", 1, buildMajorWithRatio("m5", "专业C1", "82"));
        protectGroup.setEnroll_ratio("80");
        protectGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m5", "专业C1", "82"),
                buildMajorWithRatio("m6", "专业C2", "86")));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Arrays.asList(protectGroup));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(6, state.getCandidatePoolState().getItems().size());
        assertEquals(Integer.valueOf(2), state.getCandidatePoolState().getRequiredUnitCount());
        assertEquals(Integer.valueOf(4), state.getCandidatePoolState().getRequiredMajorCount());
        assertEquals(Integer.valueOf(2), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(2, state.getInitialRecommendationState().getUnits().size());
        assertEquals(Integer.valueOf(2), state.getDraftPlanState().getSummary().getTotal());
        assertEquals(2, state.getDraftPlanState().getUnits().size());
        assertEquals(Integer.valueOf(2), state.getOrderedPlanState().getSummary().getTotal());
        assertEquals(2, state.getOrderedPlanState().getUnits().size());
    }

    @Test
    void shouldKeepMajorInitialPlanStableBeforePlanAdjustmentAnalysis() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 2, 2, 0));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "稳A", "北京", 1, buildMajorWithRatio("m3", "专业C", "42")),
                buildSchool("ps4", "s4", "稳B", "北京", 2, buildMajorWithRatio("m4", "专业D", "48")),
                buildSchool("ps5", "s5", "稳C", "北京", 3, buildMajorWithRatio("m5", "专业E", "26")),
                buildSchool("ps6", "s6", "稳D", "北京", 4, buildMajorWithRatio("m6", "专业F", "34"))));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO initialState = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        java.util.List<String> draftIds = initialState.getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(java.util.stream.Collectors.toList());
        assertTrue(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps2_m2"));
        assertTrue(draftIds.contains("ps5_m5"));
        assertTrue(draftIds.contains("ps6_m6"));
        assertFalse(initialState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("probability_inversion"));
        assertFalse(initialState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("probability_gap"));

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        java.util.Map<String, Boolean> ruleHits = adjustmentState.getAnalysis().getRules().stream()
                .collect(java.util.stream.Collectors.toMap(
                        rule -> rule.getRuleCode(),
                        rule -> Boolean.TRUE.equals(rule.getHit()),
                        (left, right) -> left,
                        java.util.LinkedHashMap::new));

        assertFalse(Boolean.TRUE.equals(ruleHits.get("probability_inversion")));
        assertFalse(Boolean.TRUE.equals(ruleHits.get("probability_gap")));
        assertFalse(Boolean.TRUE.equals(ruleHits.get("unit_major_count_validation")));
        assertFalse(Boolean.TRUE.equals(ruleHits.get("group_inner_safety_guard")));
    }

    @Test
    void shouldGenerateInitialPlanByUnitInMajorGroupMode() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(2, 1, 1, 0);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(2);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1, buildMajorWithRatio("m1", "专业A1", "60"));
        sprintGroup.setEnroll_ratio("45");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "60"),
                buildMajorWithRatio("m2", "专业A2", "42"),
                buildMajorWithRatio("m3", "专业A3", "40")));

        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1, buildMajorWithRatio("m4", "专业B1", "85"));
        safeGroup.setEnroll_ratio("70");
        safeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业B1", "85"),
                buildMajorWithRatio("m5", "专业B2", "68"),
                buildMajorWithRatio("m6", "专业B3", "61")));

        VolunteerRecommendListResponse.VolunteerSchool safeGroupLow = buildSchool("ps3", "s3", "专业组C", "北京", 2, buildMajorWithRatio("m7", "专业C1", "73"));
        safeGroupLow.setEnroll_ratio("72");
        safeGroupLow.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m7", "专业C1", "73"),
                buildMajorWithRatio("m8", "专业C2", "65")));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup, safeGroupLow));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        java.util.Map<String, CandidateItemDTO> candidateMap = state.getCandidatePoolState().getItems().stream()
                .collect(java.util.stream.Collectors.toMap(CandidateItemDTO::getVolunteerId, item -> item));
        java.util.Map<String, java.util.List<DraftItemDTO>> groupedDraft = state.getDraftPlanState().getItems().stream()
                .collect(java.util.stream.Collectors.groupingBy(item -> {
                    CandidateItemDTO candidate = candidateMap.get(item.getVolunteerId());
                    return candidate == null ? "unknown" : candidate.getPlanSchoolDataId();
                }));

        assertEquals(Integer.valueOf(2), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(2, state.getInitialRecommendationState().getUnits().size());
        assertEquals(2, groupedDraft.size());
        assertEquals(Integer.valueOf(2), state.getDraftPlanState().getSummary().getTotal());
        assertEquals(2, state.getDraftPlanState().getUnits().size());
        assertEquals(Integer.valueOf(2), state.getOrderedPlanState().getSummary().getTotal());
        assertEquals(2, state.getOrderedPlanState().getUnits().size());
        assertTrue(groupedDraft.containsKey("ps1"));
        assertTrue(groupedDraft.containsKey("ps2"));
        assertFalse(groupedDraft.containsKey("ps3"));
    }

    @Test
    void shouldTreatEqualRatioMajorAsSafetyMajorInMajorGroupInitialPlan() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(1, 1, 0, 0);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(1);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerMajor preferredMajor = buildMajorWithRatio("m1", "专业A1", "60");
        preferredMajor.setAlgTagMap(buildMajorScoreTagMap(60D));
        VolunteerRecommendListResponse.VolunteerMajor equalSafetyMajor = buildMajorWithRatio("m2", "专业A2", "45");
        equalSafetyMajor.setAlgTagMap(buildMajorScoreTagMap(20D));

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1, preferredMajor);
        sprintGroup.setEnroll_ratio("45");
        sprintGroup.setMajors(java.util.Arrays.asList(
                preferredMajor,
                equalSafetyMajor,
                buildMajorWithRatio("m3", "专业A3", "30")));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(1, state.getInitialRecommendationState().getUnits().size());
        PlanningUnitDTO unit = state.getInitialRecommendationState().getUnits().get(0);
        assertTrue(Boolean.TRUE.equals(unit.getHasSafetyMajor()));
        assertTrue(unit.getSelectedMajors().stream()
                .anyMatch(major -> "ps1_m2".equals(major.getVolunteerId()) && Boolean.TRUE.equals(major.getSafetyMajor())));
    }

    @Test
    void shouldPreferPublicSectorAlignedCandidateWhenGeneratingInitialPlan() {
        bindPlanningStateStore();
        applyPublicSectorCareerType();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(1, 0, 1, 0));
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool privateSchool = buildSchool(
                "ps1", "s1", "金审学院", "江苏", 1, buildMajorWithRatio("m1", "金融学", "52"));
        privateSchool.setSchool_nature("民办");
        privateSchool.setSchool_level("本科");
        privateSchool.setSchool_category("财经");
        privateSchool.setAlgTagMap(buildSchoolScoreTagMap(60D));

        VolunteerRecommendListResponse.VolunteerSchool publicSchool = buildSchool(
                "ps2", "s2", "师范学院", "河北", 2, buildMajorWithRatio("m2", "思想政治教育", "52"));
        publicSchool.setSchool_nature("公办");
        publicSchool.setSchool_level("本科");
        publicSchool.setSchool_category("师范");
        publicSchool.setAlgTagMap(buildSchoolScoreTagMap(56D));

        response.setSprints(java.util.Collections.emptyList());
        response.setSafes(java.util.Arrays.asList(privateSchool, publicSchool));
        response.setProtects(java.util.Collections.emptyList());

        publicSchool.getMajors().get(0).setAlgTagMap(buildMajorScoreTagMap(56D));
        privateSchool.getMajors().get(0).setAlgTagMap(buildMajorScoreTagMap(60D));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(1), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals("ps2_m2", state.getDraftPlanState().getItems().get(0).getVolunteerId());
    }

    @Test
    void shouldOrderPublicSectorAlignedDraftItemsEarlierWhenCareerTypePresent() {
        CandidateItemDTO privateCandidate = new CandidateItemDTO();
        privateCandidate.setVolunteerId("ps1_m1");
        privateCandidate.setTier("稳");
        privateCandidate.setAdmissionRatio(55D);
        privateCandidate.setRankInTier(1);
        privateCandidate.setFinalScore(60D);
        privateCandidate.setFutureDevelopmentScore(-0.5D);

        CandidateItemDTO publicCandidate = new CandidateItemDTO();
        publicCandidate.setVolunteerId("ps2_m2");
        publicCandidate.setTier("稳");
        publicCandidate.setAdmissionRatio(55D);
        publicCandidate.setRankInTier(2);
        publicCandidate.setFinalScore(56D);
        publicCandidate.setFutureDevelopmentScore(6.5D);

        java.util.Map<String, CandidateItemDTO> candidateMap = new java.util.LinkedHashMap<String, CandidateItemDTO>();
        candidateMap.put(privateCandidate.getVolunteerId(), privateCandidate);
        candidateMap.put(publicCandidate.getVolunteerId(), publicCandidate);

        @SuppressWarnings("unchecked")
        java.util.Comparator<DraftItemDTO> comparator = (java.util.Comparator<DraftItemDTO>) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildDraftOrderedComparator",
                candidateMap,
                null,
                false);

        DraftItemDTO privateDraft = new DraftItemDTO();
        privateDraft.setVolunteerId("ps1_m1");
        privateDraft.setTier("稳");
        DraftItemDTO publicDraft = new DraftItemDTO();
        publicDraft.setVolunteerId("ps2_m2");
        publicDraft.setTier("稳");

        java.util.List<DraftItemDTO> items = new java.util.ArrayList<DraftItemDTO>(java.util.Arrays.asList(privateDraft, publicDraft));
        items.sort(comparator);

        assertEquals("ps2_m2", items.get(0).getVolunteerId());
        assertEquals("ps1_m1", items.get(1).getVolunteerId());
    }

    @Test
    void shouldKeepAdmissionRatioGradientBeforeFutureDevelopmentScoreWithinTier() {
        CandidateItemDTO lowerRatioCandidate = new CandidateItemDTO();
        lowerRatioCandidate.setVolunteerId("ps1_m1");
        lowerRatioCandidate.setTier("冲");
        lowerRatioCandidate.setAdmissionRatio(30D);
        lowerRatioCandidate.setRankInTier(2);
        lowerRatioCandidate.setFinalScore(55D);
        lowerRatioCandidate.setFutureDevelopmentScore(-0.5D);

        CandidateItemDTO higherRatioCandidate = new CandidateItemDTO();
        higherRatioCandidate.setVolunteerId("ps2_m2");
        higherRatioCandidate.setTier("冲");
        higherRatioCandidate.setAdmissionRatio(48D);
        higherRatioCandidate.setRankInTier(1);
        higherRatioCandidate.setFinalScore(70D);
        higherRatioCandidate.setFutureDevelopmentScore(8D);

        java.util.Map<String, CandidateItemDTO> candidateMap = new java.util.LinkedHashMap<String, CandidateItemDTO>();
        candidateMap.put(lowerRatioCandidate.getVolunteerId(), lowerRatioCandidate);
        candidateMap.put(higherRatioCandidate.getVolunteerId(), higherRatioCandidate);

        @SuppressWarnings("unchecked")
        java.util.Comparator<DraftItemDTO> comparator = (java.util.Comparator<DraftItemDTO>) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildDraftOrderedComparator",
                candidateMap,
                null,
                false);

        DraftItemDTO lowerRatioDraft = new DraftItemDTO();
        lowerRatioDraft.setVolunteerId("ps1_m1");
        lowerRatioDraft.setTier("冲");
        DraftItemDTO higherRatioDraft = new DraftItemDTO();
        higherRatioDraft.setVolunteerId("ps2_m2");
        higherRatioDraft.setTier("冲");

        java.util.List<DraftItemDTO> items = new java.util.ArrayList<DraftItemDTO>(java.util.Arrays.asList(higherRatioDraft, lowerRatioDraft));
        items.sort(comparator);

        assertEquals("ps1_m1", items.get(0).getVolunteerId());
        assertEquals("ps2_m2", items.get(1).getVolunteerId());
    }

    @Test
    void shouldUseSchoolEnrollRatioForMajorGroupOrderedGradient() {
        CandidateItemDTO lowMajorHighGroupCandidate = new CandidateItemDTO();
        lowMajorHighGroupCandidate.setVolunteerId("unitA_m1");
        lowMajorHighGroupCandidate.setTier("冲");
        lowMajorHighGroupCandidate.setAdmissionRatio(4D);
        lowMajorHighGroupCandidate.setSchoolEnrollRatio(50D);
        lowMajorHighGroupCandidate.setRankInTier(1);
        lowMajorHighGroupCandidate.setFinalScore(80D);
        lowMajorHighGroupCandidate.setFutureDevelopmentScore(8D);

        CandidateItemDTO higherMajorLowerGroupCandidate = new CandidateItemDTO();
        higherMajorLowerGroupCandidate.setVolunteerId("unitB_m1");
        higherMajorLowerGroupCandidate.setTier("冲");
        higherMajorLowerGroupCandidate.setAdmissionRatio(18D);
        higherMajorLowerGroupCandidate.setSchoolEnrollRatio(46D);
        higherMajorLowerGroupCandidate.setRankInTier(2);
        higherMajorLowerGroupCandidate.setFinalScore(60D);
        higherMajorLowerGroupCandidate.setFutureDevelopmentScore(-0.5D);

        java.util.Map<String, CandidateItemDTO> candidateMap = new java.util.LinkedHashMap<String, CandidateItemDTO>();
        candidateMap.put(lowMajorHighGroupCandidate.getVolunteerId(), lowMajorHighGroupCandidate);
        candidateMap.put(higherMajorLowerGroupCandidate.getVolunteerId(), higherMajorLowerGroupCandidate);

        @SuppressWarnings("unchecked")
        java.util.Comparator<DraftItemDTO> comparator = (java.util.Comparator<DraftItemDTO>) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildDraftOrderedComparator",
                candidateMap,
                null,
                true);

        DraftItemDTO lowMajorHighGroupDraft = new DraftItemDTO();
        lowMajorHighGroupDraft.setVolunteerId("unitA_m1");
        lowMajorHighGroupDraft.setTier("冲");
        DraftItemDTO higherMajorLowerGroupDraft = new DraftItemDTO();
        higherMajorLowerGroupDraft.setVolunteerId("unitB_m1");
        higherMajorLowerGroupDraft.setTier("冲");

        java.util.List<DraftItemDTO> items = new java.util.ArrayList<DraftItemDTO>(java.util.Arrays.asList(lowMajorHighGroupDraft, higherMajorLowerGroupDraft));
        items.sort(comparator);

        assertEquals("unitB_m1", items.get(0).getVolunteerId());
        assertEquals("unitA_m1", items.get(1).getVolunteerId());
    }

    @Test
    void shouldKeepProtectAdmissionGradientBeforeLocalProtectPriority() {
        CandidateItemDTO localHighRatioCandidate = new CandidateItemDTO();
        localHighRatioCandidate.setVolunteerId("local_m1");
        localHighRatioCandidate.setTier("保");
        localHighRatioCandidate.setProvinceName("湖北");
        localHighRatioCandidate.setAdmissionRatio(99D);
        localHighRatioCandidate.setSchoolEnrollRatio(99D);
        localHighRatioCandidate.setRankInTier(1);
        localHighRatioCandidate.setFinalScore(80D);

        CandidateItemDTO nonLocalLowerRatioCandidate = new CandidateItemDTO();
        nonLocalLowerRatioCandidate.setVolunteerId("nonlocal_m1");
        nonLocalLowerRatioCandidate.setTier("保");
        nonLocalLowerRatioCandidate.setProvinceName("山东");
        nonLocalLowerRatioCandidate.setAdmissionRatio(75D);
        nonLocalLowerRatioCandidate.setSchoolEnrollRatio(75D);
        nonLocalLowerRatioCandidate.setRankInTier(2);
        nonLocalLowerRatioCandidate.setFinalScore(60D);

        java.util.Map<String, CandidateItemDTO> candidateMap = new java.util.LinkedHashMap<String, CandidateItemDTO>();
        candidateMap.put(localHighRatioCandidate.getVolunteerId(), localHighRatioCandidate);
        candidateMap.put(nonLocalLowerRatioCandidate.getVolunteerId(), nonLocalLowerRatioCandidate);

        @SuppressWarnings("unchecked")
        java.util.Comparator<DraftItemDTO> comparator = (java.util.Comparator<DraftItemDTO>) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildDraftOrderedComparator",
                candidateMap,
                "湖北",
                true);

        DraftItemDTO localHighRatioDraft = new DraftItemDTO();
        localHighRatioDraft.setVolunteerId("local_m1");
        localHighRatioDraft.setTier("保");
        DraftItemDTO nonLocalLowerRatioDraft = new DraftItemDTO();
        nonLocalLowerRatioDraft.setVolunteerId("nonlocal_m1");
        nonLocalLowerRatioDraft.setTier("保");

        java.util.List<DraftItemDTO> items = new java.util.ArrayList<DraftItemDTO>(java.util.Arrays.asList(localHighRatioDraft, nonLocalLowerRatioDraft));
        items.sort(comparator);

        assertEquals("nonlocal_m1", items.get(0).getVolunteerId());
        assertEquals("local_m1", items.get(1).getVolunteerId());
    }

    @Test
    void shouldNotChangeCandidatePoolMemberCountWhenCareerTypePresent() {
        bindPlanningStateStore();
        applyPublicSectorCareerType();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(2, 0, 2, 0));
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool privateSchool = buildSchool(
                "ps1", "s1", "民办财经", "江苏", 1, buildMajorWithRatio("m1", "金融学", "52"));
        privateSchool.setSchool_nature("民办");
        privateSchool.setSchool_level("本科");
        privateSchool.setSchool_category("财经");
        privateSchool.setAlgTagMap(buildSchoolScoreTagMap(60D));
        privateSchool.getMajors().get(0).setAlgTagMap(buildMajorScoreTagMap(60D));

        VolunteerRecommendListResponse.VolunteerSchool publicSchool = buildSchool(
                "ps2", "s2", "公办师范", "河北", 2, buildMajorWithRatio("m2", "思想政治教育", "52"));
        publicSchool.setSchool_nature("公办");
        publicSchool.setSchool_level("本科");
        publicSchool.setSchool_category("师范");
        publicSchool.setAlgTagMap(buildSchoolScoreTagMap(56D));
        publicSchool.getMajors().get(0).setAlgTagMap(buildMajorScoreTagMap(56D));

        response.setSprints(java.util.Collections.emptyList());
        response.setSafes(java.util.Arrays.asList(privateSchool, publicSchool));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(2, state.getCandidatePoolState().getItems().size());
        assertEquals(Integer.valueOf(2), state.getCandidatePoolState().getSummary().getEntryTotal());
        java.util.Set<String> selectedIds = state.getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(java.util.stream.Collectors.toSet());
        assertEquals(new java.util.HashSet<String>(java.util.Arrays.asList("ps1_m1", "ps2_m2")), selectedIds);
    }

    @Test
    void shouldPreferPublicSectorAlignedMajorGroupWhenGeneratingInitialPlan() {
        bindPlanningStateStore();
        applyPublicSectorCareerType();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(1, 0, 1, 0);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(1);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool privateGroup = buildSchool("ps1", "s1", "民办财经组", "江苏", 1,
                buildMajorWithRatio("m1", "金融学", "60"));
        privateGroup.setSchool_nature("民办");
        privateGroup.setSchool_level("本科");
        privateGroup.setSchool_category("财经");
        privateGroup.setEnroll_ratio("52");
        privateGroup.setAlgTagMap(buildSchoolScoreTagMap(60D));
        privateGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "金融学", "60"),
                buildMajorWithRatio("m2", "会计学", "58")));
        privateGroup.getMajors().forEach(major -> major.setAlgTagMap(buildMajorScoreTagMap(60D)));

        VolunteerRecommendListResponse.VolunteerSchool publicGroup = buildSchool("ps2", "s2", "公办师范组", "河北", 2,
                buildMajorWithRatio("m3", "思想政治教育", "60"));
        publicGroup.setSchool_nature("公办");
        publicGroup.setSchool_level("本科");
        publicGroup.setSchool_category("师范");
        publicGroup.setEnroll_ratio("52");
        publicGroup.setAlgTagMap(buildSchoolScoreTagMap(56D));
        publicGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m3", "思想政治教育", "60"),
                buildMajorWithRatio("m4", "汉语言文学", "57")));
        publicGroup.getMajors().forEach(major -> major.setAlgTagMap(buildMajorScoreTagMap(56D)));

        response.setSprints(java.util.Collections.emptyList());
        response.setSafes(java.util.Arrays.asList(privateGroup, publicGroup));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(1), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(1, state.getInitialRecommendationState().getUnits().size());
        assertEquals("ps2", state.getInitialRecommendationState().getUnits().get(0).getUnitId());
        assertEquals("ps2", state.getDraftPlanState().getUnits().get(0).getUnitId());
        assertTrue(state.getDraftPlanState().getItems().stream().allMatch(item -> item.getVolunteerId().startsWith("ps2_")));
    }

    @Test
    void shouldPreferPublicSectorAlignedMajorsWithinMajorGroupWhenCareerTypePresent() {
        @SuppressWarnings("unchecked")
        java.util.Comparator<CandidateItemDTO> comparator = (java.util.Comparator<CandidateItemDTO>) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildMajorGroupInnerCandidateComparator");

        CandidateItemDTO privateMajor = new CandidateItemDTO();
        privateMajor.setVolunteerId("ps1_m1");
        privateMajor.setPreferred(true);
        privateMajor.setIntentScore(60D);
        privateMajor.setFinalScore(60D);
        privateMajor.setAdmissionRatio(55D);
        privateMajor.setFutureDevelopmentScore(-0.5D);

        CandidateItemDTO publicMajor = new CandidateItemDTO();
        publicMajor.setVolunteerId("ps1_m2");
        publicMajor.setPreferred(true);
        publicMajor.setIntentScore(56D);
        publicMajor.setFinalScore(56D);
        publicMajor.setAdmissionRatio(55D);
        publicMajor.setFutureDevelopmentScore(6.5D);

        java.util.List<CandidateItemDTO> majors = new java.util.ArrayList<CandidateItemDTO>(java.util.Arrays.asList(privateMajor, publicMajor));
        majors.sort(comparator);

        assertEquals("ps1_m2", majors.get(0).getVolunteerId());
        assertEquals("ps1_m1", majors.get(1).getVolunteerId());
    }

    @Test
    void shouldRegenerateInitialRecommendationWhenForceRegenerateIsTrue() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse first = new VolunteerRecommendListResponse();
        first.setBaseData(buildBaseData(4, 2, 2, 0));
        first.setUserScoreDetail(buildScoreDetail());
        first.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "12")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18"))));
        first.setSafes(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "稳A", "北京", 1, buildMajorWithRatio("m5", "专业E", "55")),
                buildSchool("ps6", "s6", "稳B", "北京", 2, buildMajorWithRatio("m6", "专业F", "60"))));
        first.setProtects(java.util.Collections.emptyList());

        VolunteerRecommendListResponse second = new VolunteerRecommendListResponse();
        second.setBaseData(buildBaseData(4, 2, 2, 0));
        second.setUserScoreDetail(buildScoreDetail());
        second.setSprints(java.util.Collections.emptyList());
        second.setSafes(java.util.Arrays.asList(
                buildSchool("rp3", "rs3", "稳A", "北京", 1, buildMajorWithRatio("rm3", "专业C", "42")),
                buildSchool("rp4", "rs4", "稳B", "北京", 2, buildMajorWithRatio("rm4", "专业D", "48")),
                buildSchool("rp5", "rs5", "稳C", "北京", 3, buildMajorWithRatio("rm5", "专业E", "52")),
                buildSchool("rp6", "rs6", "稳D", "北京", 4, buildMajorWithRatio("rm6", "专业F", "58"))));
        second.setProtects(java.util.Collections.emptyList());

        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false))
                .thenReturn(first)
                .thenReturn(second)
                .thenReturn(second);

        PlanningStateDTO firstState = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());
        assertEquals(Integer.valueOf(2), firstState.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(2), firstState.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));

        InitialPlanGenerateReq forceReq = new InitialPlanGenerateReq();
        forceReq.setForceRegenerate(true);
        forceReq.setOverwriteExistingDraft(true);
        PlanningStateDTO regenerated = planningStateService.generateInitialPlan(1L, 1L, forceReq);

        assertEquals(Integer.valueOf(0), regenerated.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(4), regenerated.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
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

    private java.util.Map<String, Object> buildMajorScoreTagMap(Double score) {
        java.util.Map<String, Object> algTagMap = new java.util.HashMap<String, Object>();
        algTagMap.put("major_score_new", score);
        return algTagMap;
    }

    private java.util.Map<String, Object> buildSchoolScoreTagMap(Double score) {
        java.util.Map<String, Object> algTagMap = new java.util.HashMap<String, Object>();
        algTagMap.put("volunteer_score", score);
        return algTagMap;
    }

    private void applyPublicSectorCareerType() {
        UpdateLatentProfileReq req = new UpdateLatentProfileReq();
        FutureDevelopmentDTO futureDevelopment = new FutureDevelopmentDTO();
        futureDevelopment.setCareerTypes(java.util.Arrays.asList("体制内/考公导向"));
        req.setFutureDevelopment(futureDevelopment);
        planningStateService.updateLatentProfile(1L, req);
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
        return scoreDetail;
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
        java.util.concurrent.atomic.AtomicLong idGenerator = new java.util.concurrent.atomic.AtomicLong(1L);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenAnswer(invocation -> planningStateRef.get());
        doAnswer(invocation -> {
            ChatSessionExtraData data = invocation.getArgument(0);
            ChatSessionExtraData stored = new ChatSessionExtraData();
            stored.setId(data.getId() != null ? data.getId() : idGenerator.getAndIncrement());
            stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            stored.setDataValue(data.getDataValue());
            // 回填主键：生产路径（sharedService.save）会把自增 id 写回实体，CAS 落盘依赖它
            data.setId(stored.getId());
            planningStateRef.set(stored);
            return true;
        }).when(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        doAnswer(invocation -> {
            ChatSessionExtraData data = invocation.getArgument(0);
            ChatSessionExtraData stored = new ChatSessionExtraData();
            stored.setId(data.getId() != null ? data.getId() : idGenerator.getAndIncrement());
            stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            stored.setDataValue(data.getDataValue());
            data.setId(stored.getId());
            planningStateRef.set(stored);
            return true;
        }).when(chatSessionExtraDataSharedService).updateById(any(ChatSessionExtraData.class));
        // CAS 语义替身（H2 写路径统一 CAS）：只有"库里那行仍是我们读到的那份"（id+data_value
        // 都一致）才写入；赢了之后行对象替换成新值，下一次读/CAS 拿到的是更新后的那份。
        when(chatSessionExtraDataSharedService.updateDataValueIfUnchanged(
                any(ChatSessionExtraData.class), any(), any()))
                .thenAnswer(invocation -> {
                    ChatSessionExtraData current = invocation.getArgument(0);
                    String expectedDataValue = invocation.getArgument(1);
                    String newDataValue = invocation.getArgument(2);
                    ChatSessionExtraData stored = planningStateRef.get();
                    if (current == null || stored == null || stored.getId() == null
                            || !stored.getId().equals(current.getId())) {
                        return false;
                    }
                    boolean sameValue = expectedDataValue == null
                            ? stored.getDataValue() == null
                            : expectedDataValue.equals(stored.getDataValue());
                    if (!sameValue) {
                        return false;
                    }
                    ChatSessionExtraData updated = new ChatSessionExtraData();
                    updated.setId(stored.getId());
                    updated.setDataKey(stored.getDataKey());
                    updated.setDataValue(newDataValue);
                    planningStateRef.set(updated);
                    return true;
                });
        return planningStateRef;
    }
}
