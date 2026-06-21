package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.manager.MajorExtraDataManager;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.inner.VolunteerSourceDataSnapshot;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateFilterOptionsDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateViewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationPreviewDTO;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessCheckReq;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessCheckRes;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintDeriveRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanReorderReq;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftLockReq;
import com.ytell.zhiyuan.model.dto.planning.DraftRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.DraftSelectReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.InitialPlanStrategyReportDTO;
import com.ytell.zhiyuan.model.dto.planning.InitialPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedMoveReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanSortReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitMoveReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentAnalyzeReq;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentApplyReq;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentStateDTO;
import com.ytell.zhiyuan.model.dto.planning.AddSuggestionDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateVersionDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.dto.planning.ReorderSuggestionDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplaceSuggestionDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewWorkflowRunRes;
import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import com.ytell.zhiyuan.model.dto.planning.UpdateLatentProfileReq;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import com.ytell.zhiyuan.model.dto.planning.InitialRecommendationGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.MarkPlanningIntentStaleReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningBehaviorEventDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.entity.biz.PlanningDataFreshnessScheduleEntity;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.service.shared.PlanningBehaviorEventSharedService;
import com.ytell.zhiyuan.service.shared.PlanningDataFreshnessScheduleSharedService;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Comparator;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class PlanningStateServiceTest {

    private PlanningStateService planningStateService;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private ChatSessionSharedService chatSessionSharedService;
    private PlanningBehaviorEventSharedService planningBehaviorEventSharedService;
    private VolunteerDataProvider volunteerDataProvider;
    private PlanningExcelExportBuilder planningExcelExportBuilder;
    private VolunteerBizService volunteerBizService;
    private SchoolManager schoolManager;
    private VolunteerSourceDataSyncService volunteerSourceDataSyncService;
    private PlanningDataFreshnessScheduleSharedService planningDataFreshnessScheduleSharedService;

    @BeforeEach
    void setUp() {
        planningStateService = new PlanningStateService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);
        planningBehaviorEventSharedService = Mockito.mock(PlanningBehaviorEventSharedService.class);
        volunteerDataProvider = Mockito.mock(VolunteerDataProvider.class);
        planningExcelExportBuilder = new PlanningExcelExportBuilder();
        volunteerBizService = Mockito.mock(VolunteerBizService.class);
        schoolManager = Mockito.mock(SchoolManager.class);
        volunteerSourceDataSyncService = Mockito.mock(VolunteerSourceDataSyncService.class);
        planningDataFreshnessScheduleSharedService = Mockito.mock(PlanningDataFreshnessScheduleSharedService.class);
        when(planningDataFreshnessScheduleSharedService.saveOrUpdateSchedule(any(PlanningDataFreshnessScheduleEntity.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        MajorExtraDataManager majorExtraDataManager = new MajorExtraDataManager();
        majorExtraDataManager.init();
        ReflectionTestUtils.setField(planningStateService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(planningStateService, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(planningStateService, "planningBehaviorEventSharedService", planningBehaviorEventSharedService);
        ReflectionTestUtils.setField(planningStateService, "volunteerDataProvider", volunteerDataProvider);
        ReflectionTestUtils.setField(planningStateService, "planningExcelExportBuilder", planningExcelExportBuilder);
        ReflectionTestUtils.setField(planningStateService, "volunteerBizService", volunteerBizService);
        ReflectionTestUtils.setField(planningStateService, "volunteerSourceDataSyncService", volunteerSourceDataSyncService);
        ReflectionTestUtils.setField(planningStateService, "planningDataFreshnessScheduleSharedService", planningDataFreshnessScheduleSharedService);
        ReflectionTestUtils.setField(planningStateService, "volunteerIntervalService", new VolunteerIntervalService());
        ReflectionTestUtils.setField(planningStateService, "majorExtraDataManager", majorExtraDataManager);
        ReflectionTestUtils.setField(planningStateService, "schoolManager", schoolManager);
    }

    @Test
    void shouldReturnDefaultPlanningStateWhenMissing() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(1L, ChatSessionExtraDataConstants.PLANNING_STATE_KEY))
                .thenReturn(null);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals(Long.valueOf(1L), state.getSessionId());
        assertEquals(Integer.valueOf(0), state.getVersion());
        assertEquals("profile_ready", state.getPhase());
    }

    @Test
    void shouldMarkPreferenceIntentChangeStaleWithoutCandidatePool() {
        bindPlanningStateStore();
        PlanningStateDTO initial = planningStateService.getPlanningState(1L);
        initial.getStaleFlags().setCandidatePool(false);
        initial.getStaleFlags().setRecommendationOverlay(false);
        initial.getStaleFlags().setInitialRecommendation(false);
        initial.getStaleFlags().setOrderedPlan(false);
        initial.getStaleFlags().setPlanAdjustment(false);
        initial.getStaleFlags().setReview(false);
        saveStateToStore(1L, initial);

        MarkPlanningIntentStaleReq req = new MarkPlanningIntentStaleReq();
        req.setIntentMode("preference");
        PlanningStateVersionDTO version = planningStateService.markIntentChangeStale(1L, req);

        assertEquals(Integer.valueOf(1), version.getVersion());
        assertFalse(staleCandidatePool(version.getStaleFlags()));
        assertTrue(staleRecommendationOverlay(version.getStaleFlags()));
        assertTrue(staleInitialRecommendation(version.getStaleFlags()));
        assertTrue(staleOrderedPlan(version.getStaleFlags()));
        assertTrue(stalePlanAdjustment(version.getStaleFlags()));
        assertTrue(staleReview(version.getStaleFlags()));
        assertEquals("preference_intent_changed", version.getStaleFlags().getReasonCode());
    }

    @Test
    void shouldMarkConstraintIntentChangeStaleWithCandidatePool() {
        bindPlanningStateStore();
        PlanningStateDTO initial = planningStateService.getPlanningState(1L);
        initial.getStaleFlags().setCandidatePool(false);
        initial.getStaleFlags().setRecommendationOverlay(false);
        initial.getStaleFlags().setInitialRecommendation(false);
        initial.getStaleFlags().setOrderedPlan(false);
        initial.getStaleFlags().setPlanAdjustment(false);
        initial.getStaleFlags().setReview(false);
        saveStateToStore(1L, initial);

        MarkPlanningIntentStaleReq req = new MarkPlanningIntentStaleReq();
        req.setIntentMode("constraint");
        PlanningStateVersionDTO version = planningStateService.markIntentChangeStale(1L, req);

        assertEquals(Integer.valueOf(1), version.getVersion());
        assertTrue(staleCandidatePool(version.getStaleFlags()));
        assertTrue(staleRecommendationOverlay(version.getStaleFlags()));
        assertTrue(staleInitialRecommendation(version.getStaleFlags()));
        assertTrue(staleOrderedPlan(version.getStaleFlags()));
        assertTrue(stalePlanAdjustment(version.getStaleFlags()));
        assertTrue(staleReview(version.getStaleFlags()));
        assertEquals("constraint_intent_changed", version.getStaleFlags().getReasonCode());
    }

    @Test
    void shouldBackfillDataFreshnessSnapshotWithoutNotification() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId("v1");
        item.setPlanSchoolDataId("u1");
        item.setSchoolName("学校A");
        item.setMajorName("专业A");
        item.setTier("稳");
        initial.getCandidatePoolState().getItems().add(item);
        saveStateToStore(1L, initial);

        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, new DataFreshnessCheckReq());

        assertEquals("current", res.getDataFreshnessState().getStatusCode());
        assertEquals("none", res.getDataFreshnessState().getChangeLevel());
        assertFalse(Boolean.TRUE.equals(res.getDataFreshnessState().getShouldNotify()));
        assertNotNull(res.getDataFreshnessState().getDataHash());
        assertFalse(staleCandidatePool(res.getStaleFlags()));
        assertFalse(staleReview(res.getStaleFlags()));
    }

    @Test
    void shouldKeepPredictDataFreshnessStaticWhenFetchLatestRequested() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId("v1");
        item.setPlanSchoolDataId("u1");
        item.setSchoolName("学校A");
        item.setMajorName("专业A");
        item.setTier("稳");
        initial.getCandidatePoolState().getItems().add(item);
        initial.getDataFreshnessState().setPrepareType("PREDICT");
        initial.getDataFreshnessState().setStatusCode("current");
        saveStateToStore(1L, initial);

        PlanningDataFreshnessScheduleEntity schedule = new PlanningDataFreshnessScheduleEntity();
        schedule.setChatSessionId(1L);
        schedule.setPrepareType("PREDICT");
        schedule.setEnabled(false);
        when(planningDataFreshnessScheduleSharedService.saveOrUpdateSchedule(any(PlanningDataFreshnessScheduleEntity.class)))
                .thenReturn(schedule);
        when(planningDataFreshnessScheduleSharedService.getByChatSessionId(1L)).thenReturn(schedule);

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setFetchLatest(true);
        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, 1L, req);

        assertEquals("current", res.getDataFreshnessState().getStatusCode());
        assertEquals("none", res.getDataFreshnessState().getChangeLevel());
        assertEquals("PREDICT", res.getDataFreshnessState().getPrepareType());
        assertFalse(Boolean.TRUE.equals(res.getDataFreshnessState().getShouldNotify()));
        assertFalse(Boolean.TRUE.equals(res.getDataFreshnessState().getRequiresCandidateRefresh()));
        assertFalse(staleCandidatePool(res.getStaleFlags()));
        verify(volunteerSourceDataSyncService, never()).fetchLatestSourceData(any(), any(), anyBoolean());
        verify(volunteerBizService, never()).recommendVolunteerListWithSourceData(any(), any(), anyBoolean(), any());
    }

    @Test
    void shouldMarkPlanningStateStaleWhenVolunteerDataHashChanges() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId("v1");
        item.setPlanSchoolDataId("u1");
        item.setSchoolName("学校A");
        item.setMajorName("专业A");
        item.setTier("稳");
        initial.getCandidatePoolState().getItems().add(item);
        saveStateToStore(1L, initial);

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setDataHash("new-data-hash");
        req.setDataVersion("upstream-v2");
        req.setChangeLevel("major");
        req.setChangedCount(2);
        req.setAffectedVolunteerIds(java.util.Arrays.asList("v1"));
        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, req);

        assertEquals(Integer.valueOf(1), res.getVersion());
        assertEquals("changed", res.getDataFreshnessState().getStatusCode());
        assertEquals("major", res.getDataFreshnessState().getChangeLevel());
        assertEquals("new-data-hash", res.getDataFreshnessState().getLatestDataHash());
        assertTrue(Boolean.TRUE.equals(res.getDataFreshnessState().getShouldNotify()));
        assertTrue(Boolean.TRUE.equals(res.getDataFreshnessState().getRequiresCandidateRefresh()));
        assertTrue(Boolean.TRUE.equals(res.getDataFreshnessState().getRequiresReview()));
        assertTrue(staleCandidatePool(res.getStaleFlags()));
        assertTrue(staleReview(res.getStaleFlags()));
        assertEquals("volunteer_data_changed", res.getStaleFlags().getReasonCode());
    }

    @Test
    void shouldFetchLatestVolunteerDataAndSyncCandidateSnapshot() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId("school-1_major-1");
        item.setPlanSchoolDataId("school-1");
        item.setSchoolName("学校A");
        item.setMajorName("专业A");
        item.setTier("稳");
        item.setPlanNum(10);
        initial.getCandidatePoolState().getItems().add(item);
        saveStateToStore(1L, initial);

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setSourceDataHash("source-v2");
        snapshot.setVolunteerData(new com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO());
        when(volunteerSourceDataSyncService.fetchLatestSourceData(eq(1L), eq(1L), eq(false))).thenReturn(snapshot);
        when(volunteerBizService.recommendVolunteerListWithSourceData(eq(1L), eq(1L), eq(false), any()))
                .thenReturn(buildLatestVolunteerResponse("school-1", "major-1", "专业A", 12));

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setFetchLatest(true);
        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, 1L, req);
        PlanningStateDTO stored = planningStateService.getPlanningState(1L);

        assertEquals("changed", res.getDataFreshnessState().getStatusCode());
        assertEquals("minor", res.getDataFreshnessState().getChangeLevel());
        assertEquals(Integer.valueOf(1), res.getDataFreshnessState().getChangedCount());
        assertEquals(Integer.valueOf(1), res.getDataFreshnessState().getUpdatedCount());
        assertEquals("source-v2", res.getDataFreshnessState().getLatestDataVersion());
        assertTrue(Boolean.TRUE.equals(res.getDataFreshnessState().getRequiresCandidateRefresh()));
        assertFalse(Boolean.TRUE.equals(res.getDataFreshnessState().getRequiresReview()));
        assertFalse(staleCandidatePool(res.getStaleFlags()));
        assertFalse(staleRecommendationOverlay(res.getStaleFlags()));
        assertEquals(Integer.valueOf(12), stored.getCandidatePoolState().getItems().get(0).getPlanNum());
        assertEquals(res.getDataFreshnessState().getLatestDataHash(), stored.getDataFreshnessState().getDataHash());
    }

    @Test
    void shouldSyncLatestVolunteerDataIntoMajorGroupPlanAndCandidates() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        initial.getCandidatePoolState().setVolunteerModel(VolunteerModel.majorGroup.name());
        CandidateItemDTO removedBio = buildCandidateItem("north_bio", "north", "north-school", "中北大学（物化）", "稳", "生物工程", 55D, 80D, 55D, false);
        removedBio.setMajorId("bio");
        CandidateItemDTO removedShip = buildCandidateItem("north_ship", "north", "north-school", "中北大学（物化）", "稳", "船舶与海洋工程", 56D, 79D, 55D, false);
        removedShip.setMajorId("ship");
        CandidateItemDTO renamedLaw = buildCandidateItem("police_law", "police", "police-school", "海南警察学院（不限）", "保", "法学", 75D, 70D, 75D, false);
        renamedLaw.setMajorId("law");
        initial.getCandidatePoolState().getItems().add(removedBio);
        initial.getCandidatePoolState().getItems().add(removedShip);
        initial.getCandidatePoolState().getItems().add(renamedLaw);
        initial.getWorkingPlanState().getItems().add(buildDraftItem("north_bio", "中北大学（物化）", "生物工程", "稳"));
        initial.getWorkingPlanState().getItems().add(buildDraftItem("north_ship", "中北大学（物化）", "船舶与海洋工程", "稳"));
        initial.getWorkingPlanState().getItems().add(buildDraftItem("police_law", "海南警察学院（不限）", "法学", "保"));
        ReflectionTestUtils.invokeMethod(planningStateService, "syncWorkingPlanUnitsWithItems", initial.getWorkingPlanState(), initial.getCandidatePoolState().getItems(), initial.getCandidatePoolState());
        initial.getOrderedPlanState().getItems().add(buildOrderedItem("north_bio", "中北大学（物化）", "生物工程", "稳", 1));
        initial.getOrderedPlanState().getItems().add(buildOrderedItem("north_ship", "中北大学（物化）", "船舶与海洋工程", "稳", 2));
        initial.getOrderedPlanState().getItems().add(buildOrderedItem("police_law", "海南警察学院（不限）", "法学", "保", 3));
        initial.getOrderedPlanState().setUnits(ReflectionTestUtils.invokeMethod(planningStateService,
                "buildOrderedUnitsFromOrderedItems", initial.getOrderedPlanState().getItems(), initial.getWorkingPlanState(), initial.getCandidatePoolState().getItems()));
        saveStateToStore(1L, initial);

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setSourceDataHash("source-major-group-v2");
        snapshot.setVolunteerData(new com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO());
        when(volunteerSourceDataSyncService.fetchLatestSourceData(eq(1L), eq(1L), eq(false))).thenReturn(snapshot);
        when(volunteerBizService.recommendVolunteerListWithSourceData(eq(1L), eq(1L), eq(false), any()))
                .thenReturn(buildMajorGroupFreshnessResponse());

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setFetchLatest(true);
        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, 1L, req);
        PlanningStateDTO stored = planningStateService.getPlanningState(1L);

        assertEquals("changed", res.getDataFreshnessState().getStatusCode());
        assertEquals(Integer.valueOf(4), res.getDataFreshnessState().getChangedCount());
        assertEquals(Integer.valueOf(1), res.getDataFreshnessState().getAddedCount());
        assertEquals(Integer.valueOf(1), res.getDataFreshnessState().getUpdatedCount());
        assertEquals(Integer.valueOf(2), res.getDataFreshnessState().getRemovedCount());
        assertTrue(Boolean.TRUE.equals(res.getDataFreshnessState().getRequiresReview()));
        assertTrue(staleReview(res.getStaleFlags()));
        assertFalse(staleCandidatePool(res.getStaleFlags()));
        assertEquals(2, stored.getCandidatePoolState().getItems().size());
        assertTrue(stored.getCandidatePoolState().getItems().stream().anyMatch(item -> "police_law".equals(item.getVolunteerId()) && "法学（改）".equals(item.getMajorName())));
        assertTrue(stored.getCandidatePoolState().getItems().stream().anyMatch(item -> "luosang_tourism".equals(item.getVolunteerId())));
        assertFalse(stored.getWorkingPlanState().getItems().stream().anyMatch(item -> item.getVolunteerId().startsWith("north_")));
        assertEquals(1, stored.getWorkingPlanState().getItems().size());
        assertEquals("法学（改）", stored.getWorkingPlanState().getItems().get(0).getMajorName());
        assertFalse(stored.getOrderedPlanState().getItems().stream().anyMatch(item -> item.getVolunteerId().startsWith("north_")));
        assertEquals(1, stored.getOrderedPlanState().getItems().size());
        assertEquals("法学（改）", stored.getOrderedPlanState().getItems().get(0).getMajorName());
        assertEquals(1, stored.getOrderedPlanState().getUnits().size());
        assertEquals("法学（改）", stored.getOrderedPlanState().getUnits().get(0).getMajorItems().get(0).getMajorName());
    }

    @Test
    void shouldSyncSamePendingFreshnessChangeOnceLatestSnapshotIsAvailable() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        CandidateItemDTO stale = new CandidateItemDTO();
        stale.setVolunteerId("school-1_major-1");
        stale.setPlanSchoolDataId("school-1");
        stale.setSchoolName("学校A");
        stale.setMajorName("专业A");
        stale.setTier("稳");
        stale.setPlanNum(10);
        initial.getCandidatePoolState().getItems().add(stale);
        initial.getWorkingPlanState().getItems().add(buildDraftItem("school-1_major-1", "学校A", "专业A", "稳"));
        initial.getOrderedPlanState().getItems().add(buildOrderedItem("school-1_major-1", "学校A", "专业A", "稳", 1));
        initial.getDataFreshnessState().setStatusCode("changed");
        initial.getDataFreshnessState().setChangeLevel("minor");
        initial.getDataFreshnessState().setShouldNotify(true);
        initial.getDataFreshnessState().setRequiresCandidateRefresh(true);
        initial.getDataFreshnessState().setLatestSourceDataHash("source-v2");
        initial.getDataFreshnessState().setLatestDataHash("pending-hash");
        initial.getDataFreshnessState().setSummary("招生计划数据已变化：更新 1 项。");
        initial.getDataFreshnessState().setChangedCount(1);
        initial.getDataFreshnessState().setUpdatedCount(1);
        saveStateToStore(1L, initial);

        VolunteerRecommendListResponse latest = buildLatestVolunteerResponse("school-1", "major-1", "专业A（改）", 12);
        CandidatePoolStateDTO latestPool = ReflectionTestUtils.invokeMethod(
                planningStateService, "buildCandidatePoolStateFromResponse", 1L, initial, latest);
        String latestHash = ReflectionTestUtils.invokeMethod(planningStateService, "buildCandidateDataHash", latestPool);
        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setSourceDataHash("source-v2");
        snapshot.setVolunteerData(new com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO());
        when(volunteerSourceDataSyncService.fetchLatestSourceData(eq(1L), eq(1L), eq(false))).thenReturn(snapshot);
        when(volunteerBizService.recommendVolunteerListWithSourceData(eq(1L), eq(1L), eq(false), any()))
                .thenReturn(latest);
        initial.getDataFreshnessState().setLatestDataHash(latestHash);
        saveStateToStore(1L, initial);

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setFetchLatest(true);
        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, 1L, req);
        PlanningStateDTO stored = planningStateService.getPlanningState(1L);

        assertEquals("changed", res.getDataFreshnessState().getStatusCode());
        assertEquals("专业A（改）", stored.getCandidatePoolState().getItems().get(0).getMajorName());
        assertEquals("专业A（改）", stored.getWorkingPlanState().getItems().get(0).getMajorName());
        assertEquals("专业A（改）", stored.getOrderedPlanState().getItems().get(0).getMajorName());
        assertEquals(latestHash, stored.getDataFreshnessState().getDataHash());
    }

    @Test
    void shouldSyncPlanDetailsEvenWhenLatestCandidateHashIsAlreadyCurrent() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        initial.getCandidatePoolState().setVolunteerModel(VolunteerModel.majorGroup.name());

        VolunteerRecommendListResponse latest = buildMajorGroupFreshnessResponse();
        CandidatePoolStateDTO latestPool = ReflectionTestUtils.invokeMethod(
                planningStateService, "buildCandidatePoolStateFromResponse", 1L, initial, latest);
        String latestHash = ReflectionTestUtils.invokeMethod(planningStateService, "buildCandidateDataHash", latestPool);
        initial.setCandidatePoolState(latestPool);
        initial.getDataFreshnessState().setStatusCode("current");
        initial.getDataFreshnessState().setDataHash(latestHash);
        initial.getDataFreshnessState().setLatestDataHash(latestHash);
        initial.getDataFreshnessState().setSourceDataHash("source-major-group-v2");
        initial.getDataFreshnessState().setLatestSourceDataHash("source-major-group-v2");
        initial.getWorkingPlanState().getItems().add(buildDraftItem("north_bio", "中北大学（物化）", "生物工程", "稳"));
        initial.getWorkingPlanState().getItems().add(buildDraftItem("north_ship", "中北大学（物化）", "船舶与海洋工程", "稳"));
        initial.getWorkingPlanState().getItems().add(buildDraftItem("police_law", "海南警察学院（不限）", "法学", "保"));
        ReflectionTestUtils.invokeMethod(planningStateService, "syncWorkingPlanUnitsWithItems",
                initial.getWorkingPlanState(), initial.getCandidatePoolState().getItems(), initial.getCandidatePoolState());
        initial.getOrderedPlanState().getItems().add(buildOrderedItem("north_bio", "中北大学（物化）", "生物工程", "稳", 1));
        initial.getOrderedPlanState().getItems().add(buildOrderedItem("north_ship", "中北大学（物化）", "船舶与海洋工程", "稳", 2));
        initial.getOrderedPlanState().getItems().add(buildOrderedItem("police_law", "海南警察学院（不限）", "法学", "保", 3));
        initial.getOrderedPlanState().setUnits(ReflectionTestUtils.invokeMethod(planningStateService,
                "buildOrderedUnitsFromOrderedItems", initial.getOrderedPlanState().getItems(),
                initial.getWorkingPlanState(), initial.getCandidatePoolState().getItems()));
        saveStateToStore(1L, initial);

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setSourceDataHash("source-major-group-v2");
        snapshot.setVolunteerData(new com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO());
        when(volunteerSourceDataSyncService.fetchLatestSourceData(eq(1L), eq(1L), eq(false))).thenReturn(snapshot);
        when(volunteerBizService.recommendVolunteerListWithSourceData(eq(1L), eq(1L), eq(false), any()))
                .thenReturn(latest);

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setFetchLatest(true);
        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, 1L, req);
        PlanningStateDTO stored = planningStateService.getPlanningState(1L);

        assertEquals("current", res.getDataFreshnessState().getStatusCode());
        assertFalse(Boolean.TRUE.equals(res.getDataFreshnessState().getShouldNotify()));
        assertFalse(Boolean.TRUE.equals(res.getDataFreshnessState().getRequiresCandidateRefresh()));
        assertFalse(stored.getWorkingPlanState().getItems().stream().anyMatch(item -> item.getVolunteerId().startsWith("north_")));
        assertEquals(1, stored.getWorkingPlanState().getItems().size());
        assertEquals("法学（改）", stored.getWorkingPlanState().getItems().get(0).getMajorName());
        assertFalse(stored.getOrderedPlanState().getItems().stream().anyMatch(item -> item.getVolunteerId().startsWith("north_")));
        assertEquals(1, stored.getOrderedPlanState().getItems().size());
        assertEquals("法学（改）", stored.getOrderedPlanState().getItems().get(0).getMajorName());
        assertEquals(1, stored.getOrderedPlanState().getUnits().size());
        assertEquals("法学（改）", stored.getOrderedPlanState().getUnits().get(0).getMajorItems().get(0).getMajorName());
    }

    @Test
    void shouldDetectSchoolAttributeChangesInVolunteerDataHash() {
        bindPlanningStateStore();
        PlanningStateDTO initial = new PlanningStateDTO();
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId("school-1_major-1");
        item.setPlanSchoolDataId("school-1");
        item.setSchoolId("school-1");
        item.setSchoolName("学校A");
        item.setSchoolRank(80);
        item.setSchoolNature("民办");
        item.setSchoolLevel("普通本科");
        item.setBaoyanRatio(0.05D);
        item.setMasterCount(12);
        item.setDoctorCount(3);
        item.setMajorId("major-1");
        item.setMajorName("专业A");
        item.setTier("稳");
        item.setPlanNum(10);
        item.setAdmissionRatio(80D);
        initial.getCandidatePoolState().getItems().add(item);
        saveStateToStore(1L, initial);

        VolunteerRecommendListResponse latest = buildLatestVolunteerResponse("school-1", "major-1", "专业A", 10);
        latest.getSafes().get(0).setSchool_rank(60);
        latest.getSafes().get(0).setSchool_nature("公办");
        latest.getSafes().get(0).setSchool_level("省重点");
        latest.getSafes().get(0).setBaoyan_ratio(0.12D);
        latest.getSafes().get(0).setMaster_count(20);
        latest.getSafes().get(0).setDoctor_count(8);

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setSourceDataHash("source-school-attrs-v2");
        snapshot.setVolunteerData(new com.ytell.zhiyuan.model.dto.inner.VolunteerDataDTO());
        when(volunteerSourceDataSyncService.fetchLatestSourceData(eq(1L), eq(1L), eq(false))).thenReturn(snapshot);
        when(volunteerBizService.recommendVolunteerListWithSourceData(eq(1L), eq(1L), eq(false), any()))
                .thenReturn(latest);

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setFetchLatest(true);
        DataFreshnessCheckRes res = planningStateService.checkDataFreshness(1L, 1L, req);
        PlanningStateDTO stored = planningStateService.getPlanningState(1L);

        assertEquals("changed", res.getDataFreshnessState().getStatusCode());
        assertEquals(Integer.valueOf(1), res.getDataFreshnessState().getUpdatedCount());
        assertTrue(res.getDataFreshnessState().getAffectedVolunteerIds().contains("school-1_major-1"));
        assertFalse(staleCandidatePool(res.getStaleFlags()));
        assertEquals(Integer.valueOf(60), stored.getCandidatePoolState().getItems().get(0).getSchoolRank());
        assertEquals("公办", stored.getCandidatePoolState().getItems().get(0).getSchoolNature());
        assertEquals("省重点", stored.getCandidatePoolState().getItems().get(0).getSchoolLevel());
        assertEquals(Double.valueOf(0.12D), stored.getCandidatePoolState().getItems().get(0).getBaoyanRatio());
        assertEquals(Integer.valueOf(20), stored.getCandidatePoolState().getItems().get(0).getMasterCount());
        assertEquals(Integer.valueOf(8), stored.getCandidatePoolState().getItems().get(0).getDoctorCount());
    }


    @Test
    void shouldNotImportLegacyPlanWhenCheckingDataFreshnessForPredictSession() {
        CreateSessionReq scoreDetail = buildScoreDetail();
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode("PREDICT");
        prepareType.setDesc("模拟填报");
        scoreDetail.setPrepareType(prepareType);
        ChatSessionExtraData scoreData = new ChatSessionExtraData();
        scoreData.setChatSessionId(1L);
        scoreData.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        scoreData.setDataValue(JSONObject.toJSONString(scoreDetail));
        when(chatSessionSharedService.getById(1L)).thenReturn(ChatSession.builder()
                .id(1L)
                .tenantId(1L)
                .sessionStatus(SessionStatus.GOING)
                .createTime(new Date())
                .build());
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.USER_SCORE_KEY)))
                .thenReturn(scoreData);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);
        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(1, 1, 0, 0));
        legacy.setUserScoreDetail(scoreDetail);
        legacy.setSprints(java.util.Arrays.asList(buildSchool(
                "ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "50"))));
        when(volunteerBizService.loadOriginalVolunteerData(1L)).thenReturn(legacy);

        DataFreshnessCheckReq req = new DataFreshnessCheckReq();
        req.setFetchLatest(true);
        DataFreshnessCheckRes checkRes = planningStateService.checkDataFreshness(1L, 1L, req);
        DataFreshnessStateDTO stateRes = planningStateService.getDataFreshnessState(1L, 1L);

        assertEquals("PREDICT", checkRes.getDataFreshnessState().getPrepareType());
        assertEquals("PREDICT", stateRes.getPrepareType());
        verify(volunteerSourceDataSyncService, never()).fetchLatestSourceData(any(), any(), anyBoolean());
        verify(volunteerBizService, never()).loadFinalSubmitVolunteerData(1L);
        verify(volunteerBizService, never()).loadCachedRecommendData(1L);
        verify(volunteerBizService, never()).loadOriginalVolunteerData(1L);
        verify(chatSessionExtraDataSharedService, never()).save(any(ChatSessionExtraData.class));
        verify(chatSessionExtraDataSharedService, never()).updateById(any(ChatSessionExtraData.class));
    }

    @Test
    void shouldNotDowngradeDetailedDataFreshnessChangeWhenMergingScheduleState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.getDataFreshnessState().setStatusCode("changed");
        state.getDataFreshnessState().setChangeLevel("medium");
        state.getDataFreshnessState().setShouldNotify(true);
        state.getDataFreshnessState().setRequiresCandidateRefresh(true);
        state.getDataFreshnessState().setRequiresReview(true);
        state.getDataFreshnessState().setSummary("候选级影响分析：中等变化");
        state.getDataFreshnessState().setChangedCount(12);
        state.getDataFreshnessState().setUpdatedCount(9);
        state.getDataFreshnessState().setLatestDataHash("candidate-hash-v2");

        PlanningDataFreshnessScheduleEntity schedule = new PlanningDataFreshnessScheduleEntity();
        schedule.setChatSessionId(1L);
        schedule.setLastCheckStatus("changed");
        schedule.setLatestSourceDataHash("source-hash-v2");
        schedule.setCheckIntervalMinutes(120);
        when(planningDataFreshnessScheduleSharedService.getByChatSessionId(1L)).thenReturn(schedule);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(1L, state);

        assertEquals("changed", workspaceState.getDataFreshnessState().getStatusCode());
        assertEquals("medium", workspaceState.getDataFreshnessState().getChangeLevel());
        assertTrue(Boolean.TRUE.equals(workspaceState.getDataFreshnessState().getRequiresReview()));
        assertEquals(Integer.valueOf(12), workspaceState.getDataFreshnessState().getChangedCount());
        assertEquals(Integer.valueOf(9), workspaceState.getDataFreshnessState().getUpdatedCount());
        assertEquals("候选级影响分析：中等变化", workspaceState.getDataFreshnessState().getSummary());
        assertEquals("source-hash-v2", workspaceState.getDataFreshnessState().getLatestSourceDataHash());
    }

    @Test
    void shouldImportSubmittedLegacyPlanWhenPlanningStateMissing() {
        bindPlanningStateStore();
        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(3, 1, 1, 1));
        legacy.setUserScoreDetail(buildScoreDetail());
        VolunteerRecommendListResponse.VolunteerSchool sprint = buildSchool(
                "ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "18"));
        sprint.setIs_preferred(true);
        VolunteerRecommendListResponse.VolunteerSchool safe = buildSchool(
                "ps2", "s2", "学校B", "天津", 1, buildMajorWithRatio("m2", "专业B", "52"));
        safe.setIs_preferred(false);
        VolunteerRecommendListResponse.VolunteerSchool protect = buildSchool(
                "ps3", "s3", "学校C", "河北", 1, buildMajorWithRatio("m3", "专业C", "82"));
        protect.setIs_preferred(true);
        legacy.setSprints(java.util.Arrays.asList(sprint));
        legacy.setSafes(java.util.Arrays.asList(safe));
        legacy.setProtects(java.util.Arrays.asList(protect));
        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals("ordered", state.getPhase());
        assertEquals(3, state.getCandidatePoolState().getItems().size());
        assertEquals(2, state.getDraftPlanState().getItems().size());
        assertEquals(2, state.getOrderedPlanState().getItems().size());
        assertEquals("legacy_submitted", state.getOrderedPlanState().getGenerationMode());
        assertTrue(state.getOrderedPlanState().getItems().stream().allMatch(item -> Boolean.TRUE.equals(item.getLocked())));
        assertTrue(state.getOrderedPlanState().getItems().stream().allMatch(item -> Boolean.TRUE.equals(item.getPinned())));
        assertEquals(Integer.valueOf(1), state.getOrderedPlanState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), state.getOrderedPlanState().getSummary().getTierCounts().get("保"));
        assertTrue(state.getOperationLogs().stream().anyMatch(log -> "legacy_plan_import".equals(log.getType())));
        verify(volunteerBizService, never()).loadCachedRecommendData(1L);
        verify(chatSessionExtraDataSharedService, times(1)).save(any(ChatSessionExtraData.class));
    }

    @Test
    void shouldFallbackToTempLegacyPlanWhenSubmittedPlanUnavailable() {
        bindPlanningStateStore();
        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(2, 1, 1, 0));
        VolunteerRecommendListResponse.VolunteerSchool sprint = buildSchool(
                "ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "18"));
        sprint.setIs_preferred(true);
        VolunteerRecommendListResponse.VolunteerSchool safe = buildSchool(
                "ps2", "s2", "学校B", "天津", 1, buildMajorWithRatio("m2", "专业B", "52"));
        safe.setIs_preferred(true);
        legacy.setSprints(java.util.Arrays.asList(sprint));
        legacy.setSafes(java.util.Arrays.asList(safe));
        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenThrow(new RuntimeException("missing final"));
        when(volunteerBizService.loadCachedRecommendData(1L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals("ordered", state.getPhase());
        assertEquals("legacy_import", state.getOrderedPlanState().getGenerationMode());
        assertEquals(2, state.getOrderedPlanState().getItems().size());
        assertTrue(state.getOrderedPlanState().getItems().stream().noneMatch(item -> Boolean.TRUE.equals(item.getLocked())));
        assertTrue(state.getOrderedPlanState().getItems().stream().noneMatch(item -> Boolean.TRUE.equals(item.getPinned())));
        verify(chatSessionExtraDataSharedService, times(1)).save(any(ChatSessionExtraData.class));
    }

    @Test
    void shouldNotTreatOriginalLegacyFullDataAsSubmittedPlan() throws Exception {
        bindPlanningStateStore();
        VolunteerBizService parser = new VolunteerBizService();
        VolunteerRecommendListResponse original = parser.parseVolunteerRecommendListResponse(
                new String(Files.readAllBytes(Paths.get("data/tmp/session_volunteer_23.json")), StandardCharsets.UTF_8));

        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenThrow(new RuntimeException("missing final"));
        when(volunteerBizService.loadCachedRecommendData(1L)).thenThrow(new RuntimeException("missing temp"));
        when(volunteerBizService.loadOriginalVolunteerData(1L)).thenReturn(original);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals("legacy_import", state.getOrderedPlanState().getGenerationMode());
        assertEquals(441, state.getCandidatePoolState().getItems().size());
        assertEquals(0, state.getOrderedPlanState().getItems().size());
        assertTrue(state.getOrderedPlanState().getItems().stream().noneMatch(item -> Boolean.TRUE.equals(item.getLocked())));
        assertTrue(state.getOrderedPlanState().getItems().stream().noneMatch(item -> Boolean.TRUE.equals(item.getPinned())));
        verify(chatSessionExtraDataSharedService, times(1)).save(any(ChatSessionExtraData.class));
    }

    @Test
    void shouldImportMajorModeTempPlanByMajorEntries() {
        bindPlanningStateStore();
        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(3, 2, 1, 0));
        legacy.getBaseData().setVolunteerModel(VolunteerModel.major);

        VolunteerRecommendListResponse.VolunteerSchool sprintA = buildSchool(
                "ps1", "s1", "学校A", "北京", 1,
                buildMajorWithRatio("m1", "专业A", "18"));
        sprintA.setIs_preferred(true);
        VolunteerRecommendListResponse.VolunteerSchool sprintB = buildSchool(
                "ps2", "s2", "学校B", "北京", 2,
                buildMajorWithRatio("m2", "专业B", "22"));
        sprintB.setIs_preferred(true);
        VolunteerRecommendListResponse.VolunteerSchool safe = buildSchool(
                "ps3", "s3", "学校C", "天津", 1,
                buildMajorWithRatio("m3", "专业C", "52"));
        safe.setIs_preferred(true);
        legacy.setSprints(java.util.Arrays.asList(sprintA, sprintB));
        legacy.setSafes(java.util.Arrays.asList(safe));

        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenThrow(new RuntimeException("missing final"));
        when(volunteerBizService.loadCachedRecommendData(1L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals("major", state.getCandidatePoolState().getVolunteerModel());
        assertEquals(3, state.getOrderedPlanState().getItems().size());
        assertEquals(3, state.getOrderedPlanState().getSummary().getTotal());
        assertEquals(2, state.getOrderedPlanState().getSummary().getTierCounts().get("冲"));
        assertEquals(1, state.getOrderedPlanState().getSummary().getTierCounts().get("稳"));
        assertEquals(3, state.getOrderedPlanState().getUnits().size());
        assertEquals("legacy_import", state.getOrderedPlanState().getGenerationMode());
    }

    @Test
    void shouldImportMajorGroupTempPlanBySchoolUnits() {
        bindPlanningStateStore();
        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(2, 1, 1, 0));
        legacy.getBaseData().setVolunteerModel(VolunteerModel.majorGroup);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(2);
        volunteerCount.setMajorCount(2);
        legacy.getBaseData().setVolunteerCount(volunteerCount);

        VolunteerRecommendListResponse.VolunteerSchool sprint = buildSchool(
                "ps1", "s1", "学校A第01组", "北京", 1,
                buildMajorWithRatio("m1", "专业A", "18"));
        VolunteerRecommendListResponse.VolunteerMajor majorA = buildMajorWithRatio("m1", "专业A", "18");
        VolunteerRecommendListResponse.VolunteerMajor majorB = buildMajorWithRatio("m2", "专业B", "22");
        VolunteerRecommendListResponse.VolunteerMajor majorC = buildMajorWithRatio("m3", "专业C", "25");
        majorA.setPlanMajorDataId(null);
        majorB.setPlanMajorDataId(null);
        majorC.setPlanMajorDataId(null);
        sprint.setMajors(java.util.Arrays.asList(majorA, majorB, majorC));
        sprint.setIs_preferred(true);
        VolunteerRecommendListResponse.VolunteerSchool safe = buildSchool(
                "ps2", "s2", "学校B第01组", "天津", 1,
                buildMajorWithRatio("m4", "专业D", "52"));
        VolunteerRecommendListResponse.VolunteerMajor majorD = buildMajorWithRatio("m4", "专业D", "52");
        VolunteerRecommendListResponse.VolunteerMajor majorE = buildMajorWithRatio("m5", "专业E", "58");
        majorD.setPlanMajorDataId(null);
        majorE.setPlanMajorDataId(null);
        safe.setMajors(java.util.Arrays.asList(majorD, majorE));
        safe.setIs_preferred(true);
        legacy.setSprints(java.util.Arrays.asList(sprint));
        legacy.setSafes(java.util.Arrays.asList(safe));

        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenThrow(new RuntimeException("missing final"));
        when(volunteerBizService.loadCachedRecommendData(1L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals("majorGroup", state.getCandidatePoolState().getVolunteerModel());
        assertEquals(5, state.getCandidatePoolState().getItems().size());
        assertEquals(5, state.getDraftPlanState().getItems().size());
        assertEquals(5, state.getOrderedPlanState().getItems().size());
        assertEquals(5, state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .distinct()
                .count());
        assertEquals(2, state.getOrderedPlanState().getSummary().getTotal());
        assertEquals(1, state.getOrderedPlanState().getSummary().getTierCounts().get("冲"));
        assertEquals(1, state.getOrderedPlanState().getSummary().getTierCounts().get("稳"));
        assertEquals(2, state.getOrderedPlanState().getUnits().size());
        assertTrue(state.getOrderedPlanState().getUnits().stream()
                .allMatch(unit -> unit.getMajorItems() != null && !unit.getMajorItems().isEmpty()));
        Map<String, OrderedUnitDTO> orderedUnitMap = state.getOrderedPlanState().getUnits().stream()
                .collect(Collectors.toMap(OrderedUnitDTO::getUnitId, unit -> unit));
        assertEquals(3, orderedUnitMap.get("ps1").getMajorItems().size());
        assertEquals(2, orderedUnitMap.get("ps2").getMajorItems().size());
        assertTrue(orderedUnitMap.get("ps1").getMajorItems().stream()
                .map(PlanningUnitMajorDTO::getMajorName)
                .collect(Collectors.toSet())
                .containsAll(java.util.Arrays.asList("专业A", "专业B", "专业C")));
        assertEquals("legacy_import", state.getOrderedPlanState().getGenerationMode());
    }

    @Test
    void shouldPreserveLegacyMajorGroupMajorsForExternalSession941() throws Exception {
        String sampleDir = System.getProperty("legacy.sample.dir", System.getenv("LEGACY_SAMPLE_DIR"));
        Assumptions.assumeTrue(sampleDir != null && !sampleDir.trim().isEmpty(), "legacy sample dir not configured");
        Path sampleFile = Paths.get(sampleDir, "session_volunteer_941_temp.json");
        Assumptions.assumeTrue(Files.exists(sampleFile), "legacy 941 temp sample not found: " + sampleFile);

        bindPlanningStateStore(941L);
        VolunteerBizService parser = new VolunteerBizService();
        VolunteerRecommendListResponse legacy = parser.parseVolunteerRecommendListResponse(
                new String(Files.readAllBytes(sampleFile), StandardCharsets.UTF_8));

        when(volunteerBizService.loadFinalSubmitVolunteerData(941L)).thenThrow(new RuntimeException("missing final"));
        when(volunteerBizService.loadCachedRecommendData(941L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(941L);

        assertEquals("majorGroup", state.getCandidatePoolState().getVolunteerModel());
        assertEquals(40, state.getOrderedPlanState().getUnits().size());
        assertTrue(state.getOrderedPlanState().getItems().size() > state.getOrderedPlanState().getUnits().size());
        assertEquals(state.getOrderedPlanState().getItems().size(), state.getDraftPlanState().getItems().size());
        assertEquals(state.getOrderedPlanState().getItems().size(), state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .distinct()
                .count());
        OrderedUnitDTO unit = state.getOrderedPlanState().getUnits().stream()
                .filter(item -> "53020261003178".equals(item.getUnitId()))
                .findFirst()
                .orElse(null);
        assertNotNull(unit);
        assertEquals(2, unit.getMajorItems().size());
        assertTrue(unit.getMajorItems().stream()
                .map(PlanningUnitMajorDTO::getMajorName)
                .collect(Collectors.toSet())
                .containsAll(java.util.Arrays.asList("计算机科学与技术(校本部)", "网络空间安全(校本部)")));
        assertTrue(unit.getMajorItems().stream()
                .map(PlanningUnitMajorDTO::getVolunteerId)
                .collect(Collectors.toSet())
                .containsAll(java.util.Arrays.asList("53020261003178_574", "53020261003178_584")));

        OrderedPlanSortReq sortReq = new OrderedPlanSortReq();
        sortReq.setSortField("admissionRatio");
        PlanningStateDTO sorted = planningStateService.sortOrderedPlan(941L, sortReq);
        assertEquals(40, sorted.getOrderedPlanState().getUnits().size());
        OrderedUnitDTO sortedUnit = sorted.getOrderedPlanState().getUnits().stream()
                .filter(item -> "53020261003178".equals(item.getUnitId()))
                .findFirst()
                .orElse(null);
        assertNotNull(sortedUnit);
        assertEquals(2, sortedUnit.getMajorItems().size());

        DraftRemoveReq removeReq = new DraftRemoveReq();
        removeReq.setVolunteerIds(java.util.Arrays.asList("53020261003178_574"));
        PlanningStateDTO removed = planningStateService.removeDraftItems(941L, removeReq);
        assertEquals(sorted.getOrderedPlanState().getItems().size() - 1, removed.getOrderedPlanState().getItems().size());
        OrderedUnitDTO removedUnit = removed.getOrderedPlanState().getUnits().stream()
                .filter(item -> "53020261003178".equals(item.getUnitId()))
                .findFirst()
                .orElse(null);
        assertNotNull(removedUnit);
        assertEquals(1, removedUnit.getMajorItems().size());
        assertEquals("53020261003178_584", removedUnit.getMajorItems().get(0).getVolunteerId());

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 941L, analyzeReq);
        assertNotNull(adjustmentState.getAnalysis());
        assertNotNull(adjustmentState.getAnalysis().getRules());
        assertFalse(adjustmentState.getAnalysis().getRules().isEmpty());
    }

    @Test
    void shouldSelectLegacyPlanByTierTargetsWhenPreferredFlagMissing() {
        bindPlanningStateStore();
        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(3, 1, 1, 1));
        legacy.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "18")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "22"))));
        legacy.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "稳A", "天津", 1, buildMajorWithRatio("m3", "专业C", "52"))));
        legacy.setProtects(java.util.Arrays.asList(
                buildSchool("ps4", "s4", "保A", "河北", 1, buildMajorWithRatio("m4", "专业D", "82"))));
        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals(4, state.getCandidatePoolState().getItems().size());
        assertEquals(3, state.getDraftPlanState().getItems().size());
        assertEquals(3, state.getOrderedPlanState().getItems().size());
        assertEquals(java.util.Arrays.asList("ps1_m1", "ps3_m3", "ps4_m4"),
                state.getOrderedPlanState().getItems().stream()
                        .map(OrderedItemDTO::getVolunteerId)
                        .collect(Collectors.toList()));
    }

    @Test
    void shouldNotImportLegacyPlanWhenPlanningStateExists() {
        PlanningStateDTO existing = new PlanningStateDTO();
        existing.setSessionId(1L);
        existing.setPhase("candidate_generated");
        ChatSessionExtraData extraData = new ChatSessionExtraData();
        extraData.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        extraData.setDataValue(com.alibaba.fastjson.JSONObject.toJSONString(existing));
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(1L, ChatSessionExtraDataConstants.PLANNING_STATE_KEY))
                .thenReturn(extraData);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals("candidate_generated", state.getPhase());
        verify(volunteerBizService, never()).loadFinalSubmitVolunteerData(1L);
        verify(volunteerBizService, never()).loadCachedRecommendData(1L);
        verify(chatSessionExtraDataSharedService, never()).save(any(ChatSessionExtraData.class));
    }

    @Test
    void shouldRecordPlanEditCacheNoticeWithoutApplyingItToLegacyPlan() {
        bindPlanningStateStore();
        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(1, 1, 0, 0));
        VolunteerRecommendListResponse.VolunteerSchool sprint = buildSchool(
                "ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "18"));
        sprint.setIs_preferred(true);
        legacy.setSprints(java.util.Arrays.asList(sprint));

        ChatSessionExtraData planEditCache = new ChatSessionExtraData();
        planEditCache.setDataKey(ChatSessionExtraDataConstants.PLAN_EDIT_CACHE_KEY);
        planEditCache.setDataValue("{\"preferredRegions\":[\"上海\"]}");
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(1L, ChatSessionExtraDataConstants.PLAN_EDIT_CACHE_KEY))
                .thenReturn(planEditCache);
        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals(1, state.getOrderedPlanState().getItems().size());
        assertEquals("ps1_m1", state.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertTrue(state.getOperationLogs().stream()
                .anyMatch(log -> "legacy_plan_edit_cache_pending".equals(log.getType())));
        verify(chatSessionExtraDataSharedService, times(1)).save(any(ChatSessionExtraData.class));
        verify(chatSessionExtraDataSharedService, times(1)).updateById(any(ChatSessionExtraData.class));
    }

    @Test
    void shouldImportTrackedLegacyCompleteDataFiles() throws Exception {
        VolunteerBizService parser = new VolunteerBizService();
        for (Long sessionId : java.util.Arrays.asList(26L, 29L, 35L)) {
            Path path = Paths.get("data/tmp/session_volunteer_" + sessionId + ".json");
            VolunteerRecommendListResponse legacy = parser.parseVolunteerRecommendListResponse(
                    new String(Files.readAllBytes(path), StandardCharsets.UTF_8));
            assertEquals(0, countLegacyPreferredEntries(legacy));
            assertLegacyOriginalImportMatchesSource(sessionId, legacy);
        }
    }

    @Test
    void shouldImportExternalLegacyCompleteDataSamples() throws Exception {
        String sampleDir = System.getProperty("legacy.sample.dir", System.getenv("LEGACY_SAMPLE_DIR"));
        Assumptions.assumeTrue(sampleDir != null && !sampleDir.trim().isEmpty(), "legacy sample dir not configured");
        Path dir = Paths.get(sampleDir);
        Assumptions.assumeTrue(Files.isDirectory(dir), "legacy sample dir not found: " + sampleDir);

        VolunteerBizService parser = new VolunteerBizService();
        List<Path> sampleFiles = Files.list(dir)
                .filter(path -> path.getFileName().toString().matches("session_volunteer_\\d+(_final|_temp)?\\.json"))
                .sorted()
                .collect(Collectors.toList());
        Assumptions.assumeFalse(sampleFiles.isEmpty(), "legacy sample dir has no volunteer json files");

        for (Path sampleFile : sampleFiles) {
            Long sessionId = extractSessionId(sampleFile);
            VolunteerRecommendListResponse legacy = parser.parseVolunteerRecommendListResponse(
                    new String(Files.readAllBytes(sampleFile), StandardCharsets.UTF_8));
            if (countLegacyRecommendEntries(legacy) == 0) {
                continue;
            }
            String fileName = sampleFile.getFileName().toString();
            if (fileName.contains("_final")) {
                assertLegacyImportMatchesSource(sessionId, legacy, true, false);
            } else if (fileName.contains("_temp")) {
                assertLegacyImportMatchesSource(sessionId, legacy, false, false);
            } else {
                assertLegacyOriginalImportMatchesSource(sessionId, legacy);
            }
        }
    }

    @Test
    void shouldPreferFinalOverTempAndOriginalForExternalLegacySessionSamples() throws Exception {
        String sampleDir = System.getProperty("legacy.sample.dir", System.getenv("LEGACY_SAMPLE_DIR"));
        Assumptions.assumeTrue(sampleDir != null && !sampleDir.trim().isEmpty(), "legacy sample dir not configured");
        Path dir = Paths.get(sampleDir);
        Assumptions.assumeTrue(Files.isDirectory(dir), "legacy sample dir not found: " + sampleDir);

        VolunteerBizService parser = new VolunteerBizService();
        List<Long> completeSessionIds = Files.list(dir)
                .filter(path -> path.getFileName().toString().matches("session_volunteer_\\d+\\.json"))
                .map(this::extractSessionId)
                .filter(sessionId -> Files.exists(dir.resolve("session_volunteer_" + sessionId + "_temp.json"))
                        && Files.exists(dir.resolve("session_volunteer_" + sessionId + "_final.json")))
                .sorted()
                .collect(Collectors.toList());
        Assumptions.assumeFalse(completeSessionIds.isEmpty(), "legacy sample dir has no complete original/temp/final session groups");

        boolean hasMajorMode = false;
        boolean hasMajorGroupMode = false;
        for (Long sessionId : completeSessionIds) {
            VolunteerRecommendListResponse original = parser.parseVolunteerRecommendListResponse(
                    new String(Files.readAllBytes(dir.resolve("session_volunteer_" + sessionId + ".json")), StandardCharsets.UTF_8));
            VolunteerRecommendListResponse temp = parser.parseVolunteerRecommendListResponse(
                    new String(Files.readAllBytes(dir.resolve("session_volunteer_" + sessionId + "_temp.json")), StandardCharsets.UTF_8));
            VolunteerRecommendListResponse submitted = parser.parseVolunteerRecommendListResponse(
                    new String(Files.readAllBytes(dir.resolve("session_volunteer_" + sessionId + "_final.json")), StandardCharsets.UTF_8));
            if (countLegacyRecommendEntries(submitted) == 0) {
                continue;
            }

            VolunteerModel model = submitted.getBaseData() == null ? null : submitted.getBaseData().getVolunteerModel();
            hasMajorMode = hasMajorMode || VolunteerModel.major.equals(model);
            hasMajorGroupMode = hasMajorGroupMode || VolunteerModel.majorGroup.equals(model);

            setUp();
            bindPlanningStateStore(sessionId);
            when(volunteerBizService.loadFinalSubmitVolunteerData(sessionId)).thenReturn(submitted);
            when(volunteerBizService.loadCachedRecommendData(sessionId)).thenReturn(temp);
            when(volunteerBizService.loadOriginalVolunteerData(sessionId)).thenReturn(original);

            PlanningStateDTO state = planningStateService.getPlanningState(sessionId);

            assertEquals(countLegacyRecommendEntries(submitted), state.getCandidatePoolState().getItems().size());
            assertEquals("legacy_submitted", state.getOrderedPlanState().getGenerationMode());
            assertTrue(state.getOrderedPlanState().getItems().stream().allMatch(item -> Boolean.TRUE.equals(item.getLocked())));
            assertTrue(state.getOrderedPlanState().getItems().stream().allMatch(item -> Boolean.TRUE.equals(item.getPinned())));
            verify(volunteerBizService, never()).loadCachedRecommendData(sessionId);
            verify(volunteerBizService, never()).loadOriginalVolunteerData(sessionId);
        }

        assertTrue(hasMajorMode, "complete session samples should include major mode");
        assertTrue(hasMajorGroupMode, "complete session samples should include majorGroup mode");
    }

    @Test
    void shouldKeepDistinctCandidatesWhenMajorIdRepeatsWithinSamePlanSchool() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(1, 1, 0, 0);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(30);
        volunteerCount.setMajorCount(6);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool school = buildSchool(
                "ps1",
                "s1",
                "北京联合大学(14)",
                "北京",
                1,
                buildMajorWithPlan("major-1", "plan-1", "软件工程", "65"));
        school.setMajors(java.util.Arrays.asList(
                buildMajorWithPlan("major-1", "plan-1", "软件工程(北四环校区)", "65"),
                buildMajorWithPlan("major-1", "plan-2", "软件工程(蒲黄榆校区)", "62"),
                buildMajorWithPlan("major-2", "plan-3", "电气工程及其自动化", "58")
        ));
        response.setSprints(java.util.Arrays.asList(school));

        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());

        assertNotNull(state.getCandidatePoolState());
        assertEquals(3, state.getCandidatePoolState().getItems().size());
        assertEquals(3, state.getCandidatePoolState().getItems().stream()
                .map(CandidateItemDTO::getVolunteerId)
                .distinct()
                .count());
        assertTrue(state.getCandidatePoolState().getItems().stream()
                .map(CandidateItemDTO::getVolunteerId)
                .allMatch(id -> id != null && id.startsWith("ps1_")));
        CandidatePoolStateDTO.SourceSummary sourceSummary = state.getCandidatePoolState().getSourceSummary();
        assertNotNull(sourceSummary);
        assertEquals(3, sourceSummary.getExternalEntryTotal());
        assertEquals(1, sourceSummary.getExternalUnitTotal());
        assertEquals(3, sourceSummary.getExternalEntryTierCounts().get("冲"));
        assertEquals(1, sourceSummary.getExternalUnitTierCounts().get("冲"));
        assertEquals(3, sourceSummary.getNormalizedEntryTotal());
        assertEquals(1, sourceSummary.getNormalizedUnitTotal());
        assertEquals(3, sourceSummary.getNormalizedEntryTierCounts().get("冲"));
        assertEquals(1, sourceSummary.getNormalizedUnitTierCounts().get("冲"));
    }

    @Test
    void shouldRemoveAddedCandidateFromRemainingWhenReplacingInitialRecommendationCandidate() throws Exception {
        Class<?> selectionStateClass = Class.forName(
                "com.ytell.zhiyuan.service.biz.PlanningStateService$InitialRecommendationSelectionState");
        java.lang.reflect.Constructor<?> constructor = selectionStateClass.getDeclaredConstructor();
        constructor.setAccessible(true);
        Object selectionState = constructor.newInstance();

        CandidateItemDTO selected = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A1", 82D, 61D, 70D, true);
        CandidateItemDTO add = buildCandidateItem("ps2_m1", "ps2", "s2", "学校B", "稳", "专业B1", 76D, 56D, 62D, false);

        @SuppressWarnings("unchecked")
        List<CandidateItemDTO> selectedList = (List<CandidateItemDTO>) ReflectionTestUtils.getField(selectionState, "selected");
        @SuppressWarnings("unchecked")
        List<CandidateItemDTO> remainingList = (List<CandidateItemDTO>) ReflectionTestUtils.getField(selectionState, "remaining");
        @SuppressWarnings("unchecked")
        Set<String> selectedIds = (Set<String>) ReflectionTestUtils.getField(selectionState, "selectedIds");

        assertNotNull(selectedList);
        assertNotNull(remainingList);
        assertNotNull(selectedIds);

        selectedList.add(selected);
        selectedIds.add(selected.getVolunteerId());
        remainingList.add(add);

        ReflectionTestUtils.invokeMethod(
                planningStateService,
                "replaceInitialRecommendationCandidate",
                selectionState,
                selected,
                add,
                "selected_by_gap_fill");

        assertEquals(1, selectedList.size());
        assertEquals("ps2_m1", selectedList.get(0).getVolunteerId());
        assertTrue(selectedIds.contains("ps2_m1"));
        assertFalse(selectedIds.contains("ps1_m1"));
        assertTrue(remainingList.stream().noneMatch(item -> "ps2_m1".equals(item.getVolunteerId())));
        assertEquals(1, remainingList.size());
        assertEquals("ps1_m1", remainingList.get(0).getVolunteerId());
    }


    @Test
    void shouldGroupCandidatesToPlanningUnits() {
        java.util.List<CandidateItemDTO> candidates = java.util.Arrays.asList(
                buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A1", 82D, 61D, 70D, true),
                buildCandidateItem("ps1_m2", "ps1", "s1", "学校A", "冲", "专业A2", 65D, 55D, 70D, false),
                buildCandidateItem("ps1_m3", "ps1", "s1", "学校A", "冲", "专业A3", 58D, 52D, 70D, false),
                buildCandidateItem("ps2_m1", "ps2", "s2", "学校B", "稳", "专业B1", 51D, 49D, 45D, false),
                buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "稳", "专业B2", 43D, 45D, 45D, false)
        );

        @SuppressWarnings("unchecked")
        java.util.List<PlanningUnitDTO> units = (java.util.List<PlanningUnitDTO>) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "groupCandidatesToPlanningUnits",
                candidates,
                2);

        assertNotNull(units);
        assertEquals(2, units.size());
        assertEquals("ps1", units.get(0).getUnitId());
        assertEquals("ps2", units.get(1).getUnitId());
        assertEquals(2, units.get(0).getSelectedMajors().size());
        assertEquals(2, units.get(1).getSelectedMajors().size());
    }

    @Test
    void shouldPreferSafetyMajorWhenBuildingPlanningUnit() {
        java.util.List<CandidateItemDTO> unitCandidates = java.util.Arrays.asList(
                buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A1", 92D, 66D, 80D, true),
                buildCandidateItem("ps1_m2", "ps1", "s1", "学校A", "冲", "专业A2", 85D, 60D, 80D, false),
                buildCandidateItem("ps1_m3", "ps1", "s1", "学校A", "冲", "专业A3", 78D, 58D, 80D, false)
        );

        PlanningUnitDTO unit = (PlanningUnitDTO) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildPlanningUnit",
                unitCandidates,
                2);

        assertNotNull(unit);
        assertTrue(Boolean.TRUE.equals(unit.getHasSafetyMajor()));
        assertEquals(2, unit.getSelectedMajors().size());
        assertTrue(unit.getSelectedMajors().stream().anyMatch(PlanningUnitMajorDTO::getSafetyMajor));
        assertEquals("专业A2", unit.getSelectedMajors().get(0).getMajorName());
        assertEquals("专业A1", unit.getSelectedMajors().get(1).getMajorName());
    }

    @Test
    void shouldDisplaySelectedMajorGroupMajorsByAdmissionRatioAsc() {
        java.util.List<CandidateItemDTO> unitCandidates = java.util.Arrays.asList(
                buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A1", 42D, 95D, 70D, true),
                buildCandidateItem("ps1_m2", "ps1", "s1", "学校A", "冲", "专业A2", 88D, 60D, 70D, false),
                buildCandidateItem("ps1_m3", "ps1", "s1", "学校A", "冲", "专业A3", 76D, 58D, 70D, false)
        );

        PlanningUnitDTO unit = (PlanningUnitDTO) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildPlanningUnit",
                unitCandidates,
                3);

        assertNotNull(unit);
        assertEquals(3, unit.getSelectedMajors().size());
        assertEquals("专业A1", unit.getSelectedMajors().get(0).getMajorName());
        assertEquals("专业A3", unit.getSelectedMajors().get(1).getMajorName());
        assertEquals("专业A2", unit.getSelectedMajors().get(2).getMajorName());

        java.util.List<DraftUnitDTO> draftUnits = ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildDraftUnitsFromPlanningUnits",
                java.util.Arrays.asList(unit),
                "initial_auto");
        assertNotNull(draftUnits);
        assertEquals("专业A1", draftUnits.get(0).getMajorItems().get(0).getMajorName());
        assertEquals("专业A3", draftUnits.get(0).getMajorItems().get(1).getMajorName());
        assertEquals("专业A2", draftUnits.get(0).getMajorItems().get(2).getMajorName());
    }

    @Test
    void shouldMarkPlanningUnitIncompleteWhenMajorCountInsufficient() {
        java.util.List<CandidateItemDTO> unitCandidates = java.util.Arrays.asList(
                buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A1", 72D, 66D, 70D, false),
                buildCandidateItem("ps1_m2", "ps1", "s1", "学校A", "冲", "专业A2", 64D, 60D, 70D, false)
        );

        PlanningUnitDTO unit = (PlanningUnitDTO) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "buildPlanningUnit",
                unitCandidates,
                3);

        assertNotNull(unit);
        assertFalse(Boolean.TRUE.equals(unit.getComplete()));
        assertEquals(2, unit.getSelectedMajorCount());
        assertEquals(2, unit.getTotalMajorCount());
    }

    @Test
    void shouldPopulateWorkingPlanSummaryTargetCountsFromCandidatePoolRequiredCount() {
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId("ps1_m1");
        item.setTier("稳");
        draft.setItems(java.util.Arrays.asList(item));

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setRequiredCount(48);
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());

        ReflectionTestUtils.invokeMethod(
                planningStateService,
                "recalculateWorkingPlanSummary",
                draft,
                candidatePoolState);

        assertEquals(Integer.valueOf(1), draft.getSummary().getUnitTotal());
        assertEquals(Integer.valueOf(48), draft.getSummary().getTargetUnitCount());
        assertEquals(Integer.valueOf(1), draft.getSummary().getTotal());
        assertEquals(Integer.valueOf(48), draft.getSummary().getTargetCount());
    }

    @Test
    void shouldCountUnitTierCounts() {
        java.util.List<PlanningUnitDTO> units = new java.util.ArrayList<PlanningUnitDTO>();
        units.add(buildPlanningUnitDto("ps1", "冲"));
        units.add(buildPlanningUnitDto("ps2", "冲"));
        units.add(buildPlanningUnitDto("ps3", "稳"));

        @SuppressWarnings("unchecked")
        java.util.Map<String, Integer> tierCounts = (java.util.Map<String, Integer>) ReflectionTestUtils.invokeMethod(
                planningStateService,
                "countUnitTierCounts",
                units);

        assertEquals(Integer.valueOf(2), tierCounts.get("冲"));
        assertEquals(Integer.valueOf(1), tierCounts.get("稳"));
        assertEquals(Integer.valueOf(0), tierCounts.get("保"));
    }

    @Test
    void shouldPreferCompleteSafeUnitOverHigherScoreWeakUnit() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(1, 1, 0, 0);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(1);
        volunteerCount.setMajorCount(3);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool weakHighScore = buildSchool("ps1", "s1", "弱高分组", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "63"));
        weakHighScore.setEnroll_ratio("62");
        java.util.Map<String, Object> weakAlgTagMap = new java.util.HashMap<String, Object>();
        weakAlgTagMap.put("volunteer_score", 99D);
        weakHighScore.setAlgTagMap(weakAlgTagMap);
        weakHighScore.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "63"),
                buildMajorWithRatio("m2", "专业A2", "60")
        ));

        VolunteerRecommendListResponse.VolunteerSchool completeSafe = buildSchool("ps2", "s2", "完整安全组", "北京", 2,
                buildMajorWithRatio("m3", "专业B1", "78"));
        completeSafe.setEnroll_ratio("66");
        java.util.Map<String, Object> safeAlgTagMap = new java.util.HashMap<String, Object>();
        safeAlgTagMap.put("volunteer_score", 92D);
        completeSafe.setAlgTagMap(safeAlgTagMap);
        completeSafe.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m3", "专业B1", "78"),
                buildMajorWithRatio("m4", "专业B2", "72"),
                buildMajorWithRatio("m5", "专业B3", "61")
        ));

        response.setSprints(java.util.Arrays.asList(weakHighScore, completeSafe));
        response.setSafes(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(1, state.getInitialRecommendationState().getUnits().size());
        assertEquals("ps1", state.getInitialRecommendationState().getUnits().get(0).getUnitId());
        assertEquals(2, state.getInitialRecommendationState().getUnits().get(0).getSelectedMajors().size());
        assertTrue(Boolean.TRUE.equals(state.getInitialRecommendationState().getUnits().get(0).getHasSafetyMajor()));
        assertTrue(state.getInitialRecommendationState().getItems().stream()
                .allMatch(item -> item.getVolunteerId().startsWith("ps1_")));
    }

    @Test
    void shouldCountLocalProtectByUnitInMajorGroupInitialRecommendation() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(2, 0, 0, 2);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(2);
        volunteerCount.setMajorCount(3);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        CreateSessionReq scoreDetail = buildScoreDetail();
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setName("河南");
        scoreDetail.setProvince(province);
        response.setUserScoreDetail(scoreDetail);

        VolunteerRecommendListResponse.VolunteerSchool localProtect = buildSchool("ps1", "s1", "本省保底组", "河南", 1,
                buildMajorWithRatio("m1", "专业A1", "86"));
        localProtect.setEnroll_ratio("70");
        localProtect.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "86"),
                buildMajorWithRatio("m2", "专业A2", "80"),
                buildMajorWithRatio("m3", "专业A3", "68")
        ));

        VolunteerRecommendListResponse.VolunteerSchool outerProtect = buildSchool("ps2", "s2", "外省保底组", "河北", 2,
                buildMajorWithRatio("m4", "专业B1", "88"));
        outerProtect.setEnroll_ratio("72");
        outerProtect.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业B1", "88"),
                buildMajorWithRatio("m5", "专业B2", "82"),
                buildMajorWithRatio("m6", "专业B3", "70")
        ));

        response.setSprints(java.util.Collections.emptyList());
        response.setSafes(java.util.Collections.emptyList());
        response.setProtects(java.util.Arrays.asList(localProtect, outerProtect));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(2), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(1), state.getInitialRecommendationState().getSummary().getLocalProtectCount());
        assertEquals(2, state.getInitialRecommendationState().getUnits().size());
    }

    @Test
    void shouldRepairInitialPlanMajorGroupIssuesBeforePlanAdjustmentAnalysis() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(4, 2, 2, 0);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(4);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool weakSprintGroup = buildSchool("ps1", "s1", "冲组弱", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "18"));
        weakSprintGroup.setEnroll_ratio("25");
        weakSprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "18")
        ));

        VolunteerRecommendListResponse.VolunteerSchool repairedSprintGroup = buildSchool("ps2", "s2", "冲组稳", "北京", 2,
                buildMajorWithRatio("m2", "专业B1", "20"));
        repairedSprintGroup.setEnroll_ratio("17");
        repairedSprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m2", "专业B1", "20"),
                buildMajorWithRatio("m3", "专业B2", "24"),
                buildMajorWithRatio("m4", "专业B3", "16")
        ));

        VolunteerRecommendListResponse.VolunteerSchool normalSprintGroup = buildSchool("ps3", "s3", "冲组常规", "北京", 3,
                buildMajorWithRatio("m5", "专业C1", "26"));
        normalSprintGroup.setEnroll_ratio("22");
        normalSprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m5", "专业C1", "26"),
                buildMajorWithRatio("m6", "专业C2", "28"),
                buildMajorWithRatio("m7", "专业C3", "21")
        ));

        VolunteerRecommendListResponse.VolunteerSchool safeGroupA = buildSchool("ps4", "s4", "稳组A", "河南", 1,
                buildMajorWithRatio("m8", "专业D1", "32"));
        safeGroupA.setEnroll_ratio("29");
        safeGroupA.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m8", "专业D1", "32"),
                buildMajorWithRatio("m9", "专业D2", "34"),
                buildMajorWithRatio("m10", "专业D3", "28")
        ));

        VolunteerRecommendListResponse.VolunteerSchool safeGroupB = buildSchool("ps5", "s5", "稳组B", "河南", 2,
                buildMajorWithRatio("m11", "专业E1", "38"));
        safeGroupB.setEnroll_ratio("35");
        safeGroupB.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m11", "专业E1", "38"),
                buildMajorWithRatio("m12", "专业E2", "40"),
                buildMajorWithRatio("m13", "专业E3", "34")
        ));

        response.setSprints(java.util.Arrays.asList(weakSprintGroup, repairedSprintGroup, normalSprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroupA, safeGroupB));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO initialState = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        java.util.List<String> draftIds = initialState.getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(java.util.stream.Collectors.toList());
        assertFalse(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps2_m2"));
        assertTrue(draftIds.contains("ps2_m3"));
        assertFalse(initialState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("group_inner_safety_guard"));
        assertFalse(initialState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("probability_inversion"));
        assertFalse(initialState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("probability_gap"));
        assertTrue(initialState.getInitialRecommendationState().getStrategyReport().getObjectiveWeights().stream()
                .anyMatch(item -> "major_group_inner_safety".equals(item.getCode())
                        && item.getRelativeWeight() != null
                        && item.getPriority() != null));

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        java.util.Map<String, Boolean> ruleHits = adjustmentState.getAnalysis().getRules().stream()
                .collect(java.util.stream.Collectors.toMap(
                        rule -> rule.getRuleCode(),
                        rule -> Boolean.TRUE.equals(rule.getHit()),
                        (left, right) -> left,
                        java.util.LinkedHashMap::new));

        assertFalse(Boolean.TRUE.equals(ruleHits.get("group_inner_safety_guard")));
        assertFalse(Boolean.TRUE.equals(ruleHits.get("probability_inversion")));
        assertFalse(Boolean.TRUE.equals(ruleHits.get("probability_gap")));
    }

    @Test
    void shouldBorrowInitialPlanGapFromSaferTierBeforeSprintInMajorMode() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(6, 2, 2, 2));
        response.setUserScoreDetail(buildScoreDetail());

        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "12")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18")),
                buildSchool("ps3", "s3", "冲C", "北京", 3, buildMajorWithRatio("m3", "专业C", "24")),
                buildSchool("ps4", "s4", "冲D", "北京", 4, buildMajorWithRatio("m4", "专业D", "30"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "稳A", "北京", 1, buildMajorWithRatio("m5", "专业E", "55")),
                buildSchool("ps6", "s6", "稳B", "北京", 2, buildMajorWithRatio("m6", "专业F", "60")),
                buildSchool("ps7", "s7", "稳C", "北京", 3, buildMajorWithRatio("m7", "专业G", "64")),
                buildSchool("ps8", "s8", "稳D", "北京", 4, buildMajorWithRatio("m8", "专业H", "68"))
        ));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(6), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(2), state.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(4), state.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(0), state.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertEquals(Integer.valueOf(2), state.getDraftPlanState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(4), state.getDraftPlanState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(0), state.getDraftPlanState().getSummary().getTierCounts().get("保"));
    }

    @Test
    void shouldPreferSafeCandidatesWhenProtectTierIsUnavailableUnderRealWorldScale() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(96, 38, 28, 30));
        response.setUserScoreDetail(buildScoreDetail());

        java.util.List<VolunteerRecommendListResponse.VolunteerSchool> sprints = new java.util.ArrayList<VolunteerRecommendListResponse.VolunteerSchool>();
        for (int i = 1; i <= 272; i++) {
            sprints.add(buildSchool("sp" + i, "s" + i, "冲" + i, "北京", i,
                    buildMajorWithRatio("msp" + i, "冲专业" + i, String.valueOf(10 + (i % 20)))));
        }
        java.util.List<VolunteerRecommendListResponse.VolunteerSchool> safes = new java.util.ArrayList<VolunteerRecommendListResponse.VolunteerSchool>();
        for (int i = 1; i <= 130; i++) {
            safes.add(buildSchool("sf" + i, "ss" + i, "稳" + i, "天津", i,
                    buildMajorWithRatio("msf" + i, "稳专业" + i, String.valueOf(40 + (i % 30)))));
        }
        response.setSprints(sprints);
        response.setSafes(safes);
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(96), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(38), state.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(58), state.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(0), state.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
    }

    @Test
    void shouldKeepTierTargetsForHighScoreMajorModeWhenSupplyIsSufficient() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(96, 38, 28, 30));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(buildFlatSchools("冲", "北京", 60, 12, 37));
        response.setSafes(buildFlatSchools("稳", "上海", 60, 45, 72));
        response.setProtects(buildFlatSchools("保", "江苏", 60, 80, 96));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(96), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(38), state.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(28), state.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(30), state.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertTrue(state.getOrderedPlanState().getSummary().getTierCounts().get("冲") >= 37);
        assertEquals(Integer.valueOf(28), state.getOrderedPlanState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(30), state.getOrderedPlanState().getSummary().getTierCounts().get("保"));
        assertFalse(state.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("ratio_distribution"));
        assertFalse(state.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("safety_guard"));
        assertTierSelectionHighScoreFirst(state, "冲", 37, 60);
        assertTierSelectionHighScoreFirst(state, "稳", 28, 28);
        assertTierSelectionHighScoreFirst(state, "保", 30, 30);
    }

    @Test
    void shouldKeepSprintQuotaForHighScoreMajorModeUnderAggressiveTargets() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(96, 38, 28, 30));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(buildFlatSchools("冲高", "北京", 120, 8, 34));
        response.setSafes(buildFlatSchools("稳高", "上海", 90, 42, 68));
        response.setProtects(buildFlatSchools("保高", "广东", 90, 78, 96));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(38), state.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(28), state.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(30), state.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertEquals(Integer.valueOf(38), state.getDraftPlanState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(28), state.getDraftPlanState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(30), state.getDraftPlanState().getSummary().getTierCounts().get("保"));
        assertTierSelectionHighScoreFirst(state, "冲", 37, 45);
        assertTierSelectionHighScoreFirst(state, "稳", 28, 32);
        assertTierSelectionHighScoreFirst(state, "保", 30, 34);
    }

    @Test
    void shouldPreferHighScoreBusinessAndLawCandidatesWhenSupplyIsSufficient() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(96, 38, 28, 30));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(buildTaggedHighScoreSchools("冲文商", "北京", 50, "法学", 1000D, 12, 36));
        response.getSprints().addAll(buildTaggedHighScoreSchools("冲理工", "北京", 50, "计算机", 700D, 12, 36));
        response.setSafes(buildTaggedHighScoreSchools("稳文商", "上海", 50, "财经", 950D, 45, 70));
        response.getSafes().addAll(buildTaggedHighScoreSchools("稳理工", "上海", 50, "电子信息", 650D, 45, 70));
        response.setProtects(buildTaggedHighScoreSchools("保文商", "江苏", 50, "法学", 900D, 80, 96));
        response.getProtects().addAll(buildTaggedHighScoreSchools("保理工", "江苏", 50, "自动化", 600D, 80, 96));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(38), state.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(28), state.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(30), state.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertTierSelectionDominatedByTaggedHeadCandidates(state, "冲", "法学", 0.85D);
        assertTierSelectionDominatedByTaggedHeadCandidates(state, "稳", "财经", 0.85D);
        assertTierSelectionDominatedByTaggedHeadCandidates(state, "保", "法学", 0.85D);
    }

    @Test
    void shouldKeepTierTargetsForHighScoreMajorGroupModeWhenSupplyIsSufficient() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(48, 14, 14, 20);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(48);
        volunteerCount.setMajorCount(3);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(buildGroupSchools("冲组", "北京", 24, 20, 12D));
        response.setSafes(buildGroupSchools("稳组", "上海", 24, 55, 14D));
        response.setProtects(buildGroupSchools("保组", "江苏", 30, 82, 16D));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(48), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(14), state.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(14), state.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(20), state.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertEquals(Integer.valueOf(48), state.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(48), state.getOrderedPlanState().getSummary().getTotal());
        assertFalse(state.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("group_inner_safety_guard"));
        assertMajorGroupRepresentativeSelectionWithinTopRanks(state, "冲", 14, 14);
        assertMajorGroupRepresentativeSelectionWithinTopRanks(state, "稳", 14, 14);
        assertMajorGroupRepresentativeSelectionWithinTopRanks(state, "保", 20, 20);
    }

    @Test
    void shouldKeepSprintQuotaForHighScoreMajorGroupModeUnderAggressiveTargets() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(48, 14, 14, 20);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(48);
        volunteerCount.setMajorCount(3);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(buildGroupSchools("激冲组", "北京", 40, 18, 10D));
        response.setSafes(buildGroupSchools("激稳组", "上海", 32, 52, 12D));
        response.setProtects(buildGroupSchools("激保组", "广东", 28, 80, 14D));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(14), state.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(14), state.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(20), state.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertEquals(Integer.valueOf(14), state.getOrderedPlanState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(14), state.getOrderedPlanState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(20), state.getOrderedPlanState().getSummary().getTierCounts().get("保"));
        assertMajorGroupRepresentativeSelectionWithinTopRanks(state, "冲", 14, 14);
        assertMajorGroupRepresentativeSelectionWithinTopRanks(state, "稳", 14, 14);
        assertMajorGroupRepresentativeSelectionWithinTopRanks(state, "保", 20, 20);
    }


    @Test
    void shouldReorderDraftPlanAndMarkGenerationMetadata() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "18"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "52"))));
        response.setProtects(java.util.Arrays.asList(buildSchool("ps3", "s3", "学校C", "北京", 3, buildMajorWithRatio("m3", "专业C", "81"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        selectReq.setSource("manual_workspace_v2");
        planningStateService.selectDraftItems(1L, selectReq);

        DraftPlanReorderReq reorderReq = new DraftPlanReorderReq();
        reorderReq.setForceRegenerate(true);
        reorderReq.setRegroupByTier(true);
        PlanningStateDTO reordered = planningStateService.reorderDraftPlan(1L, 1L, reorderReq);

        assertEquals("draft_reorder", reordered.getPlanGenerationState().getMode());
        assertEquals("draft_reorder", reordered.getOrderedPlanState().getGenerationMode());
        assertEquals(Integer.valueOf(3), reordered.getOrderedPlanState().getSummary().getTotal());
    }

    @Test
    void shouldKeepWorkspaceCandidateDetailsForDraftAndOrderedItems() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO orderedCandidate = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 82D, 61D, 70D, true);
        orderedCandidate.setHotIndex(88D);
        orderedCandidate.setSalaryAvg(45D);
        CandidateItemDTO unusedCandidate = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "稳", "专业B", 56D, 40D, 50D, false);
        candidatePoolState.setItems(java.util.Arrays.asList(orderedCandidate, unusedCandidate));
        state.setCandidatePoolState(candidatePoolState);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        OrderedItemDTO orderedItem = new OrderedItemDTO();
        orderedItem.setVolunteerId("ps1_m1");
        orderedItem.setSchoolName("学校A");
        orderedItem.setMajorName("专业A");
        orderedPlanState.setItems(java.util.Collections.singletonList(orderedItem));
        state.setOrderedPlanState(orderedPlanState);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals(1, workspaceState.getCandidatePoolState().getItems().size());
        CandidateItemDTO workspaceCandidate = workspaceState.getCandidatePoolState().getItems().get(0);
        assertEquals("ps1_m1", workspaceCandidate.getVolunteerId());
        assertEquals(Double.valueOf(82D), workspaceCandidate.getAdmissionRatio());
        assertEquals(Double.valueOf(61D), workspaceCandidate.getFinalScore());
        assertEquals(Double.valueOf(88D), workspaceCandidate.getHotIndex());
        assertEquals(Double.valueOf(45D), workspaceCandidate.getSalaryAvg());
    }

    @Test
    void shouldResolveLegacyWorkspaceCandidateDetailsBySchoolAndMajor() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO orderedCandidate = buildCandidateItem("ps1_s1_pm1", "ps1", "s1", "学校A", "冲", "专业A", 82D, 61D, 70D, true);
        CandidateItemDTO samePrefixCandidate = buildCandidateItem("ps1_s1_pm2", "ps1", "s1", "学校A", "冲", "专业B", 74D, 55D, 70D, false);
        candidatePoolState.setItems(java.util.Arrays.asList(orderedCandidate, samePrefixCandidate));
        state.setCandidatePoolState(candidatePoolState);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        OrderedItemDTO orderedItem = new OrderedItemDTO();
        orderedItem.setVolunteerId("ps1_s1_legacy1");
        orderedItem.setSchoolName("学校A");
        orderedItem.setMajorName("专业A");
        orderedPlanState.setItems(java.util.Collections.singletonList(orderedItem));
        state.setOrderedPlanState(orderedPlanState);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals(1, workspaceState.getCandidatePoolState().getItems().size());
        CandidateItemDTO workspaceCandidate = workspaceState.getCandidatePoolState().getItems().get(0);
        assertEquals("ps1_s1_legacy1", workspaceCandidate.getVolunteerId());
        assertEquals(Double.valueOf(82D), workspaceCandidate.getAdmissionRatio());
        assertEquals(Double.valueOf(61D), workspaceCandidate.getFinalScore());
        assertEquals("专业A", workspaceCandidate.getMajorName());
    }

    @Test
    void shouldResolveLegacyMajorGroupWorkspaceCandidateDetailsByUnitMajorContext() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        CandidateItemDTO accounting = buildCandidateItem("ps1_s1_pm1", "ps1", "s1", "学校A第01组", "冲", "会计学", 82D, 61D, 70D, true);
        CandidateItemDTO law = buildCandidateItem("ps1_s1_pm2", "ps1", "s1", "学校A第01组", "冲", "法学", 76D, 58D, 70D, false);
        candidatePoolState.setItems(java.util.Arrays.asList(accounting, law));
        state.setCandidatePoolState(candidatePoolState);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("ps1");
        unit.setSchoolName("学校A第01组");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId("ps1_s1_legacy1");
        major.setMajorName("会计学");
        unit.setMajorItems(java.util.Collections.singletonList(major));
        orderedPlanState.setUnits(java.util.Collections.singletonList(unit));
        state.setOrderedPlanState(orderedPlanState);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals(1, workspaceState.getCandidatePoolState().getItems().size());
        CandidateItemDTO workspaceCandidate = workspaceState.getCandidatePoolState().getItems().get(0);
        assertEquals("ps1_s1_legacy1", workspaceCandidate.getVolunteerId());
        assertEquals(Double.valueOf(82D), workspaceCandidate.getAdmissionRatio());
        assertEquals(Double.valueOf(61D), workspaceCandidate.getFinalScore());
        assertEquals("会计学", workspaceCandidate.getMajorName());
    }

    @Test
    void shouldExposeWorkflowStatusForEmptyCandidatePool() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setGeneratedAt("2026-05-12T10:00:00+08:00");
        candidatePoolState.setStatusCode("empty");
        candidatePoolState.setStatusMessage("当前可用于规划的候选池暂无可用志愿");
        state.setCandidatePoolState(candidatePoolState);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals("empty", workspaceState.getWorkflowStatus().getCandidateStatus());
        assertEquals("当前可用于规划的候选池暂无可用志愿", workspaceState.getWorkflowStatus().getCandidateMessage());
        assertEquals("empty", workspaceState.getWorkflowStatus().getPlanStatus());
    }

    @Test
    void shouldMarkGeneratedEmptyCandidatePoolAsSystemSupplyIssue() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Collections.emptyList());
        response.setSafes(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());

        assertEquals("empty", state.getCandidatePoolState().getStatusCode());
        assertEquals("当前可用于规划的候选池暂无可用志愿，请核验专项资格、批次、分数线、选科或身体限报等条件",
                state.getCandidatePoolState().getStatusMessage());
        assertFalse(state.getCandidatePoolState().getStatusMessage().contains("筛选"));
        assertFalse(state.getCandidatePoolState().getRiskHints().isEmpty());

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);
        assertEquals("empty", workspaceState.getWorkflowStatus().getCandidateStatus());
        assertFalse(workspaceState.getWorkflowStatus().getCandidateMessage().contains("筛选"));
    }

    @Test
    void shouldExposeWorkflowStatusForPendingReviewPlan() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.getCandidatePoolState().setStatusCode("ready");
        state.getCandidatePoolState().setStatusMessage("候选池已生成");
        OrderedItemDTO orderedItem = new OrderedItemDTO();
        orderedItem.setVolunteerId("v1");
        state.getOrderedPlanState().setItems(java.util.Collections.singletonList(orderedItem));
        state.getStaleFlags().setReview(true);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals("ready", workspaceState.getWorkflowStatus().getCandidateStatus());
        assertEquals("pending_review", workspaceState.getWorkflowStatus().getPlanStatus());
        assertEquals("not_reviewed", workspaceState.getWorkflowStatus().getReviewStatus());
    }

    @Test
    void shouldExposeWorkflowStatusForLegacySubmittedPlan() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        OrderedItemDTO orderedItem = new OrderedItemDTO();
        orderedItem.setVolunteerId("v1");
        state.getOrderedPlanState().setItems(java.util.Collections.singletonList(orderedItem));
        state.getOrderedPlanState().setGenerationMode("legacy_submitted");

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals("legacy_readonly", workspaceState.getWorkflowStatus().getPlanStatus());
        assertEquals(Boolean.TRUE, workspaceState.getWorkflowStatus().getLegacySubmitted());
    }

    @Test
    void shouldExposeStudentSummaryAndIntentStateForWorkspaceHeader() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.getProfileState().getExplicitProfile().getStrengthSubjects().add("物理");
        state.getProfileState().getExplicitProfile().getPositiveRegions().add("北京");
        state.getConstraintState().getSoftPreferences().getPreferMajors().add("计算机");
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("天津");

        CreateSessionReq scoreDetail = new CreateSessionReq();
        CreateSessionReq.Sex sex = new CreateSessionReq.Sex();
        sex.setCode("male");
        scoreDetail.setSex(sex);
        scoreDetail.setTotalScore(537);
        scoreDetail.setTotalScorePos(11278);
        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setName("本科批");
        batch.setScore(446F);
        scoreDetail.setBatch(batch);
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setName("湖南");
        scoreDetail.setProvince(province);
        scoreDetail.setSubjectList(java.util.Arrays.asList(
                new CreateSessionReq.SubjectItem(1, "首选", "history", "历史"),
                new CreateSessionReq.SubjectItem(0, "再选", "biology", "生物"),
                new CreateSessionReq.SubjectItem(0, "再选", "politics", "政治")));
        ChatSessionExtraData scoreData = new ChatSessionExtraData();
        scoreData.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        scoreData.setDataValue(com.alibaba.fastjson.JSONObject.toJSONString(scoreDetail));
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.USER_SCORE_KEY)))
                .thenReturn(scoreData);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals("男", workspaceState.getStudentSummary().getSex());
        assertEquals(Integer.valueOf(537), workspaceState.getStudentSummary().getScore());
        assertEquals(Integer.valueOf(11278), workspaceState.getStudentSummary().getRank());
        assertEquals("本科批", workspaceState.getStudentSummary().getBatchName());
        assertEquals(Integer.valueOf(446), workspaceState.getStudentSummary().getBatchScore());
        assertEquals("湖南", workspaceState.getStudentSummary().getProvinceName());
        assertEquals(java.util.Arrays.asList("历史", "生物", "政治"), workspaceState.getStudentSummary().getSubjects());
        assertEquals(java.util.Arrays.asList("物理"), workspaceState.getStudentSummary().getStrengthSubjects());
        assertEquals(java.util.Arrays.asList("北京"), workspaceState.getProfileState().getExplicitProfile().getPositiveRegions());
        assertEquals(java.util.Arrays.asList("计算机"), workspaceState.getConstraintState().getSoftPreferences().getPreferMajors());
        assertEquals(java.util.Arrays.asList("天津"), workspaceState.getConstraintState().getHardConstraints().getMustExcludeRegions());
    }

    @Test
    void shouldInitializeProfileStateFromSessionData() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        CreateSessionReq scoreDetail = buildScoreDetail();
        UserProfileData userProfileData = buildUserProfileData();

        planningStateService.initializeProfileState(1L, scoreDetail, userProfileData);

        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService).save(captor.capture());
        PlanningStateDTO state = com.alibaba.fastjson.JSONObject.parseObject(captor.getValue().getDataValue(), PlanningStateDTO.class);

        assertEquals(java.util.Arrays.asList("计算机", "电子信息"), state.getProfileState().getExplicitProfile().getPositiveMajors());
        assertEquals(java.util.Arrays.asList("临床医学"), state.getProfileState().getExplicitProfile().getNegativeMajors());
        assertEquals(java.util.Arrays.asList("北京", "上海"), state.getProfileState().getExplicitProfile().getPositiveRegions());
        assertEquals(java.util.Arrays.asList("物理", "化学"), state.getProfileState().getExplicitProfile().getStrengthSubjects());
        assertEquals("170", state.getProfileState().getPhysicalConstraints().getHeight());
        assertEquals("4.8", state.getProfileState().getPhysicalConstraints().getVision().getLeft());
        assertEquals("5.0", state.getProfileState().getPhysicalConstraints().getVision().getRight());
        assertEquals(java.util.Arrays.asList("normal"), state.getProfileState().getPhysicalConstraints().getColorVision());
        assertTrue(state.getProfileState().getPhysicalConstraints().getSpecialLimits().contains("专项计划"));
        assertTrue(state.getProfileState().getPhysicalConstraints().getSpecialLimits().contains("不接受中外合作"));
    }

    @Test
    void shouldInitializeNewSessionPlanWithoutImportingLegacyPlan() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse legacy = new VolunteerRecommendListResponse();
        legacy.setBaseData(buildBaseData(2, 1, 1, 0));
        VolunteerRecommendListResponse.VolunteerSchool legacySprint = buildSchool(
                "legacy_ps1", "legacy_s1", "历史学校A", "北京", 1, buildMajorWithRatio("legacy_m1", "历史专业A", "18"));
        legacySprint.setIs_preferred(true);
        VolunteerRecommendListResponse.VolunteerSchool legacySafe = buildSchool(
                "legacy_ps2", "legacy_s2", "历史学校B", "天津", 1, buildMajorWithRatio("legacy_m2", "历史专业B", "52"));
        legacySafe.setIs_preferred(true);
        legacy.setSprints(java.util.Arrays.asList(legacySprint));
        legacy.setSafes(java.util.Arrays.asList(legacySafe));
        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenReturn(legacy);

        planningStateService.initializeProfileState(1L, buildScoreDetail(), buildUserProfileData());

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("new_ps1", "new_s1", "新学校A", "北京", 1, buildMajorWithRatio("new_m1", "新专业A", "25"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("new_ps2", "new_s2", "新学校B", "天津", 1, buildMajorWithRatio("new_m2", "新专业B", "55"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("new_ps3", "new_s3", "新学校C", "河北", 1, buildMajorWithRatio("new_m3", "新专业C", "85"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateInitialPlan(1L, 1L, new InitialPlanGenerateReq());

        assertEquals(Integer.valueOf(3), state.getCandidatePoolState().getRequiredCount());
        assertEquals(3, state.getCandidatePoolState().getItems().size());
        assertEquals(Integer.valueOf(3), state.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(3), state.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(3), state.getOrderedPlanState().getSummary().getTotal());
        assertEquals("initial_auto", state.getOrderedPlanState().getGenerationMode());
        assertTrue(state.getDraftPlanState().getItems().stream()
                .allMatch(item -> item.getVolunteerId().startsWith("new_ps")));
        assertTrue(state.getOrderedPlanState().getItems().stream()
                .allMatch(item -> item.getVolunteerId().startsWith("new_ps")));
        assertTrue(state.getOperationLogs().stream().noneMatch(log -> "legacy_plan_import".equals(log.getType())));
        verify(volunteerBizService, never()).loadFinalSubmitVolunteerData(1L);
        verify(volunteerBizService, never()).loadCachedRecommendData(1L);
        verify(volunteerBizService, never()).loadOriginalVolunteerData(1L);
    }

    @Test
    void shouldBackfillProfileStateFromLegacySessionData() {
        ChatSessionExtraData scoreData = new ChatSessionExtraData();
        scoreData.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        scoreData.setDataValue(com.alibaba.fastjson.JSONObject.toJSONString(buildScoreDetail()));

        ChatSessionExtraData profileData = new ChatSessionExtraData();
        profileData.setDataKey(ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        profileData.setDataValue(com.alibaba.fastjson.JSONObject.toJSONString(buildUserProfileData()));

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.USER_SCORE_KEY)))
                .thenReturn(scoreData);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.USER_PROFILE_KEY)))
                .thenReturn(profileData);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals(java.util.Arrays.asList("计算机", "电子信息"), state.getProfileState().getExplicitProfile().getPositiveMajors());
        assertEquals(java.util.Arrays.asList("临床医学"), state.getProfileState().getExplicitProfile().getNegativeMajors());
        assertEquals(java.util.Arrays.asList("北京", "上海"), state.getProfileState().getExplicitProfile().getPositiveRegions());
        assertEquals(java.util.Arrays.asList("河北"), state.getProfileState().getExplicitProfile().getNegativeRegions());
        assertEquals(java.util.Arrays.asList("清华大学"), state.getProfileState().getExplicitProfile().getPositiveSchools());
        assertEquals(java.util.Arrays.asList("物理", "化学"), state.getProfileState().getExplicitProfile().getStrengthSubjects());
        assertEquals("170", state.getProfileState().getPhysicalConstraints().getHeight());
    }

    @Test
    void shouldPersistCandidateViewStateWithoutTouchingStaleFlags() {
        AtomicReference<ChatSessionExtraData> planningStateRef = bindPlanningStateStore();

        planningStateService.initializeProfileState(1L, buildScoreDetail(), buildUserProfileData());

        CandidateViewStateDTO req = new CandidateViewStateDTO();
        req.getFilters().setProvinceNames(java.util.Arrays.asList("北京"));
        req.getFilters().setNegativeProvinceNames(java.util.Arrays.asList("河北"));
        req.getFilters().setMajorKeywords(java.util.Arrays.asList("计算机"));
        req.setExpertPreferredOnly(true);
        req.getSort().setField("hotIndex");
        req.getSort().setOrder("asc");

        PlanningStateDTO updated = planningStateService.updateCandidateViewState(1L, req);

        assertEquals(java.util.Arrays.asList("北京"), updated.getCandidateViewState().getFilters().getProvinceNames());
        assertEquals(java.util.Arrays.asList("河北"), updated.getCandidateViewState().getFilters().getNegativeProvinceNames());
        assertEquals(java.util.Arrays.asList("计算机"), updated.getCandidateViewState().getFilters().getMajorKeywords());
        assertTrue(Boolean.TRUE.equals(updated.getCandidateViewState().getExpertPreferredOnly()));
        assertEquals("hotIndex", updated.getCandidateViewState().getSort().getField());
        assertEquals("asc", updated.getCandidateViewState().getSort().getOrder());
        assertFalse(Boolean.TRUE.equals(updated.getStaleFlags().getCandidatePool()));
        assertFalse(Boolean.TRUE.equals(updated.getStaleFlags().getRecommendationOverlay()));
        assertTrue(Boolean.TRUE.equals(updated.getStaleFlags().getInitialRecommendation()));
        assertFalse(Boolean.TRUE.equals(updated.getStaleFlags().getOrderedPlan()));
        assertTrue(Boolean.TRUE.equals(updated.getStaleFlags().getPlanAdjustment()));
        assertFalse(Boolean.TRUE.equals(updated.getStaleFlags().getReview()));
        assertNotNull(planningStateRef.get());
    }

    @Test
    void shouldKeepReviewedWorkspaceCurrentWhenCandidateViewChanges() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "专业A", 55D, 80D, 55D, false));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "稳"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "稳", 1));
        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-09T10:00:00+08:00");
        reviewState.setSourceVersion(7);
        reviewState.getSummary().setTotalRuleCount(1);
        reviewState.getSummary().setPassedRuleCount(1);
        state.setReviewState(reviewState);
        saveStateToStore(1L, state);

        CandidateViewStateDTO req = new CandidateViewStateDTO();
        req.getFilters().setProvinceNames(java.util.Arrays.asList("北京"));
        PlanningStateDTO updated = planningStateService.updateCandidateViewState(1L, req);

        assertTrue(Boolean.TRUE.equals(updated.getStaleFlags().getInitialRecommendation()));
        assertTrue(Boolean.TRUE.equals(updated.getStaleFlags().getPlanAdjustment()));
        assertFalse(Boolean.TRUE.equals(updated.getStaleFlags().getReview()));
        assertEquals("candidate_view_changed", updated.getStaleFlags().getReasonCode());

        PlanningWorkspaceStateRes workspaceState = planningStateService.getPlanningWorkspaceState(1L);
        assertEquals("ready", workspaceState.getWorkflowStatus().getPlanStatus());
        assertEquals("passed", workspaceState.getWorkflowStatus().getReviewStatus());
        assertNull(workspaceState.getWorkflowStatus().getReviewReasonCode());
    }

    @Test
    void shouldMarkReviewedWorkspaceStaleWhenOrderedPlanMoves() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(5);
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 35D, 90D, 35D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "专业B", 55D, 80D, 55D, false));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "稳"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "稳", 2));
        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-09T10:00:00+08:00");
        reviewState.setSourceVersion(5);
        reviewState.getSummary().setTotalRuleCount(1);
        reviewState.getSummary().setPassedRuleCount(1);
        state.setReviewState(reviewState);
        saveStateToStore(1L, state);

        OrderedMoveReq moveReq = new OrderedMoveReq();
        moveReq.setVolunteerId("ps1_m1");
        moveReq.setTargetPosition(2);
        PlanningStateDTO moved = planningStateService.moveOrderedItem(1L, moveReq);

        assertEquals("ps2_m2", moved.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", moved.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertTrue(Boolean.TRUE.equals(moved.getStaleFlags().getReview()));
        assertEquals("plan_structure_changed", moved.getStaleFlags().getReasonCode());

        PlanningWorkspaceStateRes workspaceState = planningStateService.getPlanningWorkspaceState(1L);
        assertEquals("pending_review", workspaceState.getWorkflowStatus().getPlanStatus());
        assertEquals("stale", workspaceState.getWorkflowStatus().getReviewStatus());
        assertEquals("plan_structure_changed", workspaceState.getWorkflowStatus().getReviewReasonCode());
    }

    @Test
    void shouldPersistLatentProfileAndMarkStaleFlags() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        UpdateLatentProfileReq req = new UpdateLatentProfileReq();
        req.setFutureDevelopment(new com.ytell.zhiyuan.model.dto.planning.FutureDevelopmentDTO());
        req.getFutureDevelopment().setStabilityVsIncome("income_first");

        PlanningStateVersionDTO result = planningStateService.updateLatentProfile(1L, req);

        assertEquals(Integer.valueOf(1), result.getVersion());
        assertFalse(result.getStaleFlags().getCandidatePool());
        assertTrue(result.getStaleFlags().getRecommendationOverlay());
        assertTrue(result.getStaleFlags().getInitialRecommendation());
        assertTrue(result.getStaleFlags().getOrderedPlan());
        assertTrue(result.getStaleFlags().getPlanAdjustment());
        assertTrue(result.getStaleFlags().getReview());

        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, times(1)).save(captor.capture());
        verify(chatSessionExtraDataSharedService, never()).updateById(any(ChatSessionExtraData.class));

        ChatSessionExtraData saved = captor.getValue();
        assertEquals(ChatSessionExtraDataConstants.PLANNING_STATE_KEY, saved.getDataKey());
        assertTrue(saved.getDataValue().contains("income_first"));
    }

    @Test
    void shouldDerivePreferencesFromLatentProfile() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        UpdateLatentProfileReq req = new UpdateLatentProfileReq();
        req.setFutureDevelopment(new com.ytell.zhiyuan.model.dto.planning.FutureDevelopmentDTO());
        req.getFutureDevelopment().setIndustryPreferences(java.util.Arrays.asList("人工智能"));
        req.setInterestPersonality(new com.ytell.zhiyuan.model.dto.planning.InterestPersonalityDTO());
        req.getInterestPersonality().setSubjectInterests(java.util.Arrays.asList("数学"));
        req.setFamilyContext(new com.ytell.zhiyuan.model.dto.planning.FamilyContextDTO());
        req.getFamilyContext().setTuitionTolerance("medium");
        planningStateService.updateLatentProfile(1L, req);

        ArgumentCaptor<ChatSessionExtraData> saveCaptor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService).save(saveCaptor.capture());
        ChatSessionExtraData stored = new ChatSessionExtraData();
        stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        stored.setDataValue(saveCaptor.getValue().getDataValue());
        reset(chatSessionExtraDataSharedService);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        ConstraintDeriveRes res = planningStateService.deriveConstraints(1L);

        assertTrue(res.getDerivedPreferences().getRecommendedMajorClusters().contains("人工智能"));
        assertTrue(res.getDerivedPreferences().getRecommendedMajorClusters().contains("数学"));
        assertEquals("medium", res.getDerivedPreferences().getTuitionFlexibilityInferred());
    }

    @Test
    void shouldGenerateAndQueryCandidatePool() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool school = new VolunteerRecommendListResponse.VolunteerSchool();
        school.setPlanSchoolDataId("ps1");
        school.setSchoolId("s1");
        school.setSchool_name("北京邮电大学");
        school.setProvince_name("北京");
        school.setCity_name("北京");
        school.setSchool_rank(12);
        school.setBaoyan_ratio(0.18D);
        school.setUpgrade_ratio(0.66D);
        school.setMaster_count(42);
        school.setDoctor_count(18);
        school.setSchool_batch("本科");
        school.setSchool_level("211");
        school.setSchool_nature("公办");
        school.setSchool_category("理工");
        school.setEnroll_ratio("61");
        school.setRankTagList(java.util.Arrays.asList("211", "双一流"));
        school.setBasicTagList(java.util.Arrays.asList("公办", "理工"));
        school.setRank_in_tier(2);
        school.setIs_preferred(true);
        java.util.Map<String, Object> schoolAlgTagMap = new java.util.HashMap<String, Object>();
        schoolAlgTagMap.put("college_score_new", 86.2D);
        schoolAlgTagMap.put("major_score", 78.4D);
        schoolAlgTagMap.put("volunteer_score", 81.8D);
        school.setAlgTagMap(schoolAlgTagMap);
        VolunteerRecommendListResponse.HistoryScore schoolHistory = new VolunteerRecommendListResponse.HistoryScore();
        schoolHistory.setYear(2025);
        schoolHistory.setScore(645);
        schoolHistory.setPos(3821);
        schoolHistory.setPlanNum(12);
        schoolHistory.setEnrollNum(12);
        school.setHistory_score_list(java.util.Arrays.asList(schoolHistory));
        VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
        major.setMajorId("m1");
        major.setMajor_name("计算机科学与技术");
        major.setMajorUnitCode("080901");
        major.setLevel("优选");
        major.setEnroll_ratio("58");
        major.setPlanNum(6);
        major.setDuration("4年");
        major.setPlanMoney("5800");
        major.setMust_subject(java.util.Arrays.asList("物理", "化学"));
        major.setRankTagList(java.util.Arrays.asList("意向专业"));
        major.setPlanTagList(java.util.Arrays.asList("计划数:6", "学制:4年"));
        java.util.Map<String, Object> majorAlgTagMap = new java.util.HashMap<String, Object>();
        majorAlgTagMap.put("hot_index", 82.5D);
        majorAlgTagMap.put("salary_avg", 18.6D);
        majorAlgTagMap.put("major_score_new", 78.4D);
        major.setAlgTagMap(majorAlgTagMap);
        VolunteerRecommendListResponse.HistoryScore majorHistory = new VolunteerRecommendListResponse.HistoryScore();
        majorHistory.setYear(2025);
        majorHistory.setScore(643);
        majorHistory.setPos(4012);
        majorHistory.setPlanNum(6);
        majorHistory.setEnrollNum(6);
        major.setHistory_score_list(java.util.Arrays.asList(majorHistory));
        school.setMajors(java.util.Arrays.asList(major));
        response.setSafes(java.util.Arrays.asList(school));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        VolunteerRecommendListResponse.BaseData baseData = new VolunteerRecommendListResponse.BaseData();
        baseData.setNeed_count(45);
        java.util.Map<String, Integer> targetCountMap = new java.util.HashMap<String, Integer>();
        targetCountMap.put("sprints_count", 12);
        targetCountMap.put("safes_count", 18);
        targetCountMap.put("protects_count", 15);
        baseData.setThree_target_count_map(targetCountMap);
        response.setBaseData(baseData);
        com.ytell.zhiyuan.model.dto.CreateSessionReq userScoreDetail = new com.ytell.zhiyuan.model.dto.CreateSessionReq();
        com.ytell.zhiyuan.model.dto.CreateSessionReq.StrategyType strategyType = new com.ytell.zhiyuan.model.dto.CreateSessionReq.StrategyType();
        strategyType.setCode("aggressive");
        strategyType.setName("激进型");
        userScoreDetail.setStrategyType(strategyType);
        response.setUserScoreDetail(userScoreDetail);
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());

        assertEquals(Integer.valueOf(1), state.getCandidatePoolState().getSummary().getTotal());
        assertFalse(state.getStaleFlags().getCandidatePool());
        assertFalse(state.getStaleFlags().getRecommendationOverlay());
        assertEquals(Integer.valueOf(45), state.getCandidatePoolState().getRequiredCount());
        assertEquals(Integer.valueOf(18), state.getCandidatePoolState().getRequiredTierCounts().get("冲"));
        assertEquals(Integer.valueOf(13), state.getCandidatePoolState().getRequiredTierCounts().get("稳"));
        assertEquals(Integer.valueOf(14), state.getCandidatePoolState().getRequiredTierCounts().get("保"));
        assertEquals(Integer.valueOf(1), state.getRecommendationOverlayState().getSummary().getTotal());
        assertEquals(Integer.valueOf(1), state.getRecommendationOverlayState().getSummary().getPreferredCount());

        ArgumentCaptor<ChatSessionExtraData> saveCaptor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService).save(saveCaptor.capture());
        ChatSessionExtraData saved = new ChatSessionExtraData();
        saved.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        saved.setDataValue(saveCaptor.getValue().getDataValue());
        reset(chatSessionExtraDataSharedService);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(saved);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        queryReq.getFilters().setProvinceNames(java.util.Arrays.asList("北京"));
        queryReq.getFilters().setMajorKeywords(java.util.Arrays.asList("计算机"));
        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);

        assertEquals(Integer.valueOf(1), queryRes.getTotal());
        assertEquals("北京邮电大学", queryRes.getItems().get(0).getSchoolName());
        assertEquals(Integer.valueOf(12), queryRes.getItems().get(0).getSchoolRank());
        assertEquals("080901", queryRes.getItems().get(0).getMajorCode());
        assertEquals("优选", queryRes.getItems().get(0).getMajorTier());
        assertEquals(Integer.valueOf(6), queryRes.getItems().get(0).getPlanNum());
        assertEquals(Integer.valueOf(5800), queryRes.getItems().get(0).getTuitionPerYear());
        assertEquals(Double.valueOf(82.5D), queryRes.getItems().get(0).getHotIndex());
        assertEquals(Double.valueOf(18.6D), queryRes.getItems().get(0).getSalaryAvg());
        assertEquals(Double.valueOf(86.2D), queryRes.getItems().get(0).getBaseScore());
        assertEquals(Double.valueOf(78.4D), queryRes.getItems().get(0).getIntentScore());
        assertEquals(Double.valueOf(81.8D), queryRes.getItems().get(0).getFinalScore());
        assertTrue(Boolean.TRUE.equals(queryRes.getItems().get(0).getPreferred()));
        assertEquals(2, queryRes.getItems().get(0).getSchoolRankTags().size());
        assertEquals(2, queryRes.getItems().get(0).getSchoolBasicTags().size());
        assertEquals(2, queryRes.getItems().get(0).getMajorPlanTags().size());
        assertNotNull(queryRes.getItems().get(0).getSchoolHistoryScores());
        assertNotNull(queryRes.getItems().get(0).getMajorHistoryScores());
    }

    @Test
    void shouldQueryCandidatePoolWithStoredItemsWhenOverlayRefreshFails() {
        bindPlanningStateStore(17L);
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(17L);
        state.setVersion(220);
        state.getStaleFlags().setRecommendationOverlay(true);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.major.name());
        candidatePoolState.getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "会计学", 62D, 81D, 62D, false));
        candidatePoolState.getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "冲", "计算机科学与技术", 35D, 90D, 35D, false));
        state.setCandidatePoolState(candidatePoolState);
        saveStateToStore(17L, state);
        when(volunteerBizService.recommendVolunteerList(1L, 17L, false, false))
                .thenThrow(new RuntimeException("rank unavailable"));

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        queryReq.getFilters().setTiers(java.util.Arrays.asList("稳", "保"));
        queryReq.getFilters().setMajorKeywords(java.util.Arrays.asList("会计"));
        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 17L, queryReq);

        assertEquals(Integer.valueOf(1), queryRes.getTotal());
        assertEquals("会计学", queryRes.getItems().get(0).getMajorName());
    }

    @Test
    void shouldReturnCandidateFilterOptionsWithStoredItemsWhenOverlayRefreshFails() {
        bindPlanningStateStore(17L);
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(17L);
        state.setVersion(220);
        state.getStaleFlags().setRecommendationOverlay(true);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.major.name());
        CandidateItemDTO candidate = buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "会计学", 62D, 81D, 62D, false);
        candidate.setProvinceName("山东");
        candidate.setCityName("济南");
        candidatePoolState.getItems().add(candidate);
        state.setCandidatePoolState(candidatePoolState);
        saveStateToStore(17L, state);
        when(volunteerBizService.recommendVolunteerList(1L, 17L, false, false))
                .thenThrow(new RuntimeException("rank unavailable"));

        CandidateFilterOptionsDTO options = planningStateService.getCandidateFilterOptions(1L, 17L);

        assertTrue(options.getProvinceNames().contains("山东"));
    }

    @Test
    void shouldGenerateInitialRecommendationAndPlanAdjustmentSkeleton() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "18"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "52"))));
        response.setProtects(java.util.Arrays.asList(buildSchool("ps3", "s3", "学校C", "河北", 3, buildMajorWithRatio("m3", "专业C", "81"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        PlanningStateDTO recommendationState = planningStateService.generateInitialRecommendation(
                1L, 1L, new InitialRecommendationGenerateReq());

        assertNotNull(recommendationState.getInitialRecommendationState());
        assertFalse(Boolean.TRUE.equals(recommendationState.getStaleFlags().getInitialRecommendation()));
        assertEquals(Integer.valueOf(3), recommendationState.getInitialRecommendationState().getSummary().getTotal());

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        assertNotNull(adjustmentState);
        assertEquals("ready", adjustmentState.getStatus());
        assertNotNull(adjustmentState.getAnalysis().getSummaryText());
        PlanningStateDTO storedState = planningStateService.getPlanningState(1L);
        assertFalse(Boolean.TRUE.equals(storedState.getStaleFlags().getPlanAdjustment()));
        assertEquals(adjustmentState.getAnalysis().getSummaryText(),
                storedState.getPlanAdjustmentState().getAnalysis().getSummaryText());
    }

    @Test
    void shouldPreferStoredStrategyTypeWhenBuildingRequiredTierCounts() {
        bindPlanningStateStore();

        CreateSessionReq storedScoreDetail = buildScoreDetail();
        CreateSessionReq.StrategyType strategyType = new CreateSessionReq.StrategyType();
        strategyType.setCode("traditional");
        strategyType.setName("保守型");
        storedScoreDetail.setStrategyType(strategyType);

        ChatSessionExtraData scoreData = new ChatSessionExtraData();
        scoreData.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        scoreData.setDataValue(com.alibaba.fastjson.JSONObject.toJSONString(storedScoreDetail));
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.USER_SCORE_KEY)))
                .thenReturn(scoreData);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(96, 68, 28, 0));
        response.setUserScoreDetail(buildScoreDetail());
        response.getUserScoreDetail().setStrategyType(null);
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "学校B", "天津", 1, buildMajorWithRatio("m2", "专业B", "40"))));
        response.setProtects(java.util.Arrays.asList(buildSchool("ps3", "s3", "学校C", "河北", 1, buildMajorWithRatio("m3", "专业C", "80"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());

        assertEquals(Integer.valueOf(19), state.getCandidatePoolState().getRequiredTierCounts().get("冲"));
        assertEquals(Integer.valueOf(38), state.getCandidatePoolState().getRequiredTierCounts().get("稳"));
        assertEquals(Integer.valueOf(39), state.getCandidatePoolState().getRequiredTierCounts().get("保"));
    }

    @Test
    void shouldFallbackToCautiousStrategyWhenStrategyTypeMissing() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(45, 300, 400, 300));
        response.setUserScoreDetail(buildScoreDetail());
        response.getUserScoreDetail().setStrategyType(null);
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "学校B", "天津", 1, buildMajorWithRatio("m2", "专业B", "60"))));
        response.setProtects(java.util.Arrays.asList(buildSchool("ps3", "s3", "学校C", "河北", 1, buildMajorWithRatio("m3", "专业C", "90"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());

        assertEquals(Integer.valueOf(13), state.getCandidatePoolState().getRequiredTierCounts().get("冲"));
        assertEquals(Integer.valueOf(13), state.getCandidatePoolState().getRequiredTierCounts().get("稳"));
        assertEquals(Integer.valueOf(19), state.getCandidatePoolState().getRequiredTierCounts().get("保"));
    }

    @Test
    void shouldFallbackToDefaultPlanCountWhenNeedCountMissing() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(0, 300, 400, 300));
        response.setUserScoreDetail(buildScoreDetail());
        response.getUserScoreDetail().setStrategyType(null);
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "学校B", "天津", 1, buildMajorWithRatio("m2", "专业B", "60"))));
        response.setProtects(java.util.Arrays.asList(buildSchool("ps3", "s3", "学校C", "河北", 1, buildMajorWithRatio("m3", "专业C", "90"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        PlanningStateDTO state = planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());

        assertEquals(Integer.valueOf(13), state.getCandidatePoolState().getRequiredTierCounts().get("冲"));
        assertEquals(Integer.valueOf(13), state.getCandidatePoolState().getRequiredTierCounts().get("稳"));
        assertEquals(Integer.valueOf(19), state.getCandidatePoolState().getRequiredTierCounts().get("保"));
    }


    @Test
    void shouldAnalyzePlanAdjustmentByUnitInMajorGroupMode() {
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

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "52"));
        sprintGroup.setEnroll_ratio("40");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "52"),
                buildMajorWithRatio("m2", "专业A2", "45"),
                buildMajorWithRatio("m3", "专业A3", "35")
        ));

        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "河南", 1,
                buildMajorWithRatio("m4", "专业B1", "70"));
        safeGroup.setEnroll_ratio("65");
        safeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业B1", "70"),
                buildMajorWithRatio("m5", "专业B2", "63"),
                buildMajorWithRatio("m6", "专业B3", "60")
        ));

        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps3", "s3", "专业组C", "河南", 1,
                buildMajorWithRatio("m7", "专业C1", "86"));
        protectGroup.setEnroll_ratio("82");
        protectGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m7", "专业C1", "86"),
                buildMajorWithRatio("m8", "专业C2", "80")
        ));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Arrays.asList(protectGroup));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m4", "ps2_m5"));
        planningStateService.selectDraftItems(1L, selectReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("draft");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        java.util.Map<String, Boolean> ruleHits = adjustmentState.getAnalysis().getRules().stream()
                .collect(java.util.stream.Collectors.toMap(
                        rule -> rule.getRuleCode(),
                        rule -> Boolean.TRUE.equals(rule.getHit()),
                        (left, right) -> left,
                        java.util.LinkedHashMap::new));

        assertFalse(Boolean.TRUE.equals(ruleHits.get("count_validation")));
        assertFalse(Boolean.TRUE.equals(ruleHits.get("unit_major_count_validation")));
        assertFalse(Boolean.TRUE.equals(ruleHits.get("group_inner_safety_guard")));
        assertFalse(adjustmentState.getSuggestions().getAddSuggestions().stream()
                .anyMatch(item -> "count_validation".equals(item.getRuleCode())));
    }


    @Test
    void shouldRunReviewByUnitInMajorGroupMode() {
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

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "50"));
        sprintGroup.setEnroll_ratio("42");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "50"),
                buildMajorWithRatio("m2", "专业A2", "44"),
                buildMajorWithRatio("m3", "专业A3", "36")
        ));

        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps2", "s2", "专业组B", "河南", 1,
                buildMajorWithRatio("m4", "专业B1", "83"));
        protectGroup.setEnroll_ratio("78");
        protectGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业B1", "83"),
                buildMajorWithRatio("m5", "专业B2", "80"),
                buildMajorWithRatio("m6", "专业B3", "70")
        ));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Collections.emptyList());
        response.setProtects(java.util.Arrays.asList(protectGroup));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m4", "ps2_m5"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);

        java.util.Map<String, Boolean> ruleHits = reviewState.getChecks().stream()
                .collect(java.util.stream.Collectors.toMap(
                        ReviewCheckDTO::getCode,
                        check -> Boolean.TRUE.equals(check.getPassed()),
                        (left, right) -> left,
                        java.util.LinkedHashMap::new));

        assertTrue(Boolean.TRUE.equals(ruleHits.get("count_validation")));
        assertTrue(Boolean.TRUE.equals(ruleHits.get("group_inner_safety_guard")));
        assertFalse(reviewState.getCompensationPreview().getActions().stream()
                .anyMatch(action -> "count_validation".equals(action.getSourceCheckCode())));
    }

    @Test
    void shouldWarnGroupInnerSafetyGuardWhenMajorGroupHasNoSafetyMajor() {
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

        VolunteerRecommendListResponse.VolunteerSchool weakSafeGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "38"));
        weakSafeGroup.setEnroll_ratio("45");
        weakSafeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "38"),
                buildMajorWithRatio("m2", "专业A2", "35"),
                buildMajorWithRatio("m3", "专业A3", "30")
        ));

        VolunteerRecommendListResponse.VolunteerSchool normalGroup = buildSchool("ps2", "s2", "专业组B", "河南", 1,
                buildMajorWithRatio("m4", "专业B1", "85"));
        normalGroup.setEnroll_ratio("75");
        normalGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业B1", "85"),
                buildMajorWithRatio("m5", "专业B2", "79"),
                buildMajorWithRatio("m6", "专业B3", "70")
        ));

        response.setSprints(java.util.Arrays.asList(weakSafeGroup));
        response.setSafes(java.util.Arrays.asList(normalGroup));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m4", "ps2_m5"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);
        ReviewCheckDTO check = reviewState.getChecks().stream()
                .filter(item -> "group_inner_safety_guard".equals(item.getCode()))
                .findFirst()
                .orElse(null);

        assertNotNull(check);
        assertFalse(Boolean.TRUE.equals(check.getPassed()));
        assertEquals("warn", check.getLevel());
        assertTrue(check.getAffectedVolunteerIds().contains("ps1_m1"));
        assertTrue(check.getAffectedVolunteerIds().contains("ps1_m2"));
        assertFalse(check.getAffectedVolunteerIds().contains("ps2_m4"));
        assertEquals("major_group_inner", check.getScopeKind());
        assertEquals("adjust_major_group_inner_safety", check.getDefaultFixStrategy());
    }

    @Test
    void shouldWarnWhenMajorGroupSafetyMajorDiffersFromIntent() {
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

        VolunteerRecommendListResponse.VolunteerMajor intentMajor = buildMajorWithIntentScore("m1", "专业A1", "50", 60D);
        VolunteerRecommendListResponse.VolunteerMajor safetyMajor = buildMajorWithIntentScore("m2", "专业A2", "55", 15D);
        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1, intentMajor);
        sprintGroup.setEnroll_ratio("55");
        sprintGroup.setMajors(java.util.Arrays.asList(
                intentMajor,
                safetyMajor,
                buildMajorWithIntentScore("m3", "专业A3", "30", 8D)
        ));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2"));
        planningStateService.selectDraftItems(1L, selectReq);
        PlanningStateDTO orderedState = planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        ReviewCheckDTO reviewCheck = ReflectionTestUtils.invokeMethod(
                planningStateService,
                "reviewMajorGroupSafetyIntentAlignment",
                orderedState);
        assertNotNull(reviewCheck);
        assertFalse(Boolean.TRUE.equals(reviewCheck.getPassed()));
        assertTrue(reviewCheck.getSummary().contains("非意向专业托底"));
        assertTrue(reviewCheck.getAffectedVolunteerIds().contains("ps1_m2"));

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("ordered");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);
        assertTrue(adjustmentState.getAnalysis().getRules().stream()
                .anyMatch(rule -> "major_group_safety_intent_alignment".equals(rule.getRuleCode())
                        && Boolean.TRUE.equals(rule.getHit())));
        assertFalse(adjustmentState.getSuggestions().getAddSuggestions().stream()
                .anyMatch(item -> "major_group_safety_intent_alignment".equals(item.getRuleCode())));
    }




    @Test
    void shouldNotExposeGroupInnerSafetyGuardInMajorGroupPlanAdjustment() {
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

        VolunteerRecommendListResponse.VolunteerSchool weakSafeGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "38"));
        weakSafeGroup.setEnroll_ratio("45");
        weakSafeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "38"),
                buildMajorWithRatio("m2", "专业A2", "35"),
                buildMajorWithRatio("m3", "专业A3", "30")
        ));

        VolunteerRecommendListResponse.VolunteerSchool normalGroup = buildSchool("ps2", "s2", "专业组B", "河南", 1,
                buildMajorWithRatio("m4", "专业B1", "85"));
        normalGroup.setEnroll_ratio("75");
        normalGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业B1", "85"),
                buildMajorWithRatio("m5", "专业B2", "79"),
                buildMajorWithRatio("m6", "专业B3", "70")
        ));

        response.setSprints(java.util.Arrays.asList(weakSafeGroup));
        response.setSafes(java.util.Arrays.asList(normalGroup));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m4", "ps2_m5"));
        planningStateService.selectDraftItems(1L, selectReq);

        PlanAdjustmentAnalyzeReq analyzeReq = new PlanAdjustmentAnalyzeReq();
        analyzeReq.setTarget("draft");
        PlanAdjustmentStateDTO adjustmentState = planningStateService.analyzePlanAdjustment(1L, 1L, analyzeReq);

        assertFalse(adjustmentState.getAnalysis().getRules().stream()
                .anyMatch(rule -> "group_inner_safety_guard".equals(rule.getRuleCode())));
        assertFalse(adjustmentState.getSuggestions().getAddSuggestions().stream()
                .anyMatch(item -> "group_inner_safety_guard".equals(item.getRuleCode())));
    }

    @Test
    void shouldPreviewCompensationByUnitInMajorGroupMode() {
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

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "50"));
        sprintGroup.setEnroll_ratio("40");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "50"),
                buildMajorWithRatio("m2", "专业A2", "43")
        ));

        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1,
                buildMajorWithRatio("m3", "专业B1", "68"));
        safeGroup.setEnroll_ratio("60");
        safeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m3", "专业B1", "68"),
                buildMajorWithRatio("m4", "专业B2", "64")
        ));

        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps3", "s3", "专业组C", "河南", 1,
                buildMajorWithRatio("m5", "专业C1", "88"));
        protectGroup.setEnroll_ratio("80");
        protectGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m5", "专业C1", "88"),
                buildMajorWithRatio("m6", "专业C2", "84")
        ));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Arrays.asList(protectGroup));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m3", "ps2_m4"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        CompensationPreviewDTO preview = planningStateService.runReview(1L, 1L).getCompensationPreview();

        CompensationActionDTO countAction = preview.getActions().stream()
                .filter(action -> "count_validation".equals(action.getSourceCheckCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(countAction);
        assertEquals(1, countAction.getUnitIds().size());
        assertTrue(countAction.getUnitIds().contains("ps3"));
        assertEquals(2, countAction.getVolunteerIds().size());
        assertTrue(countAction.getVolunteerIds().contains("ps3_m5"));
        assertTrue(countAction.getVolunteerIds().contains("ps3_m6"));
    }

    @Test
    void shouldReturnAffectedUnitIdsForProbabilityGapInMajorGroupReview() {
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

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "40"));
        sprintGroup.setEnroll_ratio("20");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "40"),
                buildMajorWithRatio("m2", "专业A2", "32")
        ));

        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1,
                buildMajorWithRatio("m3", "专业B1", "60"));
        safeGroup.setEnroll_ratio("45");
        safeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m3", "专业B1", "60"),
                buildMajorWithRatio("m4", "专业B2", "50")
        ));

        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps3", "s3", "专业组C", "河南", 1,
                buildMajorWithRatio("m5", "专业C1", "95"));
        protectGroup.setEnroll_ratio("80");
        protectGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m5", "专业C1", "95"),
                buildMajorWithRatio("m6", "专业C2", "88")
        ));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Arrays.asList(protectGroup));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m3", "ps2_m4", "ps3_m5", "ps3_m6"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);

        ReviewCheckDTO probabilityGapCheck = reviewState.getChecks().stream()
                .filter(check -> "probability_gap".equals(check.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(probabilityGapCheck);
        assertFalse(probabilityGapCheck.getPassed());
        assertEquals("录取率梯度断层", probabilityGapCheck.getLabel());
        assertEquals("structure_risk", probabilityGapCheck.getCategory());
        assertEquals("structure", probabilityGapCheck.getScopeKind());
        assertEquals("preview_fixable", probabilityGapCheck.getFixability());
        assertEquals("fill_probability_gap", probabilityGapCheck.getDefaultFixStrategy());
        assertTrue(probabilityGapCheck.getSupportedFixStrategies().contains("fill_probability_gap"));
        assertEquals(java.util.Arrays.asList("ps1", "ps2"), probabilityGapCheck.getAffectedUnitIds());
        assertTrue(probabilityGapCheck.getAffectedVolunteerIds().contains("ps1_m1"));
        assertTrue(probabilityGapCheck.getAffectedVolunteerIds().contains("ps2_m3"));
    }

    @Test
    void shouldGenerateFixProposalFromCountCompensation() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = buildCountFixProposalResponse();
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        prepareCountFixProposalState();

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        assertNotNull(proposalState.getSourceVersion());
        assertNotNull(proposalState.getSourceReviewVersion());
        assertEquals(proposalState.getSourceVersion(), proposalState.getSourceVersionGuard());
        FixProposalDTO countProposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("count_validation"))
                .findFirst()
                .orElse(null);
        assertNotNull(countProposal);
        assertEquals(proposalState.getSourceVersionGuard(), countProposal.getSourceVersionGuard());
        assertEquals(proposalState.getSourceReviewVersion(), countProposal.getSourceReviewVersion());
        assertEquals("fill_missing_count", countProposal.getStrategy());
        assertEquals("ready", countProposal.getStatus());
        assertTrue(countProposal.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getActionType())));
        assertTrue(countProposal.getDryRunResult().getAddUnitCount() > 0);
        assertTrue(countProposal.getDryRunResult().getAddVolunteerCount() > 0);
        assertTrue(countProposal.getRequiresConfirmation());
    }

    @Test
    void shouldBlockCountFixProposalWhenNoCandidateCanSatisfyShortage() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(2);
        CandidateItemDTO selected = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "稳", "专业A", 55D, 80D, 55D, false);
        state.getCandidatePoolState().getItems().add(selected);
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "稳"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "稳", 1));
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("count_validation"))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("cannot_satisfy", proposal.getStrategy());
        assertEquals("blocked", proposal.getStatus());
        assertEquals("blocked", proposal.getDryRunResult().getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertTrue(proposal.getActions().isEmpty());
        assertTrue(proposal.getBlockingReason().contains("无法补齐目标志愿数量"));
        assertEquals(java.util.Collections.singletonList("candidate_pool_insufficient"), proposal.getBlockingReasonCodes());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("candidate_pool", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("candidate_pool_insufficient", proposal.getCandidateShortages().get(0).getReasonCode());
        assertEquals(Integer.valueOf(2), proposal.getCandidateShortages().get(0).getRequiredCount());
        assertEquals(Integer.valueOf(1), proposal.getCandidateShortages().get(0).getCurrentCount());
        assertEquals(Integer.valueOf(1), proposal.getCandidateShortages().get(0).getShortageCount());
        assertTrue(proposal.getDryRunResult().getMessage().contains("无法补齐目标志愿数量"));
    }

    @Test
    void shouldGenerateReadyUserGoalFixProposalThroughServiceWithoutApplying() {
        AtomicReference<ChatSessionExtraData> planningStateRef = bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(9);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "临床医学", 55D, 80D, 55D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "汉语言文学", 60D, 70D, 60D, false));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "临床医学", "稳", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "汉语言文学", "稳", 2));
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("only_keep_scope");
        req.setSourceVersionGuard(9);
        UserGoalFixProposalReq.ScopeDTO scope = new UserGoalFixProposalReq.ScopeDTO();
        scope.setEntityType("major");
        scope.setNormalizedName("临床医学");
        req.getTargetScopes().add(scope);

        FixProposalStateDTO proposalState = planningStateService.generateUserGoalFixProposals(1L, req);

        assertEquals("user_goal", proposalState.getProposalSource());
        assertEquals("ready", proposalState.getStatus());
        FixProposalDTO proposal = proposalState.getProposals().get(0);
        assertEquals("user_goal", proposal.getProposalSource());
        assertEquals("only_keep_scope", proposal.getStrategy());
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("ps2_m2", proposal.getActions().get(0).getRemoveVolunteerIds().get(0));
        verify(chatSessionExtraDataSharedService, times(1)).save(any(ChatSessionExtraData.class));
        PlanningStateDTO storedState = JSONObject.parseObject(
                planningStateRef.get().getDataValue(), PlanningStateDTO.class);
        assertEquals(2, storedState.getOrderedPlanState().getItems().size());
        assertEquals("ps1_m1", storedState.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m2", storedState.getOrderedPlanState().getItems().get(1).getVolunteerId());
    }

    @Test
    void shouldApplyUserGoalOnlyKeepProposalWithVersionGuard() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(9);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "临床医学", 55D, 80D, 55D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "汉语言文学", 60D, 70D, 60D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps3_m3", "ps3", "s3", "学校C", "稳", "临床医学", 58D, 75D, 58D, false));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "临床医学", "稳", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "汉语言文学", "稳", 2));
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = userGoalReq("only_keep_scope", 9, userGoalScope("major", "临床医学"), false);
        req.setUserOriginalText("只保留临床医学");
        FixProposalDTO proposal = planningStateService.generateUserGoalFixProposals(1L, req).getProposals().get(0);
        assertEquals("ready", proposal.getStatus());

        FixProposalApplyReq applyReq = userGoalApplyReq(proposal, req);
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertEquals("only_keep_scope", res.getRepairReport().getStrategy());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getRemovedVolunteerCount());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getAddedVolunteerCount());
        Set<String> draftIds = res.getState().getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertTrue(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps3_m3"));
        assertFalse(draftIds.contains("ps2_m2"));
        assertTrue(res.getState().getOperationLogs().stream()
                .anyMatch(log -> "user_goal_apply".equals(log.getType())));
    }

    @Test
    void shouldApplyUserGoalProposalByStrategyWhenRegeneratedProposalIdChanges() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(9);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "临床医学", 55D, 80D, 55D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "汉语言文学", 60D, 70D, 60D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps3_m3", "ps3", "s3", "学校C", "稳", "临床医学", 58D, 75D, 58D, false));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "临床医学", "稳", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "汉语言文学", "稳", 2));
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = userGoalReq("only_keep_scope", 9, userGoalScope("major", "临床医学"), false);
        req.setUserOriginalText("只保留临床医学");
        FixProposalDTO proposal = planningStateService.generateUserGoalFixProposals(1L, req).getProposals().get(0);
        FixProposalApplyReq applyReq = userGoalApplyReq(proposal, req);
        applyReq.setProposalId("ugp-stale-id-from-previous-preview");
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);

        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertEquals("only_keep_scope", res.getProposal().getStrategy());
        assertEquals(proposal.getProposalId(), res.getProposal().getProposalId());
        Set<String> draftIds = res.getState().getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertTrue(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps3_m3"));
        assertFalse(draftIds.contains("ps2_m2"));
    }

    @Test
    void shouldApplyUserGoalMustIncludeProposal() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(5);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "汉语言文学", 55D, 80D, 55D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "临床医学", 60D, 90D, 60D, false));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "汉语言文学", "稳"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "汉语言文学", "稳", 1));
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = userGoalReq("must_include_scope", 5, userGoalScope("major", "临床医学"), false);
        req.setUserOriginalText("方案里必须有临床医学");
        FixProposalDTO proposal = planningStateService.generateUserGoalFixProposals(1L, req).getProposals().get(0);
        assertEquals("ready", proposal.getStatus());
        assertEquals("add_volunteers", proposal.getActions().get(0).getActionType());

        FixProposalApplyReq applyReq = userGoalApplyReq(proposal, req);
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        Set<String> draftIds = res.getState().getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertTrue(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps2_m2"));
        assertEquals(Integer.valueOf(0), res.getRepairReport().getRemovedVolunteerCount());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getAddedVolunteerCount());
    }

    @Test
    void shouldApplyUserGoalExcludeProposal() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(6);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "金融学", 55D, 80D, 55D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "汉语言文学", 60D, 70D, 60D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps3_m3", "ps3", "s3", "学校C", "稳", "法学", 58D, 75D, 58D, false));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "金融学", "稳", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "汉语言文学", "稳", 2));
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = userGoalReq("exclude_scope", 6, userGoalScope("major", "金融学"), true);
        req.setUserOriginalText("不学金融");
        FixProposalDTO proposal = planningStateService.generateUserGoalFixProposals(1L, req).getProposals().get(0);
        assertEquals("ready", proposal.getStatus());

        FixProposalApplyReq applyReq = userGoalApplyReq(proposal, req);
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        Set<String> draftIds = res.getState().getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertFalse(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps2_m2"));
        assertTrue(draftIds.contains("ps3_m3"));
        assertEquals(Integer.valueOf(1), res.getRepairReport().getRemovedVolunteerCount());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getAddedVolunteerCount());
    }

    @Test
    void shouldApplyUserGoalTuitionBudgetProposal() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        CandidateItemDTO expensive = buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "金融学", 55D, 80D, 55D, false);
        expensive.setTuitionPerYear(30000);
        CandidateItemDTO kept = buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "汉语言文学", 60D, 70D, 60D, false);
        kept.setTuitionPerYear(12000);
        CandidateItemDTO affordable = buildCandidateItem(
                "ps3_m3", "ps3", "s3", "学校C", "稳", "法学", 58D, 75D, 58D, false);
        affordable.setTuitionPerYear(18000);
        state.getCandidatePoolState().getItems().add(expensive);
        state.getCandidatePoolState().getItems().add(kept);
        state.getCandidatePoolState().getItems().add(affordable);
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "金融学", "稳", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "汉语言文学", "稳", 2));
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("tuition_budget_scope");
        req.setSourceVersionGuard(7);
        req.setUserOriginalText("学费最好控制在两万以内");
        req.setContext(java.util.Collections.singletonMap("maxTuitionPerYear", 20000));
        FixProposalDTO proposal = planningStateService.generateUserGoalFixProposals(1L, req).getProposals().get(0);
        assertEquals("ready", proposal.getStatus());

        FixProposalApplyReq applyReq = userGoalApplyReq(proposal, req);
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertEquals("tuition_budget_scope", res.getRepairReport().getStrategy());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getRemovedVolunteerCount());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getAddedVolunteerCount());
        Set<String> draftIds = res.getState().getDraftPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertFalse(draftIds.contains("ps1_m1"));
        assertTrue(draftIds.contains("ps2_m2"));
        assertTrue(draftIds.contains("ps3_m3"));
    }

    @Test
    void shouldApplyUserGoalOnlyKeepProposalInMajorGroupMode() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(8);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.majorGroup.name());
        state.getCandidatePoolState().setRequiredCount(1);
        CandidateItemDTO current = buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A第101组", "稳", "工商管理类", 55D, 80D, 55D, false);
        CandidateItemDTO replacement = buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B第102组", "稳", "临床医学", 58D, 90D, 58D, false);
        state.getCandidatePoolState().getItems().add(current);
        state.getCandidatePoolState().getItems().add(replacement);
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A第101组", "工商管理类", "稳", 1));
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("ps1");
        unit.setSchoolName("学校A第101组");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId("ps1_m1");
        major.setMajorName("工商管理类");
        unit.getMajorItems().add(major);
        state.getOrderedPlanState().getUnits().add(unit);
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = userGoalReq("only_keep_scope", 8, userGoalScope("major", "临床医学"), false);
        req.setUserOriginalText("只保留医学");
        FixProposalDTO proposal = planningStateService.generateUserGoalFixProposals(1L, req).getProposals().get(0);
        assertEquals("ready", proposal.getStatus());

        FixProposalApplyReq applyReq = userGoalApplyReq(proposal, req);
        applyReq.setRegenerateOrderedPlan(true);
        applyReq.setRerunReview(false);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        Set<String> orderedIds = res.getState().getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertFalse(orderedIds.contains("ps1_m1"));
        assertTrue(orderedIds.contains("ps2_m2"));
        assertEquals(1, res.getState().getOrderedPlanState().getUnits().size());
        assertEquals("ps2", res.getState().getOrderedPlanState().getUnits().get(0).getUnitId());
    }

    @Test
    void shouldRejectExpiredUserGoalFixProposalApply() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(9);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps1_m1", "ps1", "s1", "学校A", "稳", "临床医学", 55D, 80D, 55D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem(
                "ps2_m2", "ps2", "s2", "学校B", "稳", "汉语言文学", 60D, 70D, 60D, false));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "临床医学", "稳", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "汉语言文学", "稳", 2));
        saveStateToStore(1L, state);

        UserGoalFixProposalReq req = userGoalReq("only_keep_scope", 9, userGoalScope("major", "临床医学"), false);
        FixProposalDTO proposal = planningStateService.generateUserGoalFixProposals(1L, req).getProposals().get(0);
        FixProposalApplyReq applyReq = userGoalApplyReq(proposal, req);
        applyReq.setSourceVersionGuard(8);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> planningStateService.applyFixProposal(1L, 1L, applyReq));
        assertEquals(409, ex.getStatus());
    }

    @Test
    void shouldGenerateCurrentPlanReasonWhenCountExceedsRequiredCount() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(2);
        CandidateItemDTO itemA = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "稳", "专业A", 55D, 80D, 55D, false);
        CandidateItemDTO itemB = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "稳", "专业B", 60D, 80D, 60D, false);
        CandidateItemDTO itemC = buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "保", "专业C", 75D, 80D, 75D, false);
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(itemA, itemB, itemC));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "稳"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "稳"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps3_m3", "学校C", "专业C", "保"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "稳", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "稳", 2));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps3_m3", "学校C", "专业C", "保", 3));
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        ReviewCheckDTO check = planningStateService.getPlanningState(1L).getReviewState().getChecks().stream()
                .filter(item -> "count_validation".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(check);
        assertEquals("count_over_limit", check.getReasonCode());

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("count_validation"))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("cannot_satisfy", proposal.getStrategy());
        assertEquals("blocked", proposal.getStatus());
        assertEquals(java.util.Collections.singletonList("count_over_limit"), proposal.getBlockingReasonCodes());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("current_plan", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("count_over_limit", proposal.getCandidateShortages().get(0).getReasonCode());
        assertEquals(Integer.valueOf(2), proposal.getCandidateShortages().get(0).getRequiredCount());
        assertEquals(Integer.valueOf(3), proposal.getCandidateShortages().get(0).getCurrentCount());
        assertNull(proposal.getCandidateShortages().get(0).getShortageCount());
        assertNull(proposal.getCandidateShortages().get(0).getAvailableCount());
    }

    @Test
    void shouldBackfillMajorGroupCountReasonFromOrderedItemsWhenUnitsAreMissing() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getStaleFlags().setReview(false);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.majorGroup.name());
        state.getCandidatePoolState().setRequiredCount(2);
        CandidateItemDTO itemA = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A第101组", "冲", "专业A", 20D, 90D, 20D, false);
        CandidateItemDTO itemB = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B第102组", "稳", "专业B", 55D, 80D, 55D, false);
        CandidateItemDTO itemC = buildCandidateItem("ps3_m3", "ps3", "s3", "学校C第103组", "保", "专业C", 80D, 70D, 80D, false);
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(itemA, itemB, itemC));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A第101组", "专业A", "冲", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B第102组", "专业B", "稳", 2));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps3_m3", "学校C第103组", "专业C", "保", 3));

        ReviewStateDTO reviewState = buildFailedReviewState("count_validation", "当前志愿数量多于官方要求", "structure", "structure_risk");
        state.setReviewState(reviewState);
        saveStateToStore(1L, state);

        PlanningStateDTO normalized = planningStateService.getPlanningState(1L);

        ReviewCheckDTO check = normalized.getReviewState().getChecks().stream()
                .filter(item -> "count_validation".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(check);
        assertEquals("count_over_limit", check.getReasonCode());
    }

    @Test
    void shouldAttributeFixProposalShortageToConfirmedHardConstraints() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().getRequiredTierCounts().put("冲", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("稳", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("保", 1);
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("河北");

        CandidateItemDTO sprint = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 20D, 80D, 20D, false);
        sprint.setProvinceName("北京");
        CandidateItemDTO safe = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "稳", "专业B", 50D, 70D, 50D, false);
        safe.setProvinceName("天津");
        CandidateItemDTO excludedProtect = buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "保", "专业C", 80D, 90D, 80D, false);
        excludedProtect.setProvinceName("河北");
        state.getCandidatePoolState().getItems().add(sprint);
        state.getCandidatePoolState().getItems().add(safe);
        state.getCandidatePoolState().getItems().add(excludedProtect);
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "稳"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "稳", 2));
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("count_validation"))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("hard_constraints", proposal.getCandidateShortages().get(0).getScope());
        assertEquals(Integer.valueOf(0), proposal.getCandidateShortages().get(0).getAvailableCount());
        assertTrue(proposal.getCandidateShortages().get(0).getMessage().contains("报考条件过滤后数量不足"));
    }

    @Test
    void shouldAttributeTierRatioShortageToConfirmedHardConstraints() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(4);
        state.getCandidatePoolState().getRequiredTierCounts().put("冲", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("稳", 2);
        state.getCandidatePoolState().getRequiredTierCounts().put("保", 1);
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("河北");

        CandidateItemDTO sprint1 = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 15D, 92D, 15D, false);
        sprint1.setProvinceName("北京");
        CandidateItemDTO sprint2 = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "冲", "专业B", 18D, 90D, 18D, false);
        sprint2.setProvinceName("天津");
        CandidateItemDTO safe1 = buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "稳", "专业C", 50D, 80D, 50D, false);
        safe1.setProvinceName("北京");
        CandidateItemDTO safe2 = buildCandidateItem("ps4_m4", "ps4", "s4", "学校D", "稳", "专业D", 55D, 78D, 55D, false);
        safe2.setProvinceName("天津");
        CandidateItemDTO excludedProtect = buildCandidateItem("ps5_m5", "ps5", "s5", "学校E", "保", "专业E", 82D, 70D, 82D, false);
        excludedProtect.setProvinceName("河北");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(sprint1, sprint2, safe1, safe2, excludedProtect));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps3_m3", "学校C", "专业C", "稳"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps4_m4", "学校D", "专业D", "稳"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "冲", 2));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps3_m3", "学校C", "专业C", "稳", 3));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps4_m4", "学校D", "专业D", "稳", 4));
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("ratio_distribution"))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertEquals(java.util.Collections.singletonList("tier_candidate_insufficient"), proposal.getBlockingReasonCodes());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("hard_constraints", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("保", proposal.getCandidateShortages().get(0).getTargetTier());
        assertEquals(Integer.valueOf(0), proposal.getCandidateShortages().get(0).getAvailableCount());
        assertTrue(proposal.getCandidateShortages().get(0).getMessage().contains("报考条件过滤后数量不足"));
    }

    @Test
    void shouldAttributeProbabilityGapShortageToConfirmedHardConstraints() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(2);
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("河北");

        CandidateItemDTO low = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 10D, 92D, 10D, false);
        low.setProvinceName("北京");
        CandidateItemDTO high = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "保", "专业B", 90D, 70D, 90D, false);
        high.setProvinceName("天津");
        CandidateItemDTO excludedMiddle = buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "稳", "专业C", 50D, 80D, 50D, false);
        excludedMiddle.setProvinceName("河北");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(low, high, excludedMiddle));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "保"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "保", 2));
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("probability_gap"))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertEquals(java.util.Collections.singletonList("probability_gap_candidate_insufficient"), proposal.getBlockingReasonCodes());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("hard_constraints", proposal.getCandidateShortages().get(0).getScope());
        assertEquals(Integer.valueOf(0), proposal.getCandidateShortages().get(0).getAvailableCount());
        assertTrue(proposal.getCandidateShortages().get(0).getMessage().contains("报考条件过滤后数量不足"));
    }

    @Test
    void shouldExplainTierRatioShortageAsCandidatePoolScopeWhenNoTargetTierCandidateExists() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getStaleFlags().setReview(false);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().getRequiredTierCounts().put("冲", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("稳", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("保", 1);

        CandidateItemDTO sprintA = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 12D, 90D, 12D, false);
        CandidateItemDTO sprintB = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "冲", "专业B", 18D, 88D, 18D, false);
        CandidateItemDTO safe = buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "稳", "专业C", 55D, 80D, 55D, false);
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(sprintA, sprintB, safe));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps3_m3", "学校C", "专业C", "稳"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "冲", 2));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps3_m3", "学校C", "专业C", "稳", 3));
        state.setReviewState(buildFailedReviewState("ratio_distribution", "冲稳保配比不均衡", "structure", "structure_risk"));
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("ratio_distribution"))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertEquals("cannot_satisfy", proposal.getStrategy());
        assertFalse(proposal.getRequiresConfirmation());
        assertTrue(proposal.getActions().isEmpty());
        assertEquals(java.util.Collections.singletonList("tier_candidate_insufficient"), proposal.getBlockingReasonCodes());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("candidate_pool", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("tier_candidate_insufficient", proposal.getCandidateShortages().get(0).getReasonCode());
        assertEquals("保", proposal.getCandidateShortages().get(0).getTargetTier());
        assertEquals(Integer.valueOf(1), proposal.getCandidateShortages().get(0).getRequiredCount());
        assertEquals(Integer.valueOf(0), proposal.getCandidateShortages().get(0).getCurrentCount());
        assertEquals(Integer.valueOf(1), proposal.getCandidateShortages().get(0).getShortageCount());
        assertEquals(Integer.valueOf(0), proposal.getCandidateShortages().get(0).getAvailableCount());
        assertTrue(proposal.getCandidateShortages().get(0).getMessage().contains("当前可用于规划的候选池"));
    }

    @Test
    void shouldExplainProbabilityGapShortageAsCandidatePoolScopeWhenNoMiddleCandidateExists() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        state.getStaleFlags().setReview(false);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(2);

        CandidateItemDTO low = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 10D, 92D, 10D, false);
        CandidateItemDTO high = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "保", "专业B", 90D, 70D, 90D, false);
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(low, high));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "冲"));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "保"));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        state.getOrderedPlanState().getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "保", 2));
        ReviewStateDTO reviewState = buildFailedReviewState("probability_gap", "录取率梯度断层", "structure", "structure_risk");
        reviewState.getChecks().get(0).setAffectedVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2"));
        state.setReviewState(reviewState);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> item.getSourceCheckCodes().contains("probability_gap"))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertEquals("cannot_satisfy", proposal.getStrategy());
        assertFalse(proposal.getRequiresConfirmation());
        assertTrue(proposal.getActions().isEmpty());
        assertEquals(java.util.Collections.singletonList("probability_gap_candidate_insufficient"), proposal.getBlockingReasonCodes());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("candidate_pool", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("probability_gap_candidate_insufficient", proposal.getCandidateShortages().get(0).getReasonCode());
        assertEquals(Integer.valueOf(1), proposal.getCandidateShortages().get(0).getRequiredCount());
        assertEquals(Integer.valueOf(0), proposal.getCandidateShortages().get(0).getAvailableCount());
        assertTrue(proposal.getCandidateShortages().get(0).getMessage().contains("断层中间录取率候选不足"));
        assertTrue(proposal.getCandidateShortages().get(0).getMessage().contains("当前可用于规划的候选池"));
    }

    @Test
    void shouldRunReviewWorkflowAndReturnFixProposalsWithWorkspaceStatus() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = buildCountFixProposalResponse();
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);
        prepareCountFixProposalState();

        ReviewWorkflowRunRes res = planningStateService.runReviewWorkflow(1L, 1L);

        assertEquals("ready_to_confirm", res.getStatus());
        assertEquals(Long.valueOf(1L), res.getSessionId());
        assertNotNull(res.getReviewState());
        assertEquals("completed", res.getReviewState().getStatus());
        assertNotNull(res.getFixProposalState());
        assertTrue(res.getFixProposalState().getProposals().stream()
                .anyMatch(item -> "fill_missing_count".equals(item.getStrategy())
                        && "ready".equals(item.getStatus())));
        assertNotNull(res.getWorkflowStatus());
        assertEquals("has_risk", res.getWorkflowStatus().getReviewStatus());
        assertNotNull(res.getWorkspaceState());
        assertEquals(res.getSourceVersion(), res.getWorkspaceState().getVersion());
        assertFalse(Boolean.TRUE.equals(res.getWorkspaceState().getStaleFlags().getReview()));
    }

    @Test
    void shouldResolveFixProposalStateStatusFromProposalStatuses() {
        FixProposalDTO ready = new FixProposalDTO();
        ready.setStatus("ready");
        FixProposalDTO blocked = new FixProposalDTO();
        blocked.setStatus("blocked");
        FixProposalDTO preview = new FixProposalDTO();
        preview.setStatus("preview_only");
        FixProposalDTO info = new FixProposalDTO();
        info.setStatus("info");

        assertEquals("empty", RepairProposalStateBuilder.resolveStateStatus(java.util.Collections.emptyList()));
        assertEquals("ready", RepairProposalStateBuilder.resolveStateStatus(java.util.Arrays.asList(blocked, ready)));
        assertEquals("preview_only", RepairProposalStateBuilder.resolveStateStatus(java.util.Arrays.asList(blocked, preview)));
        assertEquals("blocked_or_info", RepairProposalStateBuilder.resolveStateStatus(java.util.Arrays.asList(blocked, info)));
    }

    @Test
    void shouldApplyFillMissingCountFixProposalWithVersionGuard() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = buildCountFixProposalResponse();
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        prepareCountFixProposalState();
        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO countProposal = proposalState.getProposals().stream()
                .filter(item -> "fill_missing_count".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(countProposal);

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(countProposal.getProposalId());
        applyReq.setSourceVersionGuard(countProposal.getSourceVersionGuard());
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertNotNull(res.getRepairReport());
        assertEquals("fill_missing_count", res.getRepairReport().getStrategy());
        assertEquals(countProposal.getProposalId(), res.getRepairReport().getProposalId());
        assertEquals(countProposal.getSourceVersionGuard(), res.getRepairReport().getSourceVersion());
        assertTrue(res.getRepairReport().getAddedVolunteerCount() > 0);
        assertFalse(res.getRepairReport().getActionDetails().isEmpty());
        assertTrue(res.getRepairReport().getActionDetails().stream()
                .anyMatch(item -> "fill_total_count".equals(item.getActionType())
                        || "fill_missing_count".equals(item.getActionType())));
        assertTrue(res.getRepairReport().getMessages().stream().anyMatch(message -> message.contains("已补充")));
        assertTrue(res.getState().getDraftPlanState().getUnits().stream()
                .anyMatch(unit -> "ps4".equals(unit.getUnitId())));
        assertTrue(res.getState().getDraftPlanState().getItems().stream()
                .anyMatch(item -> "ps4_m7".equals(item.getVolunteerId())));
        assertTrue(res.getState().getDraftPlanState().getItems().stream()
                .anyMatch(item -> "ps4_m8".equals(item.getVolunteerId())));
    }

    @Test
    void shouldRejectExpiredFixProposalApply() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = buildCountFixProposalResponse();
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        prepareCountFixProposalState();
        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO countProposal = proposalState.getProposals().stream()
                .filter(item -> "fill_missing_count".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(countProposal);

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(countProposal.getProposalId());
        applyReq.setSourceVersionGuard(countProposal.getSourceVersionGuard() - 1);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> planningStateService.applyFixProposal(1L, 1L, applyReq));
        assertEquals(409, ex.getStatus());
    }

    @Test
    void shouldRejectFixProposalApplyWhenReviewIsStale() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = buildCountFixProposalResponse();
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        prepareCountFixProposalState();
        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO countProposal = proposalState.getProposals().stream()
                .filter(item -> "fill_missing_count".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(countProposal);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);
        state.getStaleFlags().setReview(true);
        saveStateToStore(1L, state);

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(countProposal.getProposalId());
        applyReq.setSourceVersionGuard(countProposal.getSourceVersionGuard());

        BusinessException ex = assertThrows(BusinessException.class,
                () -> planningStateService.applyFixProposal(1L, 1L, applyReq));
        assertEquals(409, ex.getStatus());
        assertTrue(ex.getMessage().contains("审查结果已过期"));
    }

    @Test
    void shouldApplyReplaceRiskItemsFixProposalWithVersionGuard() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getStaleFlags().setReview(false);

        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary("当前方案包含高收费专业");
        check.setAffectedVolunteerIds(java.util.Arrays.asList("v1"));
        reviewState.setChecks(java.util.Arrays.asList(check));
        state.setReviewState(reviewState);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO riskCandidate = buildCandidateItem("v1", "ps1", "s1", "学校A", "稳", "高收费专业", 55D, 80D, 55D, false);
        riskCandidate.setTuitionPerYear(30000);
        riskCandidate.setMajorCategory("工商管理类");
        CandidateItemDTO replacementCandidate = buildCandidateItem("v2", "ps2", "s2", "学校B", "稳", "安全专业", 58D, 82D, 58D, false);
        replacementCandidate.setMajorCategory("工商管理类");
        candidatePoolState.getItems().add(riskCandidate);
        candidatePoolState.getItems().add(replacementCandidate);
        state.setCandidatePoolState(candidatePoolState);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("v1", "学校A", "高收费专业", "稳"));
        state.setDraftPlanState(draft);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "replace_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("ready", proposal.getStatus());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
        FixProposalActionDTO replaceAction = proposal.getActions().stream()
                .filter(action -> "replace_volunteers".equals(action.getActionType()))
                .findFirst()
                .orElse(null);
        assertNotNull(replaceAction);
        assertEquals(java.util.Arrays.asList("v1"), replaceAction.getRemoveVolunteerIds());
        assertEquals(java.util.Arrays.asList("v2"), replaceAction.getCandidateVolunteerIds());
        assertEquals(1, replaceAction.getReplacementPairs().size());

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setRerunReview(false);

        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertNotNull(res.getRepairReport());
        assertEquals("replace_risk_items", res.getRepairReport().getStrategy());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getRemovedVolunteerCount());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getAddedVolunteerCount());
        assertFalse(res.getState().getDraftPlanState().getItems().stream()
                .anyMatch(item -> "v1".equals(item.getVolunteerId())));
        assertTrue(res.getState().getDraftPlanState().getItems().stream()
                .anyMatch(item -> "v2".equals(item.getVolunteerId())));
    }

    @Test
    void shouldGenerateTierRatioFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutTargetTier() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 1, 2, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 1, buildMajorWithRatio("m3", "专业C", "48")),
                buildSchool("ps4", "s4", "学校D", "北京", 2, buildMajorWithRatio("m4", "专业D", "55"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "学校E", "北京", 1, buildMajorWithRatio("m5", "专业E", "82"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setForceRegenerate(true);
        generateReq.setRegroupByTier(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);
        CandidateViewStateDTO viewState = new CandidateViewStateDTO();
        viewState.getFilters().getProvinceNames().add("上海");
        state.setCandidateViewState(viewState);
        saveStateToStore(1L, state);

        CandidatePoolQueryReq currentViewReq = new CandidatePoolQueryReq();
        currentViewReq.getFilters().setProvinceNames(java.util.Arrays.asList("上海"));
        CandidatePoolQueryRes currentViewRes = planningStateService.queryCandidatePool(1L, 1L, currentViewReq);
        assertEquals(Integer.valueOf(0), currentViewRes.getTotal());
        assertNotNull(currentViewRes.getViewSummary());
        assertEquals(Integer.valueOf(5), currentViewRes.getViewSummary().getPoolEntryTotal());
        assertEquals(Integer.valueOf(0), currentViewRes.getViewSummary().getViewEntryTotal());

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "rebalance_tier_ratio".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getActions().stream()
                .anyMatch(action -> "rebalance_protect_ratio".equals(action.getActionType())));
        FixProposalActionDTO replaceAction = proposal.getActions().stream()
                .filter(action -> "replace_volunteers".equals(action.getActionType()))
                .findFirst()
                .orElse(null);
        assertNotNull(replaceAction);
        assertEquals(java.util.Arrays.asList("ps1_m1"), replaceAction.getRemoveVolunteerIds());
        assertEquals(java.util.Arrays.asList("ps5_m5"), replaceAction.getCandidateVolunteerIds());
        assertEquals(1, replaceAction.getReplacementPairs().size());
        assertEquals("ps1_m1", replaceAction.getReplacementPairs().get(0).getFromVolunteerId());
        assertEquals("ps5_m5", replaceAction.getReplacementPairs().get(0).getToVolunteerId());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
        assertEquals(Integer.valueOf(4), proposal.getDryRunResult().getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(4), proposal.getDryRunResult().getAfterVolunteerTotal());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getBeforeVolunteerTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTierCounts().get("保"));
        assertTrue(proposal.getCandidateShortages().stream()
                .noneMatch(shortage -> "current_view".equals(shortage.getScope())));
        assertPreviewOnlyFixProposalCannotApply(proposal);
    }

    @Test
    void shouldGenerateProbabilityGapFixProposalWithReplacementPairsFromFullPoolWhenCandidateViewFiltersOutMiddleCandidate() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "北京", 1, buildMajorWithRatio("m2", "专业B", "50"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 1, buildMajorWithRatio("m3", "专业C", "90")),
                buildSchool("ps4", "s4", "学校D", "北京", 2, buildMajorWithRatio("m4", "专业D", "92"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setForceRegenerate(true);
        generateReq.setRegroupByTier(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);
        CandidateViewStateDTO viewState = new CandidateViewStateDTO();
        viewState.getFilters().getProvinceNames().add("上海");
        state.setCandidateViewState(viewState);
        saveStateToStore(1L, state);

        CandidatePoolQueryReq currentViewReq = new CandidatePoolQueryReq();
        currentViewReq.getFilters().setProvinceNames(java.util.Arrays.asList("上海"));
        CandidatePoolQueryRes currentViewRes = planningStateService.queryCandidatePool(1L, 1L, currentViewReq);
        assertEquals(Integer.valueOf(0), currentViewRes.getTotal());
        assertNotNull(currentViewRes.getViewSummary());
        assertEquals(Integer.valueOf(4), currentViewRes.getViewSummary().getPoolEntryTotal());
        assertEquals(Integer.valueOf(0), currentViewRes.getViewSummary().getViewEntryTotal());

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "fill_probability_gap".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getActions().stream()
                .anyMatch(action -> "fill_probability_gap".equals(action.getActionType())));
        FixProposalActionDTO replaceAction = proposal.getActions().stream()
                .filter(action -> "replace_volunteers".equals(action.getActionType()))
                .findFirst()
                .orElse(null);
        assertNotNull(replaceAction);
        assertEquals(java.util.Arrays.asList("ps2_m2"), replaceAction.getCandidateVolunteerIds());
        assertEquals(1, replaceAction.getRemoveVolunteerIds().size());
        assertEquals(1, replaceAction.getReplacementPairs().size());
        assertEquals(replaceAction.getRemoveVolunteerIds().get(0), replaceAction.getReplacementPairs().get(0).getFromVolunteerId());
        assertEquals("ps2_m2", replaceAction.getReplacementPairs().get(0).getToVolunteerId());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getAfterVolunteerTotal());
        assertFalse(proposal.getDryRunResult().getBeforeVolunteerTierCounts().containsKey("稳"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTierCounts().get("稳"));
        assertTrue(proposal.getCandidateShortages().stream()
                .noneMatch(shortage -> "current_view".equals(shortage.getScope())));
        assertPreviewOnlyFixProposalCannotApply(proposal);
    }

    @Test
    void shouldGenerateTierRatioFixProposalWithUnitReplacementPairsWhenMajorGroupPlanIsFull() {
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

        VolunteerRecommendListResponse.VolunteerSchool sprintA = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "10"));
        sprintA.setEnroll_ratio("10");
        sprintA.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "10"),
                buildMajorWithRatio("m2", "专业A2", "12")
        ));
        VolunteerRecommendListResponse.VolunteerSchool sprintB = buildSchool("ps2", "s2", "专业组B", "北京", 2,
                buildMajorWithRatio("m3", "专业B1", "18"));
        sprintB.setEnroll_ratio("18");
        sprintB.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m3", "专业B1", "18"),
                buildMajorWithRatio("m4", "专业B2", "20")
        ));
        VolunteerRecommendListResponse.VolunteerSchool safe = buildSchool("ps3", "s3", "专业组C", "北京", 1,
                buildMajorWithRatio("m5", "专业C1", "50"));
        safe.setEnroll_ratio("50");
        safe.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m5", "专业C1", "50"),
                buildMajorWithRatio("m6", "专业C2", "52")
        ));
        VolunteerRecommendListResponse.VolunteerSchool protect = buildSchool("ps4", "s4", "专业组D", "北京", 1,
                buildMajorWithRatio("m7", "专业D1", "82"));
        protect.setEnroll_ratio("82");
        protect.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m7", "专业D1", "82"),
                buildMajorWithRatio("m8", "专业D2", "84")
        ));
        response.setSprints(java.util.Arrays.asList(sprintA, sprintB));
        response.setSafes(java.util.Arrays.asList(safe));
        response.setProtects(java.util.Arrays.asList(protect));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m3", "ps2_m4", "ps3_m5", "ps3_m6"));
        planningStateService.selectDraftItems(1L, selectReq);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setForceRegenerate(true);
        generateReq.setRegroupByTier(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "rebalance_tier_ratio".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        FixProposalActionDTO replaceAction = proposal.getActions().stream()
                .filter(action -> "replace_volunteers".equals(action.getActionType()))
                .findFirst()
                .orElse(null);
        assertNotNull(replaceAction);
        assertEquals(java.util.Arrays.asList("ps1"), replaceAction.getRemoveUnitIds());
        assertEquals(java.util.Arrays.asList("ps4"), replaceAction.getCandidateUnitIds());
        assertTrue(replaceAction.getRemoveVolunteerIds().contains("ps1_m1"));
        assertTrue(replaceAction.getCandidateVolunteerIds().contains("ps4_m7"));
        assertEquals("ps1", replaceAction.getReplacementPairs().get(0).getFromUnitId());
        assertEquals("ps4", replaceAction.getReplacementPairs().get(0).getToUnitId());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getBeforeUnitTotal());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getAfterUnitTotal());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getBeforeUnitTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterUnitTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterUnitTierCounts().get("保"));
        assertPreviewOnlyFixProposalCannotApply(proposal);
    }

    @Test
    void shouldBlockTierRatioFixProposalWhenAllSurplusSourcesAreLocked() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 1, 2, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 1, buildMajorWithRatio("m3", "专业C", "48")),
                buildSchool("ps4", "s4", "学校D", "北京", 2, buildMajorWithRatio("m4", "专业D", "55"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "学校E", "北京", 1, buildMajorWithRatio("m5", "专业E", "82"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setForceRegenerate(true);
        generateReq.setRegroupByTier(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);
        state.getDraftPlanState().getItems().stream()
                .filter(item -> "冲".equals(item.getTier()))
                .forEach(item -> item.setLocked(true));
        state.getOrderedPlanState().getItems().stream()
                .filter(item -> "冲".equals(item.getTier()))
                .forEach(item -> item.setLocked(true));
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "rebalance_tier_ratio".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertEquals("blocked", proposal.getDryRunResult().getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertFalse(proposal.getActions().stream()
                .anyMatch(action -> "rebalance_protect_ratio".equals(action.getActionType())
                        || "replace_volunteers".equals(action.getActionType())));
        assertTrue(proposal.getBlockingReason().contains("不能只追加候选"));
        assertEquals(java.util.Collections.singletonList("replacement_pair_missing"), proposal.getBlockingReasonCodes());
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("capacity_or_replacement", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("replacement_pair_missing", proposal.getCandidateShortages().get(0).getReasonCode());
        assertTrue(proposal.getCandidateShortages().get(0).getMessage().contains("替换配对"));
    }

    @Test
    void shouldRejectLegacyPlanAdjustmentApply() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        PlanAdjustmentStateDTO adjustmentState = new PlanAdjustmentStateDTO();
        adjustmentState.setStatus("ready");
        state.setPlanAdjustmentState(adjustmentState);
        saveStateToStore(1L, state);

        BusinessException ex = assertThrows(BusinessException.class,
                () -> planningStateService.applyPlanAdjustment(1L, 1L, new PlanAdjustmentApplyReq()));

        assertEquals(410, ex.getStatus());
        assertTrue(ex.getMessage().contains("已废弃"));
        PlanningStateDTO stored = planningStateService.getPlanningState(1L);
        assertEquals(Integer.valueOf(7), stored.getVersion());
        assertEquals("ready", stored.getPlanAdjustmentState().getStatus());
    }

    @Test
    void shouldApplySortByProbabilityFixProposalAndRerunReview() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.major.name());
        candidatePoolState.setRequiredCount(3);
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 60D, 92D, 60D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "稳", "专业B", 20D, 88D, 20D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "保", "专业C", 80D, 70D, 80D, false));
        state.setCandidatePoolState(candidatePoolState);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "稳", 2));
        orderedPlanState.getItems().add(buildOrderedItem("ps3_m3", "学校C", "专业C", "保", 3));
        state.setOrderedPlanState(orderedPlanState);
        saveStateToStore(1L, state);

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);
        ReviewCheckDTO inversion = reviewState.getChecks().stream()
                .filter(item -> "probability_inversion".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(inversion);
        assertFalse(inversion.getPassed());

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "sort_by_probability".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setRerunReview(true);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertNotNull(res.getRepairReport());
        assertEquals("sort_by_probability", res.getRepairReport().getStrategy());
        assertEquals(proposal.getProposalId(), res.getRepairReport().getProposalId());
        assertTrue(Boolean.TRUE.equals(res.getRepairReport().getPostValidationPassed()));
        assertEquals(Integer.valueOf(0), res.getRepairReport().getAfterRiskCount());
        assertTrue(res.getRepairReport().getMessages().stream().anyMatch(message -> message.contains("录取率")));
        assertEquals(java.util.Arrays.asList("ps2_m2", "ps1_m1", "ps3_m3"),
                res.getState().getOrderedPlanState().getItems().stream()
                        .map(OrderedItemDTO::getVolunteerId)
                        .collect(java.util.stream.Collectors.toList()));
        ReviewCheckDTO nextInversion = res.getState().getReviewState().getChecks().stream()
                .filter(item -> "probability_inversion".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(nextInversion);
        assertTrue(nextInversion.getPassed());
        assertFalse(Boolean.TRUE.equals(res.getState().getStaleFlags().getReview()));
        ArgumentCaptor<PlanningBehaviorEventDTO> behaviorEventCaptor = ArgumentCaptor.forClass(PlanningBehaviorEventDTO.class);
        verify(planningBehaviorEventSharedService, times(1)).saveBehaviorEvent(behaviorEventCaptor.capture());
        assertEquals("plan_sort_apply", behaviorEventCaptor.getValue().getEventType());
        assertEquals("admissionRatio", behaviorEventCaptor.getValue().getSortKey());
    }

    @Test
    void shouldApplyRemoveRiskItemsFixProposalAndFillMissingCount() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.major.name());
        candidatePoolState.setRequiredCount(3);
        CandidateItemDTO riskCandidate = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 35D, 92D, 35D, false);
        riskCandidate.getMustSubjects().add("色盲限报");
        candidatePoolState.getItems().add(riskCandidate);
        candidatePoolState.getItems().add(buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "稳", "专业B", 55D, 88D, 55D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "保", "专业C", 75D, 70D, 75D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps4_m4", "ps4", "s4", "学校D", "稳", "专业D", 58D, 86D, 58D, false));
        state.setCandidatePoolState(candidatePoolState);

        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "冲"));
        draft.getItems().add(buildDraftItem("ps2_m2", "学校B", "专业B", "稳"));
        draft.getItems().add(buildDraftItem("ps3_m3", "学校C", "专业C", "保"));
        state.setDraftPlanState(draft);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "稳", 2));
        orderedPlanState.getItems().add(buildOrderedItem("ps3_m3", "学校C", "专业C", "保", 3));
        state.setOrderedPlanState(orderedPlanState);
        saveStateToStore(1L, state);

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);
        ReviewCheckDTO admissionLimit = reviewState.getChecks().stream()
                .filter(item -> "admission_limit".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(admissionLimit);
        assertFalse(admissionLimit.getPassed());
        assertTrue(admissionLimit.getAffectedVolunteerIds().contains("ps1_m1"));

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "remove_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertTrue(proposal.getActions().stream().anyMatch(action -> "remove_volunteers".equals(action.getActionType())));
        assertTrue(proposal.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getActionType())));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertTrue(proposal.getDryRunResult().getAddVolunteerCount() > 0);

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setRerunReview(true);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertNotNull(res.getRepairReport());
        assertEquals("remove_risk_items", res.getRepairReport().getStrategy());
        assertTrue(Boolean.TRUE.equals(res.getRepairReport().getPostValidationPassed()));
        assertEquals(Integer.valueOf(1), res.getRepairReport().getRemovedVolunteerCount());
        assertTrue(res.getRepairReport().getAddedVolunteerCount() > 0);
        List<String> orderedIds = res.getState().getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(java.util.stream.Collectors.toList());
        assertFalse(orderedIds.contains("ps1_m1"));
        assertTrue(orderedIds.contains("ps4_m4"));
        assertEquals(3, orderedIds.size());
        ReviewCheckDTO nextAdmissionLimit = res.getState().getReviewState().getChecks().stream()
                .filter(item -> "admission_limit".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(nextAdmissionLimit);
        assertTrue(nextAdmissionLimit.getPassed());
    }

    @Test
    void shouldApplyMajorGroupRemoveRiskItemsWithoutFillingWhenUnitCountIsKept() {
        bindPlanningStateStore();
        PlanningStateDTO state = buildMajorGroupRiskFixState(false);
        saveStateToStore(1L, state);

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);
        ReviewCheckDTO admissionLimit = reviewState.getChecks().stream()
                .filter(item -> "admission_limit".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(admissionLimit);
        assertFalse(admissionLimit.getPassed());
        assertEquals(java.util.Arrays.asList("ps1"), admissionLimit.getAffectedUnitIds());
        assertEquals(java.util.Arrays.asList("ps1_m1"), admissionLimit.getAffectedVolunteerIds());

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "remove_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAffectedUnitCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveUnitCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(0), proposal.getDryRunResult().getAddVolunteerCount());
        assertFalse(proposal.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getActionType())));

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setRerunReview(true);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getAffectedUnitCount());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getRemovedUnitCount());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getRemovedVolunteerCount());
        assertEquals(Integer.valueOf(0), res.getRepairReport().getAddedVolunteerCount());
        assertEquals(3, res.getState().getOrderedPlanState().getItems().size());
        assertEquals(2, res.getState().getOrderedPlanState().getUnits().size());
        OrderedUnitDTO unit = res.getState().getOrderedPlanState().getUnits().stream()
                .filter(item -> "ps1".equals(item.getUnitId()))
                .findFirst()
                .orElse(null);
        assertNotNull(unit);
        assertEquals(1, unit.getMajorItems().size());
        assertEquals("ps1_m2", unit.getMajorItems().get(0).getVolunteerId());
        assertFalse(res.getState().getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toSet())
                .contains("ps3_m5"));
    }

    @Test
    void shouldApplyMajorGroupRemoveRiskItemsAndFillOnlyWhenUnitCountDrops() {
        bindPlanningStateStore();
        PlanningStateDTO state = buildMajorGroupRiskFixState(true);
        saveStateToStore(1L, state);

        planningStateService.runReview(1L, 1L);
        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "remove_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertTrue(proposal.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getActionType())));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setRerunReview(true);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertEquals(Integer.valueOf(1), res.getRepairReport().getAddedVolunteerCount());
        assertEquals(2, res.getState().getOrderedPlanState().getSummary().getTotal());
        assertEquals(2, res.getState().getOrderedPlanState().getUnits().size());
        Set<String> orderedIds = res.getState().getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertFalse(orderedIds.contains("ps1_m1"));
        assertTrue(orderedIds.contains("ps2_m3"));
        assertTrue(orderedIds.contains("ps3_m5"));
        assertFalse(orderedIds.contains("ps3_m6"));
        assertTrue(Boolean.TRUE.equals(res.getRepairReport().getPostValidationPassed()));
    }

    @Test
    void shouldApplyMajorGroupInnerSafetyFixProposalWithinSameUnit() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(5);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        candidatePoolState.setRequiredCount(1);
        candidatePoolState.setRequiredMajorCount(2);
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A第101组", "冲", "专业A1", 35D, 60D, 45D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m2", "ps1", "s1", "学校A第101组", "冲", "专业A2", 38D, 58D, 45D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m3", "ps1", "s1", "学校A第101组", "冲", "安全专业A3", 52D, 62D, 45D, false));
        state.setCandidatePoolState(candidatePoolState);

        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("ps1_m1", "学校A第101组", "专业A1", "冲"));
        draft.getItems().add(buildDraftItem("ps1_m2", "学校A第101组", "专业A2", "冲"));
        ReflectionTestUtils.invokeMethod(planningStateService, "syncWorkingPlanUnitsWithItems", draft, candidatePoolState.getItems(), candidatePoolState);
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateWorkingPlanSummary", draft, candidatePoolState);
        state.setDraftPlanState(draft);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A第101组", "专业A1", "冲", 1));
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m2", "学校A第101组", "专业A2", "冲", 2));
        orderedPlanState.setUnits(ReflectionTestUtils.invokeMethod(planningStateService,
                "buildOrderedUnitsFromOrderedItems", orderedPlanState.getItems(), draft, candidatePoolState.getItems()));
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateOrderedSummary", orderedPlanState, candidatePoolState);
        state.setOrderedPlanState(orderedPlanState);
        saveStateToStore(1L, state);

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);
        ReviewCheckDTO safetyCheck = reviewState.getChecks().stream()
                .filter(item -> "group_inner_safety_guard".equals(item.getCode()))
                .findFirst()
                .orElse(null);
        assertNotNull(safetyCheck);
        assertFalse(Boolean.TRUE.equals(safetyCheck.getPassed()));
        assertEquals(java.util.Arrays.asList("ps1"), safetyCheck.getAffectedUnitIds());

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "adjust_major_group_inner_safety".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("ready", proposal.getStatus());
        assertEquals(Integer.valueOf(0), proposal.getDryRunResult().getAddUnitCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        FixProposalActionDTO action = proposal.getActions().stream()
                .filter(item -> "adjust_major_group_inner_safety".equals(item.getActionType()))
                .findFirst()
                .orElse(null);
        assertNotNull(action);
        assertEquals(java.util.Arrays.asList("ps1_m2"), action.getRemoveVolunteerIds());
        assertEquals(java.util.Arrays.asList("ps1_m3"), action.getCandidateVolunteerIds());

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setRerunReview(true);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);

        assertEquals("applied", res.getStatus());
        assertTrue(Boolean.TRUE.equals(res.getRepairReport().getPostValidationPassed()));
        Set<String> orderedIds = res.getState().getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertTrue(orderedIds.contains("ps1_m1"));
        assertFalse(orderedIds.contains("ps1_m2"));
        assertTrue(orderedIds.contains("ps1_m3"));
        OrderedUnitDTO repairedUnit = res.getState().getOrderedPlanState().getUnits().stream()
                .filter(item -> "ps1".equals(item.getUnitId()))
                .findFirst()
                .orElse(null);
        assertNotNull(repairedUnit);
        assertEquals(2, repairedUnit.getMajorItems().size());
        assertTrue(repairedUnit.getMajorItems().stream()
                .anyMatch(item -> "ps1_m3".equals(item.getVolunteerId()) && Boolean.TRUE.equals(item.getSafetyMajor())));
    }

    @Test
    void shouldGenerateItemRiskFixProposalFromExistingReview() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getStaleFlags().setReview(false);

        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary("当前方案包含高收费专业");
        check.setAffectedVolunteerIds(java.util.Arrays.asList("v1"));
        reviewState.setChecks(java.util.Arrays.asList(check));
        state.setReviewState(reviewState);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO riskCandidate = buildCandidateItem("v1", "ps1", "s1", "学校A", "稳", "高收费专业", 55D, 80D, 55D, false);
        riskCandidate.setTuitionPerYear(30000);
        riskCandidate.setMajorCategory("工商管理类");
        CandidateItemDTO replacementCandidate = buildCandidateItem("v2", "ps2", "s2", "学校B", "稳", "安全专业", 58D, 82D, 58D, false);
        replacementCandidate.setMajorCategory("工商管理类");
        candidatePoolState.getItems().add(riskCandidate);
        candidatePoolState.getItems().add(replacementCandidate);
        state.setCandidatePoolState(candidatePoolState);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("v1", "学校A", "高收费专业", "稳"));
        state.setDraftPlanState(draft);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        assertEquals(Integer.valueOf(1), proposalState.getTotal());
        assertEquals(Integer.valueOf(7), proposalState.getSourceVersion());
        assertEquals(Integer.valueOf(7), proposalState.getSourceReviewVersion());
        assertEquals(Integer.valueOf(7), proposalState.getSourceVersionGuard());
        FixProposalDTO proposal = proposalState.getProposals().get(0);
        assertEquals("replace_risk_items", proposal.getStrategy());
        assertEquals(Integer.valueOf(7), proposal.getSourceReviewVersion());
        assertEquals(Integer.valueOf(7), proposal.getSourceVersionGuard());
        assertEquals("修复高收费", proposal.getTitle());
        assertTrue(proposal.getSourceCheckCodes().contains("high_tuition"));
        assertEquals(java.util.Arrays.asList("v1"), proposal.getAffectedVolunteerIds());
        assertEquals("ready", proposal.getStatus());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertTrue(proposal.getDryRunResult().getMessage().contains("用户确认"));
        assertTrue(proposal.getActions().stream().anyMatch(action -> "replace_volunteers".equals(action.getActionType())
                && action.getReplacementPairs().stream().anyMatch(pair -> "v1".equals(pair.getFromVolunteerId())
                && "v2".equals(pair.getToVolunteerId()))));
    }

    @Test
    void shouldAllowRiskReplacementWhenCandidateOnlyHasScoreRiskFlags() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getStaleFlags().setReview(false);

        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary("当前方案包含高收费专业");
        check.setAffectedVolunteerIds(java.util.Arrays.asList("v1"));
        reviewState.setChecks(java.util.Arrays.asList(check));
        state.setReviewState(reviewState);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO riskCandidate = buildCandidateItem("v1", "ps1", "s1", "学校A", "稳", "高收费专业", 55D, 80D, 55D, false);
        riskCandidate.setTuitionPerYear(30000);
        riskCandidate.setMajorCategory("工商管理类");
        CandidateItemDTO scoreTaggedCandidate = buildCandidateItem("v2", "ps2", "s2", "学校B", "稳", "安全专业", 58D, 82D, 58D, false);
        scoreTaggedCandidate.setMajorCategory("工商管理类");
        scoreTaggedCandidate.getRiskFlags().add("special_score:0");
        scoreTaggedCandidate.getRiskFlags().add("degree_score:0");
        scoreTaggedCandidate.getRiskFlags().add("evaluate_score:0");
        candidatePoolState.getItems().add(riskCandidate);
        candidatePoolState.getItems().add(scoreTaggedCandidate);
        state.setCandidatePoolState(candidatePoolState);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("v1", "学校A", "高收费专业", "稳"));
        state.setDraftPlanState(draft);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "replace_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getActions().stream().anyMatch(action -> "replace_volunteers".equals(action.getActionType())
                && action.getCandidateVolunteerIds().contains("v2")));
    }

    @Test
    void shouldBlockRiskReplacementWhenCandidateHasExplicitRiskFlag() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getStaleFlags().setReview(false);

        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary("当前方案包含高收费专业");
        check.setAffectedVolunteerIds(java.util.Arrays.asList("v1"));
        reviewState.setChecks(java.util.Arrays.asList(check));
        state.setReviewState(reviewState);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO riskCandidate = buildCandidateItem("v1", "ps1", "s1", "学校A", "稳", "高收费专业", 55D, 80D, 55D, false);
        riskCandidate.setTuitionPerYear(30000);
        riskCandidate.setMajorCategory("工商管理类");
        CandidateItemDTO explicitRiskCandidate = buildCandidateItem("v2", "ps2", "s2", "学校B", "稳", "候选专业", 58D, 82D, 58D, false);
        explicitRiskCandidate.setMajorCategory("工商管理类");
        explicitRiskCandidate.getRiskFlags().add("foreign");
        candidatePoolState.getItems().add(riskCandidate);
        candidatePoolState.getItems().add(explicitRiskCandidate);
        state.setCandidatePoolState(candidatePoolState);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("v1", "学校A", "高收费专业", "稳"));
        state.setDraftPlanState(draft);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "replace_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldGenerateReadyReplaceRiskProposalForMultipleRiskItems() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getStaleFlags().setReview(false);

        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary("当前方案包含高收费专业");
        check.setAffectedVolunteerIds(java.util.Arrays.asList("v1", "v2"));
        reviewState.setChecks(java.util.Arrays.asList(check));
        state.setReviewState(reviewState);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO riskCandidate1 = buildCandidateItem("v1", "ps1", "s1", "学校A", "稳", "高收费专业A", 55D, 80D, 55D, false);
        riskCandidate1.setTuitionPerYear(30000);
        riskCandidate1.setMajorCategory("工商管理类");
        CandidateItemDTO riskCandidate2 = buildCandidateItem("v2", "ps2", "s2", "学校B", "稳", "高收费专业B", 56D, 79D, 56D, false);
        riskCandidate2.setTuitionPerYear(32000);
        riskCandidate2.setMajorCategory("工商管理类");
        candidatePoolState.getItems().add(riskCandidate1);
        candidatePoolState.getItems().add(riskCandidate2);
        CandidateItemDTO replacementCandidate1 = buildCandidateItem("v3", "ps3", "s3", "学校C", "稳", "安全专业C", 58D, 82D, 58D, false);
        replacementCandidate1.setMajorCategory("工商管理类");
        CandidateItemDTO replacementCandidate2 = buildCandidateItem("v4", "ps4", "s4", "学校D", "稳", "安全专业D", 59D, 81D, 59D, false);
        replacementCandidate2.setMajorCategory("工商管理类");
        candidatePoolState.getItems().add(replacementCandidate1);
        candidatePoolState.getItems().add(replacementCandidate2);
        state.setCandidatePoolState(candidatePoolState);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("v1", "学校A", "高收费专业A", "稳"));
        draft.getItems().add(buildDraftItem("v2", "学校B", "高收费专业B", "稳"));
        state.setDraftPlanState(draft);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "replace_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("ready", proposal.getStatus());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getAddVolunteerCount());
        List<FixProposalActionDTO> replaceActions = proposal.getActions().stream()
                .filter(action -> "replace_volunteers".equals(action.getActionType()))
                .collect(Collectors.toList());
        assertEquals(2, replaceActions.size());
        Set<String> removeIds = replaceActions.stream()
                .flatMap(action -> action.getRemoveVolunteerIds().stream())
                .collect(Collectors.toSet());
        Set<String> candidateIds = replaceActions.stream()
                .flatMap(action -> action.getCandidateVolunteerIds().stream())
                .collect(Collectors.toSet());
        assertEquals(new java.util.HashSet<String>(java.util.Arrays.asList("v1", "v2")), removeIds);
        assertEquals(new java.util.HashSet<String>(java.util.Arrays.asList("v3", "v4")), candidateIds);
        assertTrue(proposal.getDryRunResult().getWarnings().isEmpty());
    }

    @Test
    void shouldKeepPartialReplaceRiskProposalPreviewOnlyWithWarning() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getStaleFlags().setReview(false);

        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary("当前方案包含高收费专业");
        check.setAffectedVolunteerIds(java.util.Arrays.asList("v1", "v2"));
        reviewState.setChecks(java.util.Arrays.asList(check));
        state.setReviewState(reviewState);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO riskCandidate1 = buildCandidateItem("v1", "ps1", "s1", "学校A", "稳", "高收费专业A", 55D, 80D, 55D, false);
        riskCandidate1.setTuitionPerYear(30000);
        riskCandidate1.setMajorCategory("工商管理类");
        CandidateItemDTO riskCandidate2 = buildCandidateItem("v2", "ps2", "s2", "学校B", "稳", "高收费专业B", 56D, 79D, 56D, false);
        riskCandidate2.setTuitionPerYear(32000);
        riskCandidate2.setMajorCategory("工商管理类");
        candidatePoolState.getItems().add(riskCandidate1);
        candidatePoolState.getItems().add(riskCandidate2);
        CandidateItemDTO replacementCandidate = buildCandidateItem("v3", "ps3", "s3", "学校C", "稳", "安全专业C", 58D, 82D, 58D, false);
        replacementCandidate.setMajorCategory("工商管理类");
        candidatePoolState.getItems().add(replacementCandidate);
        state.setCandidatePoolState(candidatePoolState);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("v1", "学校A", "高收费专业A", "稳"));
        draft.getItems().add(buildDraftItem("v2", "学校B", "高收费专业B", "稳"));
        state.setDraftPlanState(draft);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "replace_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getAffectedVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("部分风险志愿的替换预览")));
        assertTrue(proposal.getDryRunResult().getAfterVolunteerIds().contains("v2"));
        assertPreviewOnlyFixProposalCannotApply(proposal);
    }

    @Test
    void shouldKeepReplaceRiskProposalBlockedWhenNoReplacementExists() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getStaleFlags().setReview(false);

        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary("当前方案包含高收费专业");
        check.setAffectedVolunteerIds(java.util.Arrays.asList("v1"));
        reviewState.setChecks(java.util.Arrays.asList(check));
        state.setReviewState(reviewState);

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        CandidateItemDTO riskCandidate = buildCandidateItem("v1", "ps1", "s1", "学校A", "稳", "高收费专业", 55D, 80D, 55D, false);
        riskCandidate.setTuitionPerYear(30000);
        CandidateItemDTO unsafeCandidate = buildCandidateItem("v2", "ps2", "s2", "学校B", "稳", "另一个高收费专业", 58D, 82D, 58D, false);
        unsafeCandidate.setTuitionPerYear(35000);
        candidatePoolState.getItems().add(riskCandidate);
        candidatePoolState.getItems().add(unsafeCandidate);
        state.setCandidatePoolState(candidatePoolState);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("v1", "学校A", "高收费专业", "稳"));
        state.setDraftPlanState(draft);
        saveStateToStore(1L, state);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);

        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "replace_risk_items".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("blocked", proposal.getStatus());
        assertEquals("blocked", proposal.getDryRunResult().getStatus());
        assertEquals(Boolean.FALSE, proposal.getRequiresConfirmation());
        assertTrue(proposal.getActions().isEmpty());
        assertTrue(proposal.getBlockingReason().contains("候选不足"));
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("专业相近")
                        && warning.contains("院校层次代价可接受")));
    }

    @Test
    void shouldNotWarnLowSprintRatioWhenRequiredTierCountIsMet() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        candidatePoolState.getRequiredTierCounts().put("冲", 8);
        candidatePoolState.getRequiredTierCounts().put("稳", 18);
        candidatePoolState.getRequiredTierCounts().put("保", 19);
        state.setCandidatePoolState(candidatePoolState);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        for (int i = 0; i < 8; i++) {
            OrderedUnitDTO unit = new OrderedUnitDTO();
            unit.setUnitId("sprint-" + i);
            unit.setTier("冲");
            orderedPlanState.getUnits().add(unit);
        }
        for (int i = 0; i < 18; i++) {
            OrderedUnitDTO unit = new OrderedUnitDTO();
            unit.setUnitId("safe-" + i);
            unit.setTier("稳");
            orderedPlanState.getUnits().add(unit);
        }
        for (int i = 0; i < 19; i++) {
            OrderedUnitDTO unit = new OrderedUnitDTO();
            unit.setUnitId("protect-" + i);
            unit.setTier("保");
            orderedPlanState.getUnits().add(unit);
        }
        state.setOrderedPlanState(orderedPlanState);

        ReviewCheckDTO check = ReflectionTestUtils.invokeMethod(planningStateService, "reviewRatioDistribution", state);

        assertNotNull(check);
        assertTrue(check.getPassed());
        assertEquals("冲稳保区间配比正常", check.getSummary());
    }

    @Test
    void shouldCapMajorGroupRequiredTierCountsByAvailableUnitsAndRedistributeShortage() {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        candidatePoolState.setRequiredCount(45);
        candidatePoolState.getRequiredTierCounts().put("冲", 13);
        candidatePoolState.getRequiredTierCounts().put("稳", 13);
        candidatePoolState.getRequiredTierCounts().put("保", 19);

        addCandidateUnits(candidatePoolState, "冲", "sprint", 8);
        addCandidateUnits(candidatePoolState, "稳", "safe", 24);
        addCandidateUnits(candidatePoolState, "保", "protect", 77);

        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateCandidatePoolSummary", candidatePoolState);
        ReflectionTestUtils.invokeMethod(planningStateService, "normalizeRequiredTierCountsByAvailableCapacity", candidatePoolState);

        assertEquals(8, candidatePoolState.getRequiredTierCounts().get("冲"));
        assertEquals(18, candidatePoolState.getRequiredTierCounts().get("稳"));
        assertEquals(19, candidatePoolState.getRequiredTierCounts().get("保"));
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

        java.util.Map<String, Boolean> ruleHits = adjustmentState.getAnalysis().getRules().stream()
                .collect(java.util.stream.Collectors.toMap(
                        rule -> rule.getRuleCode(),
                        rule -> Boolean.TRUE.equals(rule.getHit()),
                        (left, right) -> left,
                        java.util.LinkedHashMap::new));

        assertTrue(Boolean.TRUE.equals(ruleHits.get("ratio_distribution")));
        assertTrue(adjustmentState.getSuggestions().getAddSuggestions().stream()
                .anyMatch(item -> "ratio_distribution".equals(item.getRuleCode())));
        assertTrue(adjustmentState.getSuggestions().getReplaceSuggestions().stream()
                .anyMatch(item -> "ratio_distribution".equals(item.getRuleCode())
                        && !item.getRemoveVolunteerIds().isEmpty()
                        && !item.getCandidateVolunteerIds().isEmpty()
                        && !item.getReplacementPairs().isEmpty()));
    }

    @Test
    void shouldRepairInitialRecommendationForLocalProtectSafety() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(5, 1, 1, 3);
        response.setBaseData(baseData);

        CreateSessionReq scoreDetail = new CreateSessionReq();
        scoreDetail.setTotalScore(560);
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setName("北京");
        scoreDetail.setProvince(province);
        response.setUserScoreDetail(scoreDetail);

        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "12"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "稳A", "天津", 1, buildMajorWithRatio("m2", "专业B", "38"))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "保A", "河北", 1, buildMajorWithRatio("m3", "专业C", "72")),
                buildSchool("ps4", "s4", "保B", "河南", 2, buildMajorWithRatio("m4", "专业D", "78")),
                buildSchool("ps5", "s5", "保C", "北京", 3, buildMajorWithRatio("m5", "专业E", "84")),
                buildSchool("ps6", "s6", "保D", "北京", 4, buildMajorWithRatio("m6", "专业F", "88"))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        PlanningStateDTO recommendationState = planningStateService.generateInitialRecommendation(
                1L, 1L, new InitialRecommendationGenerateReq());

        assertEquals(Integer.valueOf(5), recommendationState.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(3), recommendationState.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertEquals(Integer.valueOf(2), recommendationState.getInitialRecommendationState().getSummary().getLocalProtectCount());
        assertTrue(recommendationState.getInitialRecommendationState().getItems().stream()
                .map(item -> item.getVolunteerId())
                .anyMatch("ps6_m6"::equals));
        assertFalse(recommendationState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("safety_guard"));
    }

    @Test
    void shouldRepairInitialRecommendationProbabilityGap() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 2, 2, 0));
        response.setUserScoreDetail(buildScoreDetail());

        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "20"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "稳A", "北京", 1, buildMajorWithRatio("m3", "专业C", "50")),
                buildSchool("ps4", "s4", "稳B", "北京", 2, buildMajorWithRatio("m4", "专业D", "58")),
                buildSchool("ps5", "s5", "稳C", "北京", 3, buildMajorWithRatio("m5", "专业E", "28")),
                buildSchool("ps6", "s6", "稳D", "北京", 4, buildMajorWithRatio("m6", "专业F", "36"))
        ));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        PlanningStateDTO recommendationState = planningStateService.generateInitialRecommendation(
                1L, 1L, new InitialRecommendationGenerateReq());

        java.util.List<String> selectedIds = recommendationState.getInitialRecommendationState().getItems().stream()
                .map(item -> item.getVolunteerId())
                .collect(java.util.stream.Collectors.toList());

        assertEquals(Integer.valueOf(4), recommendationState.getInitialRecommendationState().getSummary().getTotal());
        assertTrue(recommendationState.getInitialRecommendationState().getSummary().getGapFixCount() >= 1);
        assertEquals(Integer.valueOf(1), recommendationState.getInitialRecommendationState().getSummary().getUnresolvedGapCount());
        assertTrue(selectedIds.contains("ps1_m1"));
        assertTrue(selectedIds.contains("ps2_m2"));
        assertTrue(selectedIds.contains("ps5_m5"));
        assertTrue(selectedIds.contains("ps6_m6"));
        assertFalse(recommendationState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().isEmpty());
        assertTrue(recommendationState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("probability_gap"));
        InitialPlanStrategyReportDTO report = recommendationState.getInitialRecommendationState().getStrategyReport();
        assertEquals(Integer.valueOf(4), report.getTargetProfile().getTargetCount());
        assertEquals(Integer.valueOf(4), report.getSelectedCount());
        assertTrue(report.getObjectiveWeights().stream()
                .anyMatch(item -> "tier_structure".equals(item.getCode())
                        && item.getRelativeWeight() != null
                        && item.getPriority() != null));
        assertTrue(report.getObjectiveWeights().stream()
                .anyMatch(item -> "admission_safety".equals(item.getCode())
                        && item.getDescription() != null
                        && item.getDescription().contains("录取率")));
        assertTrue(report.getAppliedRepairs().stream()
                .anyMatch(item -> "probability_gap".equals(item.getRuleCode())
                        && "replace_candidate".equals(item.getActionType())
                        && item.getTradeoffSummary() != null
                        && item.getTradeoffSummary().contains("收益")));
        assertTrue(report.getActions().stream()
                .anyMatch(item -> "probability_gap".equals(item.getSourceCheckCode())
                        && "replace_volunteers".equals(item.getActionType())
                        && !item.getRemoveVolunteerIds().isEmpty()
                        && !item.getCandidateVolunteerIds().isEmpty()
                        && !item.getReplacementPairs().isEmpty()));
        assertTrue(report.getTradeoffs().stream()
                .anyMatch(item -> "probability_gap".equals(item.getRuleCode())
                        && "replace_candidate".equals(item.getActionType())
                        && item.getGains().contains("缓解录取率梯度断层")
                        && item.getSummary() != null
                        && item.getSummary().contains("取舍")));
        assertTrue(report.getUnresolvedRisks().stream()
                .anyMatch(item -> "probability_gap".equals(item.getRuleCode())));
        assertTrue(report.getCandidateShortages().stream()
                .anyMatch(item -> "probability_gap".equals(item.getSourceCheckCode())
                        && "candidate_pool".equals(item.getScope())
                        && "probability_gap_candidate_insufficient".equals(item.getReasonCode())
                        && Integer.valueOf(1).equals(item.getShortageCount())
                        && Integer.valueOf(0).equals(item.getAvailableCount())));
        assertFalse(report.getUserAttentionMessages().isEmpty());

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(recommendationState);
        assertNotNull(workspaceState.getInitialRecommendationState());
        assertTrue(workspaceState.getInitialRecommendationState().getStrategyReport().getAppliedRepairs().stream()
                .anyMatch(item -> "probability_gap".equals(item.getRuleCode())));
        assertTrue(workspaceState.getInitialRecommendationState().getStrategyReport().getCandidateShortages().stream()
                .anyMatch(item -> "当前可用于规划的候选池里，断层中间录取率候选不足。".equals(item.getMessage())));
    }

    @Test
    void shouldRepairInitialRecommendationProbabilityInversion() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 2, 2, 0));
        response.setUserScoreDetail(buildScoreDetail());

        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "52")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "26")),
                buildSchool("ps3", "s3", "冲C", "北京", 3, buildMajorWithRatio("m3", "专业C", "18"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps4", "s4", "稳A", "北京", 1, buildMajorWithRatio("m4", "专业D", "40")),
                buildSchool("ps5", "s5", "稳B", "北京", 2, buildMajorWithRatio("m5", "专业E", "54"))
        ));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        PlanningStateDTO recommendationState = planningStateService.generateInitialRecommendation(
                1L, 1L, new InitialRecommendationGenerateReq());

        java.util.List<String> selectedIds = recommendationState.getInitialRecommendationState().getItems().stream()
                .map(item -> item.getVolunteerId())
                .collect(java.util.stream.Collectors.toList());

        assertEquals(Integer.valueOf(4), recommendationState.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(2), recommendationState.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(2), recommendationState.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertTrue(selectedIds.contains("ps2_m2"));
        assertTrue(selectedIds.contains("ps3_m3"));
        assertFalse(selectedIds.contains("ps1_m1"));
        assertFalse(recommendationState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("probability_inversion"));
    }

    @Test
    void shouldFullyRepairInitialRecommendationProbabilityGapWhenCandidateWindowIsEnough() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 2, 2, 0));
        response.setUserScoreDetail(buildScoreDetail());

        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "18"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "稳A", "北京", 1, buildMajorWithRatio("m3", "专业C", "42")),
                buildSchool("ps4", "s4", "稳B", "北京", 2, buildMajorWithRatio("m4", "专业D", "48")),
                buildSchool("ps5", "s5", "稳C", "北京", 3, buildMajorWithRatio("m5", "专业E", "26")),
                buildSchool("ps6", "s6", "稳D", "北京", 4, buildMajorWithRatio("m6", "专业F", "34"))
        ));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        PlanningStateDTO recommendationState = planningStateService.generateInitialRecommendation(
                1L, 1L, new InitialRecommendationGenerateReq());

        java.util.List<String> selectedIds = recommendationState.getInitialRecommendationState().getItems().stream()
                .map(item -> item.getVolunteerId())
                .collect(java.util.stream.Collectors.toList());

        assertEquals(Integer.valueOf(4), recommendationState.getInitialRecommendationState().getSummary().getTotal());
        assertTrue(recommendationState.getInitialRecommendationState().getSummary().getGapFixCount() >= 2);
        assertEquals(Integer.valueOf(0), recommendationState.getInitialRecommendationState().getSummary().getUnresolvedGapCount());
        assertTrue(selectedIds.contains("ps1_m1"));
        assertTrue(selectedIds.contains("ps2_m2"));
        assertTrue(selectedIds.contains("ps5_m5"));
        assertTrue(selectedIds.contains("ps6_m6"));
        assertFalse(selectedIds.contains("ps3_m3"));
        assertFalse(selectedIds.contains("ps4_m4"));
        assertFalse(recommendationState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("probability_gap"));
        assertTrue(recommendationState.getInitialRecommendationState().getStrategyReport().getCandidateShortages().isEmpty());
    }

    @Test
    void shouldPreferLowerTradeoffCandidateWhenRepairingInitialRecommendationProbabilityGap() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(4, 2, 2, 0));
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool selectedLow = buildSchool(
                "ps1", "s1", "冲A", "北京", 1,
                buildMajorWithRatio("m1", "法学", "10"));
        selectedLow.setSchool_rank(80);
        VolunteerRecommendListResponse.VolunteerSchool selectedHigh = buildSchool(
                "ps2", "s2", "冲B", "北京", 2,
                buildMajorWithRatio("m2", "汉语言文学", "20"));
        selectedHigh.setSchool_rank(90);
        VolunteerRecommendListResponse.VolunteerSchool selectedFarA = buildSchool(
                "ps3", "s3", "稳A", "北京", 1,
                buildMajorWithRatio("m3", "金融学", "50"));
        selectedFarA.setSchool_rank(70);
        VolunteerRecommendListResponse.VolunteerSchool selectedFarB = buildSchool(
                "ps4", "s4", "稳B", "北京", 2,
                buildMajorWithRatio("m4", "会计学", "58"));
        selectedFarB.setSchool_rank(75);
        response.setSprints(java.util.Arrays.asList(selectedLow, selectedHigh));
        VolunteerRecommendListResponse.VolunteerSchool unrelatedHigherScore = buildSchool(
                "ps5", "s5", "稳C", "北京", 3,
                buildMajorWithRatio("m5", "计算机科学与技术", "28"));
        unrelatedHigherScore.setSchool_rank(260);
        VolunteerRecommendListResponse.VolunteerSchool similarLowerTradeoff = buildSchool(
                "ps6", "s6", "稳D", "北京", 4,
                buildMajorWithRatio("m6", "会计学", "28"));
        similarLowerTradeoff.setSchool_rank(110);
        response.setSafes(java.util.Arrays.asList(selectedFarA, selectedFarB, unrelatedHigherScore, similarLowerTradeoff));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        PlanningStateDTO recommendationState = planningStateService.generateInitialRecommendation(
                1L, 1L, new InitialRecommendationGenerateReq());

        java.util.List<String> selectedIds = recommendationState.getInitialRecommendationState().getItems().stream()
                .map(item -> item.getVolunteerId())
                .collect(java.util.stream.Collectors.toList());

        assertTrue(selectedIds.contains("ps6_m6"));
        assertFalse(selectedIds.contains("ps5_m5"));
        assertTrue(recommendationState.getInitialRecommendationState().getStrategyReport().getActions().stream()
                .anyMatch(action -> "probability_gap".equals(action.getSourceCheckCode())
                        && action.getCandidateVolunteerIds().contains("ps6_m6")));
    }

    @Test
    void shouldKeepTierTargetsStableAfterInitialRecommendationRepairs() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(5, 2, 1, 2));
        response.setUserScoreDetail(buildScoreDetail());

        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithRatio("m1", "专业A", "30")),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithRatio("m2", "专业B", "16")),
                buildSchool("ps3", "s3", "冲C", "北京", 3, buildMajorWithRatio("m3", "专业C", "12"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps4", "s4", "稳A", "北京", 1, buildMajorWithRatio("m4", "专业D", "42")),
                buildSchool("ps5", "s5", "稳B", "北京", 2, buildMajorWithRatio("m5", "专业E", "28")),
                buildSchool("ps6", "s6", "稳C", "北京", 3, buildMajorWithRatio("m6", "专业F", "34"))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps7", "s7", "保A", "河北", 1, buildMajorWithRatio("m7", "专业G", "70")),
                buildSchool("ps8", "s8", "保B", "河南", 2, buildMajorWithRatio("m8", "专业H", "78")),
                buildSchool("ps9", "s9", "保C", "北京", 3, buildMajorWithRatio("m9", "专业I", "84"))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        PlanningStateDTO recommendationState = planningStateService.generateInitialRecommendation(
                1L, 1L, new InitialRecommendationGenerateReq());

        assertEquals(Integer.valueOf(5), recommendationState.getInitialRecommendationState().getSummary().getTotal());
        assertEquals(Integer.valueOf(2), recommendationState.getInitialRecommendationState().getSummary().getTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), recommendationState.getInitialRecommendationState().getSummary().getTierCounts().get("稳"));
        assertEquals(Integer.valueOf(2), recommendationState.getInitialRecommendationState().getSummary().getTierCounts().get("保"));
        assertFalse(recommendationState.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes().contains("ratio_distribution"));
    }

    @Test
    void shouldSortCandidatePoolBySchoolEnrollRatioWhenOrderingByAdmissionRatio() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();

        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajor("m1", "专业A"));
        schoolA.setEnroll_ratio("65");
        schoolA.getMajors().get(0).setEnroll_ratio("40");

        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajor("m2", "专业B"));
        schoolB.setEnroll_ratio("55");
        schoolB.getMajors().get(0).setEnroll_ratio("70");

        response.setSafes(java.util.Arrays.asList(schoolA, schoolB));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        queryReq.getSort().setField("admissionRatio");
        queryReq.getSort().setOrder("asc");

        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);

        assertEquals(Integer.valueOf(2), queryRes.getTotal());
        assertEquals("学校B", queryRes.getItems().get(0).getSchoolName());
        assertEquals(Double.valueOf(55D), queryRes.getItems().get(0).getSchoolEnrollRatio());
        assertEquals(Double.valueOf(70D), queryRes.getItems().get(0).getAdmissionRatio());
        assertEquals("学校A", queryRes.getItems().get(1).getSchoolName());
        assertEquals(Double.valueOf(65D), queryRes.getItems().get(1).getSchoolEnrollRatio());
        assertEquals(Double.valueOf(40D), queryRes.getItems().get(1).getAdmissionRatio());
    }

    @Test
    void shouldExcludeCandidatePoolItemsByNegativeFilters() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "上海大学", "上海", 1, buildMajor("m1", "临床医学"));
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "北京邮电大学", "北京", 2, buildMajor("m2", "计算机科学与技术"));
        response.setSafes(java.util.Arrays.asList(schoolA, schoolB));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        queryReq.getFilters().setNegativeProvinceNames(java.util.Arrays.asList("上海"));
        queryReq.getFilters().setNegativeMajorKeywords(java.util.Arrays.asList("医学"));

        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);

        assertEquals(Integer.valueOf(1), queryRes.getTotal());
        assertEquals(Integer.valueOf(1), queryRes.getTotalUnitCount());
        assertNotNull(queryRes.getViewSummary());
        assertEquals(Integer.valueOf(2), queryRes.getViewSummary().getPoolEntryTotal());
        assertEquals(Integer.valueOf(2), queryRes.getViewSummary().getPoolUnitTotal());
        assertEquals(Integer.valueOf(1), queryRes.getViewSummary().getViewEntryTotal());
        assertEquals(Integer.valueOf(1), queryRes.getViewSummary().getViewUnitTotal());
        assertEquals(Integer.valueOf(1), queryRes.getViewSummary().getLoadedEntryCount());
        assertEquals(Integer.valueOf(1), queryRes.getViewSummary().getLoadedUnitCount());
        assertEquals("北京邮电大学", queryRes.getItems().get(0).getSchoolName());
    }

    @Test
    void shouldExcludeForbiddenProvinceInHighScoreCandidateView() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(90, 30, 30, 30));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(buildFlatSchools("高分冲", "北京", 30, 12, 16));
        response.setSafes(buildFlatSchools("高分稳", "上海", 30, 45, 18));
        response.setProtects(buildFlatSchools("高分保", "江苏", 30, 78, 14));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        queryReq.setPageSize(100);
        queryReq.getFilters().setNegativeProvinceNames(java.util.Arrays.asList("北京"));

        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);
        java.util.Map<String, Long> tierCounts = queryRes.getItems().stream()
                .collect(java.util.stream.Collectors.groupingBy(CandidateItemDTO::getTier, java.util.stream.Collectors.counting()));

        assertEquals(Integer.valueOf(60), queryRes.getTotal());
        assertTrue(queryRes.getItems().stream().noneMatch(item -> "北京".equals(item.getProvinceName())));
        assertEquals(Long.valueOf(30L), tierCounts.get("稳"));
        assertEquals(Long.valueOf(30L), tierCounts.get("保"));
        assertFalse(tierCounts.containsKey("冲"));
    }

    @Test
    void shouldApplyAndAcrossAttributesAndOrWithinAttribute() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();

        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajor("m1", "专业A"));
        schoolA.setBasicTagList(java.util.Arrays.asList("公办"));
        schoolA.getMajors().get(0).setRankTagList(java.util.Arrays.asList("计算机"));

        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajor("m2", "专业B"));
        schoolB.setBasicTagList(java.util.Arrays.asList("民办"));
        schoolB.getMajors().get(0).setRankTagList(java.util.Arrays.asList("法学"));

        VolunteerRecommendListResponse.VolunteerSchool schoolC = buildSchool("ps3", "s3", "学校C", "天津", 3, buildMajor("m3", "专业C"));
        schoolC.setBasicTagList(java.util.Arrays.asList("公办"));
        schoolC.getMajors().get(0).setRankTagList(java.util.Arrays.asList("法学"));

        response.setSafes(java.util.Arrays.asList(schoolA, schoolB, schoolC));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        queryReq.getFilters().setProvinceNames(java.util.Arrays.asList("北京"));
        queryReq.getFilters().setSchoolTags(java.util.Arrays.asList("公办", "民办"));
        queryReq.getFilters().setMajorTags(java.util.Arrays.asList("法学"));

        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);

        assertEquals(Integer.valueOf(1), queryRes.getTotal());
        assertEquals("学校B", queryRes.getItems().get(0).getSchoolName());
    }

    @Test
    void shouldReturnCandidateFilterOptionsFromBackend() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse.VolunteerMajor major = buildMajor("m1", "计算机科学与技术");
        major.setCategoryId("38");
        major.setSubCategoryId("47");
        VolunteerRecommendListResponse.VolunteerMajor unknownMajor = buildMajor("0", "软件工程技术");
        unknownMajor.setCategoryId("0");
        unknownMajor.setSubCategoryId("0");
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool school = buildSchool("ps1", "s1", "北京邮电大学", "北京", 1, major);
        school.setCity_name("海淀");
        school.setSchool_batch("本科");
        school.setSchool_level("211");
        school.setSchool_nature("公办");
        school.setSchool_category("理工");
        school.setBasicTagList(java.util.Arrays.asList("公办", "理工", "北京", "华东"));
        school.setRankTagList(java.util.Arrays.asList("双一流", "保研率 18%"));
        school.setPopTagList(java.util.Arrays.asList("低学费", "院校排名 12", "北京市"));
        school.getMajors().get(0).setRankTagList(java.util.Arrays.asList("计算机", "就业率 91%"));
        school.getMajors().get(0).setPlanTagList(java.util.Arrays.asList("选科要求", "意向专业类", "非意向专业类", "计划数:6"));
        VolunteerRecommendListResponse.VolunteerSchool unknownSchool =
                buildSchool("ps2", "s2", "职业技术大学", "山东", 2, unknownMajor);
        response.setSafes(java.util.Arrays.asList(school, unknownSchool));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidateFilterOptionsDTO res = planningStateService.getCandidateFilterOptions(1L, 1L);

        assertTrue(res.getProvinceNames().contains("北京"));
        assertTrue(res.getCityNames().contains("海淀"));
        assertTrue(res.getSchoolKeywords().contains("北京邮电大学"));
        assertTrue(res.getMajorKeywords().contains("计算机类"));
        assertTrue(res.getSchoolTags().contains("公办"));
        assertTrue(res.getSchoolTags().contains("理工"));
        assertTrue(res.getSchoolTags().contains("双一流"));
        assertFalse(res.getSchoolTags().contains("北京"));
        assertFalse(res.getSchoolTags().contains("北京市"));
        assertFalse(res.getSchoolTags().contains("华东"));
        assertFalse(res.getSchoolTags().contains("保研率 18%"));
        assertFalse(res.getSchoolTags().contains("院校排名 12"));
        assertTrue(res.getMajorTags().contains("计算机"));
        assertTrue(res.getMajorTags().contains("选科要求"));
        assertTrue(res.getMajorTags().contains("工学类"));
        assertFalse(res.getMajorTags().contains("意向专业"));
        assertFalse(res.getMajorTags().contains("意向专业类"));
        assertFalse(res.getMajorTags().contains("非意向专业"));
        assertFalse(res.getMajorTags().contains("非意向专业类"));
        assertTrue(res.getRegionTree().stream().anyMatch(region ->
                "北京".equals(region.getProvinceName()) && region.getCityNames().contains("海淀")));
        assertTrue(res.getGroups().stream().anyMatch(group ->
                "major.category".equals(group.getGroupCode())
                        && "majorKeywords".equals(group.getFilterField())
                        && group.getValues().contains("计算机类")));
        assertTrue(res.getGroups().stream().anyMatch(group ->
                "school.name".equals(group.getGroupCode())
                        && "schoolKeywords".equals(group.getFilterField())
                        && group.getValues().contains("北京邮电大学")));
        assertTrue(res.getGroups().stream().anyMatch(group ->
                "major.name".equals(group.getGroupCode())
                        && "majorKeywords".equals(group.getFilterField())
                        && group.getValues().contains("计算机科学与技术")));
        assertTrue(res.getMajorTree().stream().anyMatch(discipline ->
                "工学类".equals(discipline.getDisciplineName())
                        && discipline.getCategories().stream().anyMatch(category ->
                        "计算机类".equals(category.getCategoryName())
                                && category.getMajorNames().contains("计算机科学与技术"))));
        assertFalse(res.getMajorTree().isEmpty());
        CandidateFilterOptionsDTO.MajorDisciplineNodeDTO lastMajorNode =
                res.getMajorTree().get(res.getMajorTree().size() - 1);
        assertEquals("其他专业", lastMajorNode.getDisciplineName());
        assertTrue(lastMajorNode.getCategories().stream().anyMatch(category ->
                "其他专业".equals(category.getCategoryName())
                        && category.getMajorNames().contains("软件工程技术")));
        assertFalse(res.getGroups().stream().anyMatch(group -> "major.tag".equals(group.getGroupCode())));
        assertFalse(res.getMajorTags().contains("就业率 91%"));
        assertFalse(res.getMajorTags().contains("计划数:6"));
    }

    @Test
    void shouldFilterCandidatePoolBySchoolAndMajorKeywords() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerMajor software = buildMajor("m1", "软件工程(中外合作)");
        software.setCategoryId("38");
        software.setSubCategoryId("47");
        VolunteerRecommendListResponse.VolunteerMajor accounting = buildMajor("m2", "会计学");
        accounting.setCategoryId("22");
        accounting.setSubCategoryId("26");
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool(
                "ps1", "s1", "北京邮电大学", "北京", 1, software);
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool(
                "ps2", "s2", "上海财经大学", "上海", 2, accounting);
        response.setSafes(java.util.Arrays.asList(schoolA, schoolB));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidateFilterOptionsDTO options = planningStateService.getCandidateFilterOptions(1L, 1L);
        assertTrue(options.getSchoolKeywords().contains("北京邮电大学"));
        assertTrue(options.getGroups().stream().anyMatch(group ->
                "major.name".equals(group.getGroupCode()) && group.getValues().contains("软件工程")));

        CandidatePoolQueryReq schoolReq = new CandidatePoolQueryReq();
        schoolReq.getFilters().setSchoolKeywords(java.util.Arrays.asList("北京邮电"));
        CandidatePoolQueryRes schoolRes = planningStateService.queryCandidatePool(1L, 1L, schoolReq);
        assertEquals(Integer.valueOf(1), schoolRes.getTotal());
        assertEquals("北京邮电大学", schoolRes.getItems().get(0).getSchoolName());

        CandidatePoolQueryReq majorReq = new CandidatePoolQueryReq();
        majorReq.getFilters().setMajorKeywords(java.util.Arrays.asList("软件工程"));
        CandidatePoolQueryRes majorRes = planningStateService.queryCandidatePool(1L, 1L, majorReq);
        assertEquals(Integer.valueOf(1), majorRes.getTotal());
        assertEquals("软件工程(中外合作)", majorRes.getItems().get(0).getMajorName());

        CandidatePoolQueryReq excludeReq = new CandidatePoolQueryReq();
        excludeReq.getFilters().setNegativeSchoolKeywords(java.util.Arrays.asList("北京邮电"));
        CandidatePoolQueryRes excludeRes = planningStateService.queryCandidatePool(1L, 1L, excludeReq);
        assertEquals(Integer.valueOf(1), excludeRes.getTotal());
        assertEquals("上海财经大学", excludeRes.getItems().get(0).getSchoolName());
    }

    @Test
    void shouldUseDisplaySchoolNameForMajorGroupSchoolNameFilter() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        SchoolVO standardSchool = new SchoolVO();
        standardSchool.setSchoolId("s1");
        standardSchool.setSchoolName("天津财经大学珠江学院");
        when(schoolManager.getSchoolById("s1")).thenReturn(standardSchool);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool group = buildSchool(
                "ps1",
                "s1",
                "天津财经大学珠江学院(01)专业组",
                "天津",
                1,
                buildMajor("m1", "金融学"));
        VolunteerRecommendListResponse.VolunteerSchool other = buildSchool(
                "ps2",
                "s2",
                "上海财经大学(02)专业组",
                "上海",
                2,
                buildMajor("m2", "会计学"));
        response.setSafes(java.util.Arrays.asList(group, other));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidateFilterOptionsDTO options = planningStateService.getCandidateFilterOptions(1L, 1L);
        assertTrue(options.getSchoolKeywords().contains("天津财经大学珠江学院"));
        assertFalse(options.getSchoolKeywords().contains("天津财经大学珠江学院(01)专业组"));

        CandidatePoolQueryReq includeReq = new CandidatePoolQueryReq();
        includeReq.getFilters().setSchoolKeywords(java.util.Arrays.asList("天津财经大学珠江学院"));
        CandidatePoolQueryRes includeRes = planningStateService.queryCandidatePool(1L, 1L, includeReq);
        assertEquals(Integer.valueOf(1), includeRes.getTotal());
        assertEquals("天津财经大学珠江学院(01)专业组", includeRes.getItems().get(0).getSchoolName());
        assertEquals("天津财经大学珠江学院", includeRes.getItems().get(0).getDisplaySchoolName());

        CandidatePoolQueryReq excludeReq = new CandidatePoolQueryReq();
        excludeReq.getFilters().setNegativeSchoolKeywords(java.util.Arrays.asList("天津财经大学珠江学院"));
        CandidatePoolQueryRes excludeRes = planningStateService.queryCandidatePool(1L, 1L, excludeReq);
        assertEquals(Integer.valueOf(1), excludeRes.getTotal());
        assertEquals("上海财经大学(02)专业组", excludeRes.getItems().get(0).getSchoolName());
    }

    @Test
    void shouldResolveDisplaySchoolNameForLegacyCandidatePoolWithoutStoredField() {
        bindPlanningStateStore();

        SchoolVO standardSchool = new SchoolVO();
        standardSchool.setSchoolId("s1");
        standardSchool.setSchoolName("天津财经大学珠江学院");
        when(schoolManager.getSchoolById("s1")).thenReturn(standardSchool);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);
        CandidateItemDTO legacy = new CandidateItemDTO();
        legacy.setVolunteerId("ps1_m1");
        legacy.setPlanSchoolDataId("ps1");
        legacy.setSchoolId("s1");
        legacy.setSchoolName("天津财经大学珠江学院(01)专业组");
        legacy.setProvinceName("天津");
        legacy.setCityName("天津");
        legacy.setMajorId("m1");
        legacy.setMajorName("金融学");
        legacy.setTier("稳");
        legacy.setAdmissionRatio(55D);
        state.getCandidatePoolState().setItems(java.util.Collections.singletonList(legacy));
        state.getCandidatePoolState().setGeneratedAt("2026-06-11T10:00:00+08:00");
        state.getCandidatePoolState().setStatusCode("sufficient");
        saveStateToStore(1L, state);

        CandidateFilterOptionsDTO options = planningStateService.getCandidateFilterOptions(1L, 1L);
        assertTrue(options.getSchoolKeywords().contains("天津财经大学珠江学院"));
        assertFalse(options.getSchoolKeywords().contains("天津财经大学珠江学院(01)专业组"));

        CandidatePoolQueryReq includeReq = new CandidatePoolQueryReq();
        includeReq.getFilters().setSchoolKeywords(java.util.Arrays.asList("天津财经大学珠江学院"));
        CandidatePoolQueryRes includeRes = planningStateService.queryCandidatePool(1L, 1L, includeReq);
        assertEquals(Integer.valueOf(1), includeRes.getTotal());
        assertEquals("天津财经大学珠江学院(01)专业组", includeRes.getItems().get(0).getSchoolName());
    }

    @Test
    void shouldReuseExistingCandidatePoolWithoutRankWhenNotForcedAndNotStale() {
        bindPlanningStateStore();

        PlanningStateDTO state = planningStateService.getPlanningState(1L);
        CandidateItemDTO cached = new CandidateItemDTO();
        cached.setVolunteerId("ps1_m1");
        cached.setPlanSchoolDataId("ps1");
        cached.setSchoolName("北京工业大学");
        cached.setMajorId("m1");
        cached.setMajorName("自动化");
        cached.setTier("稳");
        cached.setFinalScore(88D);
        state.getCandidatePoolState().setItems(java.util.Collections.singletonList(cached));
        state.getCandidatePoolState().setGeneratedAt("2026-06-11T10:00:00+08:00");
        state.getStaleFlags().setCandidatePool(false);
        saveStateToStore(1L, state);

        CandidatePoolGenerateReq req = new CandidatePoolGenerateReq();
        req.setForceRegenerate(false);
        PlanningStateDTO result = planningStateService.generateCandidatePool(1L, 1L, req);

        assertEquals(1, result.getCandidatePoolState().getItems().size());
        assertEquals("ps1_m1", result.getCandidatePoolState().getItems().get(0).getVolunteerId());
        verify(volunteerBizService, never()).recommendVolunteerList(any(), any(), anyBoolean(), anyBoolean());
    }

    @Test
    void shouldFilterCandidatePoolBySchoolTagsWithAndAcrossDimensions() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool publicSchool = buildSchool(
                "ps1", "s1", "北京工业大学", "北京", 1, buildMajor("m1", "自动化"));
        publicSchool.setSchool_nature("公办");
        publicSchool.setSchool_category("理工");
        publicSchool.setBasicTagList(java.util.Arrays.asList("公办", "理工", "北京"));

        VolunteerRecommendListResponse.VolunteerSchool privateSchool = buildSchool(
                "ps2", "s2", "北京城市学院", "北京", 2, buildMajor("m2", "自动化"));
        privateSchool.setSchool_nature("民办");
        privateSchool.setSchool_category("综合");
        privateSchool.setBasicTagList(java.util.Arrays.asList("民办", "综合", "北京"));

        VolunteerRecommendListResponse.VolunteerSchool publicOutsideProvince = buildSchool(
                "ps3", "s3", "天津工业大学", "天津", 3, buildMajor("m3", "自动化"));
        publicOutsideProvince.setSchool_nature("公办");
        publicOutsideProvince.setSchool_category("理工");
        publicOutsideProvince.setBasicTagList(java.util.Arrays.asList("公办", "理工", "天津"));

        response.setSafes(java.util.Arrays.asList(publicSchool, privateSchool, publicOutsideProvince));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidatePoolQueryReq req = new CandidatePoolQueryReq();
        req.getFilters().setProvinceNames(java.util.Arrays.asList("北京"));
        req.getFilters().setSchoolTags(java.util.Arrays.asList("公办"));

        CandidatePoolQueryRes res = planningStateService.queryCandidatePool(1L, 1L, req);

        assertEquals(Integer.valueOf(1), res.getTotal());
        assertEquals("ps1_m1", res.getItems().get(0).getVolunteerId());
        assertEquals("公办", res.getItems().get(0).getSchoolNature());
        assertEquals("北京", res.getItems().get(0).getProvinceName());
    }

    @Test
    void shouldRefreshRecommendationOverlayWhenOverlayMarkedStale() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse initialResponse = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool initialSchool = buildSchool("ps1", "s1", "学校A", "北京", 3, buildMajor("m1", "专业A"));
        initialSchool.setEnroll_ratio("60");
        initialSchool.setIs_preferred(false);
        java.util.Map<String, Object> initialAlgTagMap = new java.util.HashMap<String, Object>();
        initialAlgTagMap.put("volunteer_score", 60D);
        initialSchool.setAlgTagMap(initialAlgTagMap);
        initialResponse.setSafes(java.util.Arrays.asList(initialSchool));
        initialResponse.setSprints(java.util.Collections.emptyList());
        initialResponse.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(initialResponse);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        PlanningStateDTO state = com.alibaba.fastjson.JSONObject.parseObject(stored.getDataValue(), PlanningStateDTO.class);
        state.getStaleFlags().setRecommendationOverlay(true);

        VolunteerRecommendListResponse refreshedResponse = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool refreshedSchool = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajor("m1", "专业A"));
        refreshedSchool.setEnroll_ratio("60");
        refreshedSchool.setIs_preferred(true);
        java.util.Map<String, Object> refreshedAlgTagMap = new java.util.HashMap<String, Object>();
        refreshedAlgTagMap.put("volunteer_score", 92D);
        refreshedSchool.setAlgTagMap(refreshedAlgTagMap);
        refreshedResponse.setSafes(java.util.Arrays.asList(refreshedSchool));
        refreshedResponse.setSprints(java.util.Collections.emptyList());
        refreshedResponse.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(refreshedResponse);

        ChatSessionExtraData refreshedStateData = new ChatSessionExtraData();
        refreshedStateData.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        refreshedStateData.setDataValue(com.alibaba.fastjson.JSONObject.toJSONString(state));
        reset(chatSessionExtraDataSharedService);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(refreshedStateData);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);

        assertEquals(Integer.valueOf(1), queryRes.getTotal());
        assertEquals(Double.valueOf(92D), queryRes.getItems().get(0).getFinalScore());
        assertEquals(Integer.valueOf(1), queryRes.getItems().get(0).getRankInTier());
        assertTrue(Boolean.TRUE.equals(queryRes.getItems().get(0).getPreferred()));
    }

    @Test
    void shouldUseRefreshedOverlayScoresWhenGenerateOrderedPlan() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse initialResponse = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool schoolA = buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "35"));
        java.util.Map<String, Object> schoolAAlgTagMap = new java.util.HashMap<String, Object>();
        schoolAAlgTagMap.put("volunteer_score", 65D);
        schoolA.setAlgTagMap(schoolAAlgTagMap);
        VolunteerRecommendListResponse.VolunteerSchool schoolB = buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "35"));
        java.util.Map<String, Object> schoolBAlgTagMap = new java.util.HashMap<String, Object>();
        schoolBAlgTagMap.put("volunteer_score", 55D);
        schoolB.setAlgTagMap(schoolBAlgTagMap);
        initialResponse.setSafes(java.util.Arrays.asList(schoolA, schoolB));
        initialResponse.setSprints(java.util.Collections.emptyList());
        initialResponse.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(initialResponse);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps2_m2", "ps1_m1"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        PlanningStateDTO state = com.alibaba.fastjson.JSONObject.parseObject(stored.getDataValue(), PlanningStateDTO.class);
        state.getStaleFlags().setRecommendationOverlay(true);

        VolunteerRecommendListResponse refreshedResponse = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool refreshedSchoolA = buildSchool("ps1", "s1", "学校A", "北京", 2, buildMajorWithRatio("m1", "专业A", "35"));
        java.util.Map<String, Object> refreshedSchoolAAlgTagMap = new java.util.HashMap<String, Object>();
        refreshedSchoolAAlgTagMap.put("volunteer_score", 58D);
        refreshedSchoolA.setAlgTagMap(refreshedSchoolAAlgTagMap);
        VolunteerRecommendListResponse.VolunteerSchool refreshedSchoolB = buildSchool("ps2", "s2", "学校B", "北京", 1, buildMajorWithRatio("m2", "专业B", "35"));
        java.util.Map<String, Object> refreshedSchoolBAlgTagMap = new java.util.HashMap<String, Object>();
        refreshedSchoolBAlgTagMap.put("volunteer_score", 88D);
        refreshedSchoolB.setAlgTagMap(refreshedSchoolBAlgTagMap);
        refreshedResponse.setSafes(java.util.Arrays.asList(refreshedSchoolA, refreshedSchoolB));
        refreshedResponse.setSprints(java.util.Collections.emptyList());
        refreshedResponse.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(refreshedResponse);

        ChatSessionExtraData refreshedStateData = new ChatSessionExtraData();
        refreshedStateData.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        refreshedStateData.setDataValue(com.alibaba.fastjson.JSONObject.toJSONString(state));
        reset(chatSessionExtraDataSharedService);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(refreshedStateData);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setForceRegenerate(true);
        generateReq.setRegroupByTier(true);
        PlanningStateDTO ordered = planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        assertEquals("ps2_m2", ordered.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", ordered.getOrderedPlanState().getItems().get(1).getVolunteerId());
    }

    @Test
    void shouldSelectRemoveAndLockDraftItems() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool school = new VolunteerRecommendListResponse.VolunteerSchool();
        school.setPlanSchoolDataId("ps1");
        school.setSchoolId("s1");
        school.setSchool_name("北京邮电大学");
        school.setProvince_name("北京");
        school.setCity_name("北京");
        school.setRank_in_tier(2);
        VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
        major.setMajorId("m1");
        major.setPlanMajorDataId("m1");
        major.setMajor_name("计算机科学与技术");
        school.setMajors(java.util.Arrays.asList(major));
        response.setSafes(java.util.Arrays.asList(school));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ArgumentCaptor<ChatSessionExtraData> saveCaptor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, times(1)).save(saveCaptor.capture());

        ChatSessionExtraData stored = new ChatSessionExtraData();
        stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        stored.setDataValue(saveCaptor.getValue().getDataValue());
        reset(chatSessionExtraDataSharedService);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1"));
        PlanningStateDTO selected = planningStateService.selectDraftItems(1L, selectReq);
        assertEquals(Integer.valueOf(1), selected.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(1), selected.getOrderedPlanState().getSummary().getTotal());
        assertEquals("ps1_m1", selected.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("drafting", selected.getPhase());
        ArgumentCaptor<PlanningBehaviorEventDTO> behaviorEventCaptor = ArgumentCaptor.forClass(PlanningBehaviorEventDTO.class);
        verify(planningBehaviorEventSharedService, times(1)).saveBehaviorEvent(behaviorEventCaptor.capture());
        assertEquals("plan_add", behaviorEventCaptor.getValue().getEventType());
        assertTrue(behaviorEventCaptor.getValue().getVolunteerIds().contains("ps1_m1"));
        assertEquals("北京邮电大学", behaviorEventCaptor.getValue().getSchoolName());
        assertEquals("计算机科学与技术", behaviorEventCaptor.getValue().getMajorName());
        assertNotNull(behaviorEventCaptor.getValue().getSnapshotDigest());
        assertNotNull(behaviorEventCaptor.getValue().getEventPayloadJson());

        ArgumentCaptor<ChatSessionExtraData> updateCaptor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, times(1)).updateById(updateCaptor.capture());
        stored.setDataValue(updateCaptor.getValue().getDataValue());
        reset(chatSessionExtraDataSharedService);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftLockReq lockReq = new DraftLockReq();
        lockReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1"));
        lockReq.setLocked(true);
        PlanningStateDTO locked = planningStateService.lockDraftItems(1L, lockReq);
        assertTrue(locked.getDraftPlanState().getItems().get(0).getLocked());

        verify(chatSessionExtraDataSharedService, times(1)).updateById(updateCaptor.capture());
        stored.setDataValue(updateCaptor.getAllValues().get(updateCaptor.getAllValues().size() - 1).getDataValue());
        reset(chatSessionExtraDataSharedService);
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftRemoveReq removeReq = new DraftRemoveReq();
        removeReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1"));
        PlanningStateDTO removed = planningStateService.removeDraftItems(1L, removeReq);
        assertEquals(Integer.valueOf(0), removed.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(0), removed.getOrderedPlanState().getSummary().getTotal());
    }

    @Test
    void shouldNormalizeMajorCandidateIdentityAndPreventDuplicateSelection() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.getCode());
        CandidateItemDTO candidate = buildCandidateItem(
                "ps1_pm1_pm1", "ps1_pm1", "s1", "学校A", "稳", "专业A", 45D, 80D, 45D, false);
        candidate.setMajorId("m1");
        state.getCandidatePoolState().setItems(java.util.Arrays.asList(candidate));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_pm1_m1", "学校A", "专业A", "稳"));
        ReflectionTestUtils.invokeMethod(planningStateService,
                "recalculateWorkingPlanSummary", state.getDraftPlanState(), state.getCandidatePoolState());
        saveStateToStore(1L, state);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);

        assertEquals(Integer.valueOf(1), queryRes.getTotal());
        assertEquals("ps1_pm1_m1", queryRes.getItems().get(0).getVolunteerId());

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_pm1_pm1"));
        PlanningStateDTO selected = planningStateService.selectDraftItems(1L, selectReq);

        assertEquals(Integer.valueOf(1), selected.getDraftPlanState().getSummary().getTotal());
        assertEquals("ps1_pm1_m1", selected.getDraftPlanState().getItems().get(0).getVolunteerId());
        assertEquals(Integer.valueOf(7), selected.getVersion());
        verify(planningBehaviorEventSharedService, never()).saveBehaviorEvent(any(PlanningBehaviorEventDTO.class));
    }

    @Test
    void shouldRecordOnlyActualPlanAddAndRemoveBehaviorEvents() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.getCode());
        state.getCandidatePoolState().setItems(java.util.Arrays.asList(
                buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "稳", "专业A", 45D, 80D, 45D, false),
                buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "保", "专业B", 65D, 70D, 65D, false)
        ));
        state.getDraftPlanState().getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A", "稳"));
        saveStateToStore(1L, state);
        reset(planningBehaviorEventSharedService);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "missing"));
        PlanningStateDTO selected = planningStateService.selectDraftItems(1L, selectReq);

        assertEquals(Integer.valueOf(2), selected.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(8), selected.getVersion());
        ArgumentCaptor<PlanningBehaviorEventDTO> behaviorEventCaptor = ArgumentCaptor.forClass(PlanningBehaviorEventDTO.class);
        verify(planningBehaviorEventSharedService, times(1)).saveBehaviorEvent(behaviorEventCaptor.capture());
        assertEquals("plan_add", behaviorEventCaptor.getValue().getEventType());
        assertEquals(java.util.Arrays.asList("ps2_m2"), behaviorEventCaptor.getValue().getVolunteerIds());

        reset(planningBehaviorEventSharedService);
        DraftRemoveReq removeMissingReq = new DraftRemoveReq();
        removeMissingReq.setVolunteerIds(java.util.Arrays.asList("missing"));
        PlanningStateDTO unchanged = planningStateService.removeDraftItems(1L, removeMissingReq);
        assertEquals(Integer.valueOf(2), unchanged.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(8), unchanged.getVersion());
        verify(planningBehaviorEventSharedService, never()).saveBehaviorEvent(any(PlanningBehaviorEventDTO.class));

        reset(planningBehaviorEventSharedService);
        DraftRemoveReq removeReq = new DraftRemoveReq();
        removeReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "missing"));
        PlanningStateDTO removed = planningStateService.removeDraftItems(1L, removeReq);
        assertEquals(Integer.valueOf(1), removed.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(9), removed.getVersion());
        verify(planningBehaviorEventSharedService, times(1)).saveBehaviorEvent(behaviorEventCaptor.capture());
        PlanningBehaviorEventDTO removeEvent = behaviorEventCaptor.getAllValues().get(behaviorEventCaptor.getAllValues().size() - 1);
        assertEquals("plan_remove", removeEvent.getEventType());
        assertEquals(java.util.Arrays.asList("ps1_m1"), removeEvent.getVolunteerIds());
    }

    @Test
    void shouldKeepMajorGroupCandidateIdentityWhenQueryCandidatePool() {
        bindPlanningStateStore();

        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.majorGroup.getCode());
        CandidateItemDTO candidate = buildCandidateItem(
                "group1_pm1", "group1", "s1", "学校A第101组", "稳", "专业A", 45D, 80D, 45D, false);
        candidate.setMajorId("m1");
        state.getCandidatePoolState().setItems(java.util.Arrays.asList(candidate));
        saveStateToStore(1L, state);

        CandidatePoolQueryReq queryReq = new CandidatePoolQueryReq();
        CandidatePoolQueryRes queryRes = planningStateService.queryCandidatePool(1L, 1L, queryReq);

        assertEquals(Integer.valueOf(1), queryRes.getTotal());
        assertEquals("group1_pm1", queryRes.getItems().get(0).getVolunteerId());
    }

    @Test
    void shouldGenerateAndMoveOrderedPlan() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(3, 1, 1, 1);
        baseData.setVolunteerModel(VolunteerModel.major);
        response.setBaseData(baseData);
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "北京航空航天大学", "北京", 1, buildMajor("m1", "飞行器设计"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "北京邮电大学", "北京", 2, buildMajor("m2", "计算机科学与技术"))));
        response.setProtects(java.util.Arrays.asList(buildSchool("ps3", "s3", "河北工业大学", "河北", 3, buildMajor("m3", "自动化"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps2_m2", "ps1_m1", "ps3_m3"));
        PlanningStateDTO draftState = planningStateService.selectDraftItems(1L, selectReq);
        assertEquals(Integer.valueOf(3), draftState.getDraftPlanState().getSummary().getTotal());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        PlanningStateDTO ordered = planningStateService.generateOrderedPlan(1L, 1L, generateReq);
        assertEquals("ps1_m1", ordered.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ordered", ordered.getPhase());
        assertFalse(ordered.getStaleFlags().getOrderedPlan());
        assertTrue(ordered.getOrderedPlanState().getSummary().getGradientOk());
        assertTrue(ordered.getOrderedPlanState().getSummary().getSafetyOk());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        reset(planningBehaviorEventSharedService);

        OrderedMoveReq moveReq = new OrderedMoveReq();
        moveReq.setVolunteerId("ps1_m1");
        moveReq.setTargetPosition(3);
        PlanningStateDTO moved = planningStateService.moveOrderedItem(1L, moveReq);
        assertEquals("ps2_m2", moved.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps3_m3", moved.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps1_m1", moved.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertEquals("user", moved.getOrderedPlanState().getItems().get(2).getOrderedBy());
        assertTrue(moved.getStaleFlags().getReview());
        assertTrue(moved.getStaleFlags().getPlanAdjustment());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        ArgumentCaptor<PlanningBehaviorEventDTO> behaviorEventCaptor = ArgumentCaptor.forClass(PlanningBehaviorEventDTO.class);
        verify(planningBehaviorEventSharedService, times(1)).saveBehaviorEvent(behaviorEventCaptor.capture());
        assertEquals("plan_item_move", behaviorEventCaptor.getValue().getEventType());
        assertEquals("major", behaviorEventCaptor.getValue().getMode());
        assertNotNull(behaviorEventCaptor.getValue().getSnapshotDigest());
        assertNotNull(behaviorEventCaptor.getValue().getEventPayloadJson());
        JSONObject movePayload = JSONObject.parseObject(behaviorEventCaptor.getValue().getEventPayloadJson());
        assertEquals(behaviorEventCaptor.getValue().getPlanVersion(), movePayload.getInteger("planVersion"));

    }

    @Test
    void shouldAllowMoveLockedOrderedItems() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajor("m1", "专业A"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajor("m2", "专业B"))));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftLockReq lockReq = new DraftLockReq();
        lockReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1"));
        lockReq.setLocked(true);
        planningStateService.lockDraftItems(1L, lockReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        PlanningStateDTO ordered = planningStateService.generateOrderedPlan(1L, 1L, generateReq);
        assertTrue(Boolean.TRUE.equals(ordered.getOrderedPlanState().getItems().get(0).getLocked()));

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedMoveReq moveReq = new OrderedMoveReq();
        moveReq.setVolunteerId("ps1_m1");
        moveReq.setTargetPosition(2);
        PlanningStateDTO moved = planningStateService.moveOrderedItem(1L, moveReq);
        assertEquals("ps2_m2", moved.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", moved.getOrderedPlanState().getItems().get(1).getVolunteerId());

    }

    @Test
    void shouldMoveAcrossDraftLockedItemsWithoutTreatingThemAsPinned() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajor("m1", "专业A")),
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajor("m2", "专业B"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 1, buildMajor("m3", "专业C")),
                buildSchool("ps4", "s4", "学校D", "北京", 2, buildMajor("m4", "专业D"))
        ));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftLockReq lockReq = new DraftLockReq();
        lockReq.setVolunteerIds(java.util.Arrays.asList("ps2_m2"));
        planningStateService.lockDraftItems(1L, lockReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        PlanningStateDTO ordered = planningStateService.generateOrderedPlan(1L, 1L, generateReq);
        assertEquals("ps1_m1", ordered.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m2", ordered.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps3_m3", ordered.getOrderedPlanState().getItems().get(2).getVolunteerId());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedMoveReq moveDownReq = new OrderedMoveReq();
        moveDownReq.setVolunteerId("ps1_m1");
        moveDownReq.setTargetPosition(2);
        PlanningStateDTO movedDown = planningStateService.moveOrderedItem(1L, moveDownReq);
        assertEquals("ps2_m2", movedDown.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", movedDown.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps3_m3", movedDown.getOrderedPlanState().getItems().get(2).getVolunteerId());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedMoveReq moveUpReq = new OrderedMoveReq();
        moveUpReq.setVolunteerId("ps1_m1");
        moveUpReq.setTargetPosition(1);
        PlanningStateDTO movedUp = planningStateService.moveOrderedItem(1L, moveUpReq);
        assertEquals("ps1_m1", movedUp.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m2", movedUp.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps3_m3", movedUp.getOrderedPlanState().getItems().get(2).getVolunteerId());
    }

    @Test
    void shouldIgnoreHistoricalPinnedOrderedItemsWhenMoving() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajor("m1", "专业A")),
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajor("m2", "专业B"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 1, buildMajor("m3", "专业C"))
        ));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        PlanningStateDTO pinned = planningStateService.generateOrderedPlan(1L, 1L, generateReq);
        pinned.getOrderedPlanState().getItems().stream()
                .filter(item -> "ps2_m2".equals(item.getVolunteerId()))
                .findFirst()
                .ifPresent(item -> {
                    item.setPinned(true);
                    item.setPinnedPosition(2);
                });
        saveStateToStore(1L, pinned);
        assertTrue(Boolean.TRUE.equals(pinned.getOrderedPlanState().getItems().get(1).getPinned()));

        stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedMoveReq moveReq = new OrderedMoveReq();
        moveReq.setVolunteerId("ps1_m1");
        moveReq.setTargetPosition(2);
        PlanningStateDTO moved = planningStateService.moveOrderedItem(1L, moveReq);
        assertEquals("ps2_m2", moved.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", moved.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps3_m3", moved.getOrderedPlanState().getItems().get(2).getVolunteerId());
    }

    @Test
    void shouldSortMajorPlanByAdmissionRatioAndIgnoreHistoricalPinnedPosition() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setCandidatePoolState(new CandidatePoolStateDTO());
        state.getCandidatePoolState().setVolunteerModel(VolunteerModel.major.name());
        state.getCandidatePoolState().setRequiredCount(4);
        state.getCandidatePoolState().getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 65D, 80D, 65D, false));
        CandidateItemDTO lowRiskCandidate = buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "冲", "专业B", 20D, 60D, 20D, false);
        lowRiskCandidate.setSchoolRank(120);
        state.getCandidatePoolState().getItems().add(lowRiskCandidate);
        state.getCandidatePoolState().getItems().add(buildCandidateItem("ps3_m3", "ps3", "s3", "学校C", "稳", "专业C", 42D, 95D, 42D, false));
        state.getCandidatePoolState().getItems().add(buildCandidateItem("ps4_m4", "ps4", "s4", "学校D", "保", "专业D", 55D, 70D, 55D, false));
        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        OrderedItemDTO pinned = buildOrderedItem("ps4_m4", "学校D", "专业D", "保", 2);
        pinned.setPinned(true);
        pinned.setPinnedPosition(2);
        orderedPlanState.getItems().add(pinned);
        orderedPlanState.getItems().add(buildOrderedItem("ps3_m3", "学校C", "专业C", "稳", 3));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "冲", 4));
        state.setOrderedPlanState(orderedPlanState);
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateOrderedSummary", orderedPlanState, state.getCandidatePoolState());
        saveStateToStore(1L, state);

        OrderedPlanSortReq sortReq = new OrderedPlanSortReq();
        sortReq.setSortField("admissionRatio");
        PlanningStateDTO sorted = planningStateService.sortOrderedPlan(1L, sortReq);

        assertEquals("ps2_m2", sorted.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps3_m3", sorted.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps4_m4", sorted.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertEquals("ps1_m1", sorted.getOrderedPlanState().getItems().get(3).getVolunteerId());
        ArgumentCaptor<PlanningBehaviorEventDTO> behaviorEventCaptor = ArgumentCaptor.forClass(PlanningBehaviorEventDTO.class);
        verify(planningBehaviorEventSharedService, times(1)).saveBehaviorEvent(behaviorEventCaptor.capture());
        assertEquals("plan_sort_apply", behaviorEventCaptor.getValue().getEventType());
        assertEquals("admissionRatio", behaviorEventCaptor.getValue().getSortKey());
        assertNotNull(behaviorEventCaptor.getValue().getSnapshotDigest());
        assertNotNull(behaviorEventCaptor.getValue().getEventPayloadJson());
        JSONObject sortPayload = JSONObject.parseObject(behaviorEventCaptor.getValue().getEventPayloadJson());
        assertEquals(behaviorEventCaptor.getValue().getPlanVersion(), sortPayload.getInteger("planVersion"));
        JSONArray sortItems = sortPayload.getJSONArray("items");
        assertNotNull(sortItems);
        assertEquals("ps2_m2", sortItems.getJSONObject(0).getString("volunteerId"));
        assertEquals("s2", sortItems.getJSONObject(0).getString("schoolId"));
        assertEquals(Integer.valueOf(120), sortItems.getJSONObject(0).getInteger("schoolRank"));
        assertEquals(Double.valueOf(20D), sortItems.getJSONObject(0).getDouble("admissionRatio"));
        assertEquals(Double.valueOf(20D), sortItems.getJSONObject(0).getDouble("schoolEnrollRatio"));
        assertEquals(Double.valueOf(60D), sortItems.getJSONObject(0).getDouble("finalScore"));
        assertEquals(Integer.valueOf(1), sortItems.getJSONObject(0).getInteger("position"));
        assertTrue(sorted.getStaleFlags().getReview());
    }

    @Test
    void shouldExposeOrderedUnitTotalMajorCountFromFullMajorGroup() {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        CandidateItemDTO majorA = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A第01组", "冲", "专业A1", 35D, 60D, 35D, false);
        majorA.setSchoolUnitCode("001");
        CandidateItemDTO majorB = buildCandidateItem("ps1_m2", "ps1", "s1", "学校A第01组", "冲", "专业A2", 33D, 58D, 35D, false);
        majorB.setSchoolUnitCode("001");
        CandidateItemDTO majorC = buildCandidateItem("ps1_m3", "ps1", "s1", "学校A第01组", "冲", "专业A3", 31D, 56D, 35D, false);
        majorC.setSchoolUnitCode("001");
        candidatePoolState.getItems().add(majorA);
        candidatePoolState.getItems().add(majorB);
        candidatePoolState.getItems().add(majorC);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A第01组", "专业A1", "冲", 1));
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m2", "学校A第01组", "专业A2", "冲", 2));
        orderedPlanState.setUnits(ReflectionTestUtils.invokeMethod(planningStateService,
                "buildOrderedUnitsFromOrderedItems", orderedPlanState.getItems(), null, candidatePoolState.getItems()));

        assertEquals(1, orderedPlanState.getUnits().size());
        OrderedUnitDTO unit = orderedPlanState.getUnits().get(0);
        assertEquals("ps1", unit.getUnitId());
        assertEquals("ps1", unit.getPlanSchoolDataId());
        assertEquals("s1", unit.getSchoolId());
        assertEquals("001", unit.getSchoolUnitCode());
        assertEquals(2, unit.getMajorItems().size());
        assertEquals(Integer.valueOf(3), unit.getTotalMajorCount());
    }

    @Test
    void shouldBackfillOrderedUnitTotalMajorCountFromInitialUnitsForLegacyWorkspace() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A第01组", "冲", "专业A1", 35D, 60D, 35D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m2", "ps1", "s1", "学校A第01组", "冲", "专业A2", 33D, 58D, 35D, false));
        state.setCandidatePoolState(candidatePoolState);

        PlanningUnitDTO initialUnit = new PlanningUnitDTO();
        initialUnit.setUnitId("ps1");
        initialUnit.setPlanSchoolDataId("ps1");
        initialUnit.setSchoolId("s1");
        initialUnit.setSchoolName("学校A第01组");
        initialUnit.setTotalMajorCount(3);
        state.getInitialRecommendationState().getUnits().add(initialUnit);

        OrderedUnitDTO orderedUnit = new OrderedUnitDTO();
        orderedUnit.setUnitId("ps1");
        orderedUnit.setSchoolName("学校A第01组");
        PlanningUnitMajorDTO majorA = new PlanningUnitMajorDTO();
        majorA.setVolunteerId("ps1_m1");
        majorA.setMajorName("专业A1");
        PlanningUnitMajorDTO majorB = new PlanningUnitMajorDTO();
        majorB.setVolunteerId("ps1_m2");
        majorB.setMajorName("专业A2");
        orderedUnit.setMajorItems(java.util.Arrays.asList(majorA, majorB));
        state.getOrderedPlanState().getUnits().add(orderedUnit);

        ReflectionTestUtils.invokeMethod(planningStateService, "normalizeMajorGroupUnitMetadata", state);

        OrderedUnitDTO normalized = state.getOrderedPlanState().getUnits().get(0);
        assertEquals("ps1", normalized.getPlanSchoolDataId());
        assertEquals("s1", normalized.getSchoolId());
        assertEquals(2, normalized.getMajorItems().size());
        assertEquals(Integer.valueOf(3), normalized.getTotalMajorCount());
    }

    @Test
    void shouldSortMajorGroupPlanByFinalScoreWithoutBreakingGroupMajors() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        candidatePoolState.setRequiredCount(2);
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A1", 35D, 60D, 35D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m2", "ps1", "s1", "学校A", "冲", "专业A2", 33D, 58D, 35D, false));
        CandidateItemDTO unitMoveCandidate = buildCandidateItem("ps2_m3", "ps2", "s2", "学校B", "稳", "专业B1", 45D, 90D, 45D, false);
        unitMoveCandidate.setSchoolRank(80);
        candidatePoolState.getItems().add(unitMoveCandidate);
        candidatePoolState.getItems().add(buildCandidateItem("ps2_m4", "ps2", "s2", "学校B", "稳", "专业B2", 48D, 88D, 45D, false));
        state.setCandidatePoolState(candidatePoolState);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A1", "冲", 1));
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m2", "学校A", "专业A2", "冲", 2));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m3", "学校B", "专业B1", "稳", 3));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m4", "学校B", "专业B2", "稳", 4));
        orderedPlanState.setUnits(ReflectionTestUtils.invokeMethod(planningStateService,
                "buildOrderedUnitsFromOrderedItems", orderedPlanState.getItems(), state.getDraftPlanState(), candidatePoolState.getItems()));
        state.setOrderedPlanState(orderedPlanState);
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateOrderedSummary", orderedPlanState, candidatePoolState);
        saveStateToStore(1L, state);

        assertEquals("ps1_m2", orderedPlanState.getUnits().get(0).getMajorItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", orderedPlanState.getUnits().get(0).getMajorItems().get(1).getVolunteerId());
        assertEquals("ps2_m3", orderedPlanState.getUnits().get(1).getMajorItems().get(0).getVolunteerId());
        assertEquals("ps2_m4", orderedPlanState.getUnits().get(1).getMajorItems().get(1).getVolunteerId());

        OrderedPlanSortReq sortReq = new OrderedPlanSortReq();
        sortReq.setSortField("finalScore");
        PlanningStateDTO sorted = planningStateService.sortOrderedPlan(1L, sortReq);

        assertEquals("ps2_m3", sorted.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m4", sorted.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps1_m1", sorted.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertEquals("ps1_m2", sorted.getOrderedPlanState().getItems().get(3).getVolunteerId());
        assertEquals("ps2", sorted.getOrderedPlanState().getUnits().get(0).getUnitId());
        assertEquals("ps2_m3", sorted.getOrderedPlanState().getUnits().get(0).getMajorItems().get(0).getVolunteerId());
        assertEquals("ps2_m4", sorted.getOrderedPlanState().getUnits().get(0).getMajorItems().get(1).getVolunteerId());
        assertEquals("ps1", sorted.getOrderedPlanState().getUnits().get(1).getUnitId());
        ArgumentCaptor<PlanningBehaviorEventDTO> behaviorEventCaptor = ArgumentCaptor.forClass(PlanningBehaviorEventDTO.class);
        verify(planningBehaviorEventSharedService, times(1)).saveBehaviorEvent(behaviorEventCaptor.capture());
        assertEquals("plan_sort_apply", behaviorEventCaptor.getValue().getEventType());
        assertEquals("finalScore", behaviorEventCaptor.getValue().getSortKey());
        assertNotNull(behaviorEventCaptor.getValue().getSnapshotDigest());
        assertNotNull(behaviorEventCaptor.getValue().getEventPayloadJson());
    }

    @Test
    void shouldMoveAndRemoveMajorGroupOrderedUnits() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        candidatePoolState.setRequiredCount(2);
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A1", 35D, 60D, 35D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m2", "ps1", "s1", "学校A", "冲", "专业A2", 33D, 58D, 35D, false));
        CandidateItemDTO unitMoveCandidate = buildCandidateItem("ps2_m3", "ps2", "s2", "学校B", "稳", "专业B1", 45D, 90D, 45D, false);
        unitMoveCandidate.setSchoolRank(80);
        candidatePoolState.getItems().add(unitMoveCandidate);
        candidatePoolState.getItems().add(buildCandidateItem("ps2_m4", "ps2", "s2", "学校B", "稳", "专业B2", 48D, 88D, 45D, false));
        state.setCandidatePoolState(candidatePoolState);

        DraftPlanStateDTO draftPlanState = new DraftPlanStateDTO();
        draftPlanState.getItems().add(buildDraftItem("ps1_m1", "学校A", "专业A1", "冲"));
        draftPlanState.getItems().add(buildDraftItem("ps1_m2", "学校A", "专业A2", "冲"));
        draftPlanState.getItems().add(buildDraftItem("ps2_m3", "学校B", "专业B1", "稳"));
        draftPlanState.getItems().add(buildDraftItem("ps2_m4", "学校B", "专业B2", "稳"));
        ReflectionTestUtils.invokeMethod(planningStateService, "syncWorkingPlanUnitsWithItems", draftPlanState, candidatePoolState.getItems(), candidatePoolState);
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateWorkingPlanSummary", draftPlanState, candidatePoolState);
        state.setDraftPlanState(draftPlanState);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A1", "冲", 1));
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m2", "学校A", "专业A2", "冲", 2));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m3", "学校B", "专业B1", "稳", 3));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m4", "学校B", "专业B2", "稳", 4));
        orderedPlanState.setUnits(ReflectionTestUtils.invokeMethod(planningStateService,
                "buildOrderedUnitsFromOrderedItems", orderedPlanState.getItems(), draftPlanState, candidatePoolState.getItems()));
        state.setOrderedPlanState(orderedPlanState);
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateOrderedSummary", orderedPlanState, candidatePoolState);
        saveStateToStore(1L, state);

        OrderedUnitMoveReq moveReq = new OrderedUnitMoveReq();
        moveReq.setUnitId("ps2");
        moveReq.setTargetPosition(1);
        PlanningStateDTO moved = planningStateService.moveOrderedUnit(1L, moveReq);
        assertEquals("ps2_m3", moved.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m4", moved.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps1_m1", moved.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertEquals("ps1_m2", moved.getOrderedPlanState().getItems().get(3).getVolunteerId());
        assertEquals("ps2", moved.getOrderedPlanState().getUnits().get(0).getUnitId());
        assertTrue(moved.getStaleFlags().getReview());

        saveStateToStore(1L, moved);
        OrderedUnitRemoveReq removeReq = new OrderedUnitRemoveReq();
        removeReq.setUnitIds(java.util.Arrays.asList("ps1"));
        PlanningStateDTO removed = planningStateService.removeOrderedUnits(1L, removeReq);
        assertEquals(2, removed.getOrderedPlanState().getItems().size());
        assertEquals("ps2_m3", removed.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m4", removed.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals(1, removed.getOrderedPlanState().getUnits().size());
        assertEquals("ps2", removed.getOrderedPlanState().getUnits().get(0).getUnitId());
        assertEquals(2, removed.getDraftPlanState().getItems().size());
        assertEquals(1, removed.getDraftPlanState().getUnits().size());
        ArgumentCaptor<PlanningBehaviorEventDTO> behaviorEventCaptor = ArgumentCaptor.forClass(PlanningBehaviorEventDTO.class);
        verify(planningBehaviorEventSharedService, times(2)).saveBehaviorEvent(behaviorEventCaptor.capture());
        assertEquals("plan_unit_move", behaviorEventCaptor.getAllValues().get(0).getEventType());
        assertTrue(behaviorEventCaptor.getAllValues().get(0).getUnitIds().contains("ps2"));
        assertNotNull(behaviorEventCaptor.getAllValues().get(0).getSnapshotDigest());
        assertNotNull(behaviorEventCaptor.getAllValues().get(0).getEventPayloadJson());
        JSONObject unitMovePayload = JSONObject.parseObject(behaviorEventCaptor.getAllValues().get(0).getEventPayloadJson());
        JSONArray unitMoveItems = unitMovePayload.getJSONArray("items");
        assertNotNull(unitMoveItems);
        assertEquals("ps2_m3", unitMoveItems.getJSONObject(0).getString("volunteerId"));
        assertEquals("s2", unitMoveItems.getJSONObject(0).getString("schoolId"));
        assertEquals(Integer.valueOf(80), unitMoveItems.getJSONObject(0).getInteger("schoolRank"));
        assertEquals(Double.valueOf(45D), unitMoveItems.getJSONObject(0).getDouble("admissionRatio"));
        assertEquals(Double.valueOf(45D), unitMoveItems.getJSONObject(0).getDouble("schoolEnrollRatio"));
        assertEquals(Double.valueOf(90D), unitMoveItems.getJSONObject(0).getDouble("finalScore"));
        assertEquals(Integer.valueOf(1), unitMoveItems.getJSONObject(0).getInteger("position"));
        assertEquals(Integer.valueOf(2), unitMovePayload.getJSONObject("beforePositions").getInteger("ps2"));
        assertEquals(Integer.valueOf(1), unitMovePayload.getJSONObject("afterPositions").getInteger("ps2"));
        assertEquals("plan_unit_remove", behaviorEventCaptor.getAllValues().get(1).getEventType());
        assertTrue(behaviorEventCaptor.getAllValues().get(1).getUnitIds().contains("ps1"));
        assertNotNull(behaviorEventCaptor.getAllValues().get(1).getSnapshotDigest());
        assertNotNull(behaviorEventCaptor.getAllValues().get(1).getEventPayloadJson());
        JSONObject unitRemovePayload = JSONObject.parseObject(behaviorEventCaptor.getAllValues().get(1).getEventPayloadJson());
        JSONArray unitRemoveItems = unitRemovePayload.getJSONArray("items");
        assertNotNull(unitRemoveItems);
        assertEquals("ps1_m1", unitRemoveItems.getJSONObject(0).getString("volunteerId"));
        assertEquals("s1", unitRemoveItems.getJSONObject(0).getString("schoolId"));
        assertEquals(Double.valueOf(35D), unitRemoveItems.getJSONObject(0).getDouble("admissionRatio"));
    }

    @Test
    void shouldPreferDedicatedBehaviorEventStoreForExportStatus() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(2);
        saveStateToStore(1L, state);

        when(planningBehaviorEventSharedService.getLatestBySessionIdAndEventType(1L, "plan_export"))
                .thenReturn(buildBehaviorEvent("store-export", 2, "2026-05-21T10:00:00+08:00"));

        PlanningWorkspaceStateRes workspaceState = planningStateService.getPlanningWorkspaceState(1L);

        assertEquals("exported", workspaceState.getWorkflowStatus().getExportStatus());
        assertEquals("2026-05-21T10:00:00+08:00", workspaceState.getWorkflowStatus().getLastExportedAt());
    }

    @Test
    void shouldIgnoreLegacyBehaviorEventsWhenDedicatedStoreMisses() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        JSONObject legacyStateJson = JSONObject.parseObject(JSONObject.toJSONString(state));
        legacyStateJson.put("behaviorEvents", java.util.Arrays.asList(buildBehaviorEvent("legacy-export", 1, "2026-05-20T10:00:00+08:00")));
        saveRawStateToStore(1L, legacyStateJson.toJSONString());

        when(planningBehaviorEventSharedService.getLatestBySessionIdAndEventType(1L, "plan_export"))
                .thenReturn(null);

        PlanningWorkspaceStateRes workspaceState = planningStateService.getPlanningWorkspaceState(1L);

        assertEquals("not_exported", workspaceState.getWorkflowStatus().getExportStatus());
        assertEquals("方案尚未导出", workspaceState.getWorkflowStatus().getExportMessage());
    }

    @Test
    void shouldPersistExportBehaviorEventAndKeepExportStatusReady() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(1);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.major.name());
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 42D, 91D, 42D, false));
        state.setCandidatePoolState(candidatePoolState);
        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        state.setOrderedPlanState(orderedPlanState);
        saveStateToStore(1L, state);

        CreateSessionReq scoreDetail = buildScoreDetail();
        when(volunteerDataProvider.getUserScoreDetail(1L)).thenReturn(scoreDetail);
        final AtomicReference<PlanningBehaviorEventDTO> exportEventRef = new AtomicReference<PlanningBehaviorEventDTO>();
        when(planningBehaviorEventSharedService.saveBehaviorEvent(any(PlanningBehaviorEventDTO.class)))
                .thenAnswer(invocation -> {
                    PlanningBehaviorEventDTO event = invocation.getArgument(0);
                    exportEventRef.set(event);
                    return true;
                });
        when(planningBehaviorEventSharedService.getLatestBySessionIdAndEventType(1L, "plan_export"))
                .thenAnswer(invocation -> exportEventRef.get());

        PlanningStateService.ExcelExportResult exportResult = planningStateService.exportOrderedPlan(1L, 1L);

        assertNotNull(exportResult.getExcelData());
        assertTrue(exportResult.getExcelData().length > 0);
        assertNotNull(exportEventRef.get());
        assertEquals("plan_export", exportEventRef.get().getEventType());
        assertEquals(Integer.valueOf(1), exportEventRef.get().getPlanVersion());
        assertNotNull(exportEventRef.get().getSnapshotDigest());
        assertNotNull(exportEventRef.get().getEventPayloadJson());

        PlanningWorkspaceStateRes workspaceState = planningStateService.getPlanningWorkspaceState(1L);
        assertEquals("exported", workspaceState.getWorkflowStatus().getExportStatus());
        assertEquals("方案已导出", workspaceState.getWorkflowStatus().getExportMessage());
    }

    @Test
    void shouldMarkExportStatusStaleAfterPlanChanges() {
        bindPlanningStateStore();
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(1);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.major.name());
        candidatePoolState.getItems().add(buildCandidateItem("ps1_m1", "ps1", "s1", "学校A", "冲", "专业A", 42D, 91D, 42D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps2_m2", "ps2", "s2", "学校B", "稳", "专业B", 62D, 86D, 62D, false));
        state.setCandidatePoolState(candidatePoolState);
        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A", "专业A", "冲", 1));
        orderedPlanState.getItems().add(buildOrderedItem("ps2_m2", "学校B", "专业B", "稳", 2));
        state.setOrderedPlanState(orderedPlanState);
        saveStateToStore(1L, state);

        CreateSessionReq scoreDetail = buildScoreDetail();
        when(volunteerDataProvider.getUserScoreDetail(1L)).thenReturn(scoreDetail);
        final AtomicReference<PlanningBehaviorEventDTO> exportEventRef = new AtomicReference<PlanningBehaviorEventDTO>();
        when(planningBehaviorEventSharedService.saveBehaviorEvent(any(PlanningBehaviorEventDTO.class)))
                .thenAnswer(invocation -> {
                    PlanningBehaviorEventDTO event = invocation.getArgument(0);
                    if ("plan_export".equals(event.getEventType())) {
                        exportEventRef.set(event);
                    }
                    return true;
                });
        when(planningBehaviorEventSharedService.getLatestBySessionIdAndEventType(1L, "plan_export"))
                .thenAnswer(invocation -> exportEventRef.get());

        planningStateService.exportOrderedPlan(1L, 1L);
        PlanningWorkspaceStateRes exportedState = planningStateService.getPlanningWorkspaceState(1L);
        assertEquals("exported", exportedState.getWorkflowStatus().getExportStatus());

        OrderedMoveReq moveReq = new OrderedMoveReq();
        moveReq.setVolunteerId("ps1_m1");
        moveReq.setTargetPosition(2);
        planningStateService.moveOrderedItem(1L, moveReq);

        PlanningWorkspaceStateRes movedState = planningStateService.getPlanningWorkspaceState(1L);
        assertEquals("stale", movedState.getWorkflowStatus().getExportStatus());
        assertEquals("方案已调整，建议重新导出", movedState.getWorkflowStatus().getExportMessage());
    }

    @Test
    void shouldSortWithinTierByAdmissionRatioWhenGenerateOrderedPlan() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "18")),
                buildSchool("ps2", "s2", "学校B", "北京", 2, buildMajorWithRatio("m2", "专业B", "9"))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 1, buildMajorWithRatio("m3", "专业C", "42")),
                buildSchool("ps4", "s4", "学校D", "北京", 2, buildMajorWithRatio("m4", "专业D", "35"))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "学校E", "北京", 1, buildMajorWithRatio("m5", "专业E", "78"))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps4_m4", "ps2_m2", "ps5_m5", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        PlanningStateDTO ordered = planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        assertEquals("ps2_m2", ordered.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", ordered.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps4_m4", ordered.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertEquals("ps3_m3", ordered.getOrderedPlanState().getItems().get(3).getVolunteerId());
        assertEquals("ps5_m5", ordered.getOrderedPlanState().getItems().get(4).getVolunteerId());
    }

    @Test
    void shouldPrioritizeLocalProtectWithinProtectTierWhenGenerateOrderedPlan() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setProvince(new com.ytell.zhiyuan.model.dto.CreateSessionReq.Province());
        response.getUserScoreDetail().getProvince().setName("北京");
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "外省保底", "河北", 1, buildMajorWithRatio("m1", "专业A", "60")),
                buildSchool("ps2", "s2", "本省保底", "北京", 2, buildMajorWithRatio("m2", "专业B", "68"))
        ));
        response.setSprints(java.util.Collections.emptyList());
        response.setSafes(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        PlanningStateDTO ordered = planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        assertEquals("ps2_m2", ordered.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps1_m1", ordered.getOrderedPlanState().getItems().get(1).getVolunteerId());
    }

    @Test
    void shouldAppendNewDraftItemsToOrderedPlanWithoutResorting() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "15"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "北京", 1, buildMajorWithRatio("m2", "专业B", "35")),
                buildSchool("ps3", "s3", "学校C", "北京", 2, buildMajorWithRatio("m3", "专业C", "38"))
        ));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq firstSelectReq = new DraftSelectReq();
        firstSelectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2"));
        planningStateService.selectDraftItems(1L, firstSelectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        PlanningStateDTO ordered = planningStateService.generateOrderedPlan(1L, 1L, generateReq);
        assertEquals("ps1_m1", ordered.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m2", ordered.getOrderedPlanState().getItems().get(1).getVolunteerId());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq appendSelectReq = new DraftSelectReq();
        appendSelectReq.setVolunteerIds(java.util.Arrays.asList("ps3_m3"));
        PlanningStateDTO appended = planningStateService.selectDraftItems(1L, appendSelectReq);

        assertEquals("ps1_m1", appended.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m2", appended.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps3_m3", appended.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertFalse(appended.getStaleFlags().getOrderedPlan());
    }

    @Test
    void shouldSyncDraftAndOrderedUnitsWhenSelectDraftItemsInMajorGroupMode() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(2, 1, 1, 0);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(2);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "55"));
        sprintGroup.setEnroll_ratio("45");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "55"),
                buildMajorWithRatio("m2", "专业A2", "42"),
                buildMajorWithRatio("m3", "专业A3", "35")
        ));

        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1,
                buildMajorWithRatio("m4", "专业B1", "78"));
        safeGroup.setEnroll_ratio("62");
        safeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业B1", "78"),
                buildMajorWithRatio("m5", "专业B2", "66"),
                buildMajorWithRatio("m6", "专业B3", "59")
        ));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(safeGroup));
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m4"));
        PlanningStateDTO selected = planningStateService.selectDraftItems(1L, selectReq);

        assertEquals(2, selected.getDraftPlanState().getUnits().size());
        assertEquals("ps1", selected.getDraftPlanState().getUnits().get(0).getUnitId());
        assertEquals(2, selected.getDraftPlanState().getUnits().get(0).getMajorItems().size());
        assertEquals("ps2", selected.getDraftPlanState().getUnits().get(1).getUnitId());
        assertEquals(1, selected.getDraftPlanState().getUnits().get(1).getMajorItems().size());
        assertEquals(2, selected.getOrderedPlanState().getUnits().size());
        assertEquals("ps1", selected.getOrderedPlanState().getUnits().get(0).getUnitId());
        assertEquals(2, selected.getOrderedPlanState().getUnits().get(0).getMajorItems().size());
        assertEquals("ps2", selected.getOrderedPlanState().getUnits().get(1).getUnitId());
        assertEquals(1, selected.getOrderedPlanState().getUnits().get(1).getMajorItems().size());
    }

    @Test
    void shouldRunReviewAndClearReviewStaleFlag() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setTotalScore(560);
        response.getUserScoreDetail().setProvince(new com.ytell.zhiyuan.model.dto.CreateSessionReq.Province());
        response.getUserScoreDetail().getProvince().setName("北京");
        response.getUserScoreDetail().setBatch(new com.ytell.zhiyuan.model.dto.CreateSessionReq.Batch());
        response.getUserScoreDetail().getBatch().setScore(540F);
        response.setBaseData(new VolunteerRecommendListResponse.BaseData());
        response.getBaseData().setNeed_count(4);
        response.getBaseData().setVolunteerCount(new com.ytell.zhiyuan.model.dto.CreateSessionReq.VolunteerCount());
        response.getBaseData().getVolunteerCount().setMajorCount(2);
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "北京航空航天大学", "北京", 1,
                buildMajorWithMeta("m1", "飞行器设计", "20", "25000", java.util.Arrays.asList("物理"), java.util.Arrays.asList("国家专项")))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "北京邮电大学", "北京", 2,
                buildMajorWithMeta("m2", "计算机科学与技术", "35", "8000", java.util.Arrays.asList("单科数学"), java.util.Collections.emptyList()))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "河北工业大学", "河北", 3,
                        buildMajorWithMeta("m3", "自动化（中外合作办学）", "70", "15000", java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps4", "s4", "北京信息科技大学", "北京", 4,
                        buildMajorWithMeta("m4", "信息工程", "62", "8000", java.util.Collections.emptyList(), java.util.Collections.emptyList()))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(false);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        ReviewStateDTO reviewState = planningStateService.runReview(1L, 1L);

        assertEquals("completed", reviewState.getStatus());
        assertEquals(Integer.valueOf(14), reviewState.getSummary().getTotal());
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "group_inner_safety_guard".equals(check.getCode()) && check.getPassed()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "count_validation".equals(check.getCode()) && !check.getPassed()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "safety_guard".equals(check.getCode()) && !check.getPassed()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "high_tuition".equals(check.getCode()) && !check.getPassed()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "admission_limit".equals(check.getCode()) && !check.getPassed()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "special_enrollment".equals(check.getCode()) && !check.getPassed()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "edge_score".equals(check.getCode()) && !check.getPassed()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check -> "cooperative_program".equals(check.getCode()) && !check.getPassed()));
        assertTrue(reviewState.getCompensationPreview().getTotalActions() > 0);
        assertTrue(reviewState.getChecks().stream().anyMatch(check ->
                "count_validation".equals(check.getCode()) && !check.getSuggestedCompensations().isEmpty()));
        assertTrue(reviewState.getChecks().stream().anyMatch(check ->
                "safety_guard".equals(check.getCode()) && !check.getSuggestedCompensations().isEmpty()));

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        PlanningStateDTO state = planningStateService.getPlanningState(1L);
        assertFalse(state.getStaleFlags().getReview());
        assertEquals("reviewed", state.getPhase());
    }

    @Test
    void shouldExposeMissingCountCompensationThroughReviewAndFixProposal() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setTotalScore(550);
        response.getUserScoreDetail().setProvince(new com.ytell.zhiyuan.model.dto.CreateSessionReq.Province());
        response.getUserScoreDetail().getProvince().setName("北京");
        response.setBaseData(new VolunteerRecommendListResponse.BaseData());
        response.getBaseData().setNeed_count(4);
        response.setSprints(java.util.Arrays.asList(buildSchool("ps1", "s1", "北京航空航天大学", "北京", 1, buildMajor("m1", "飞行器设计"))));
        response.setSafes(java.util.Arrays.asList(buildSchool("ps2", "s2", "北京邮电大学", "北京", 2, buildMajor("m2", "计算机科学与技术"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "河北工业大学", "河北", 3, buildMajor("m3", "自动化")),
                buildSchool("ps4", "s4", "北京信息科技大学", "北京", 4, buildMajor("m4", "通信工程")),
                buildSchool("ps5", "s5", "北方工业大学", "北京", 5, buildMajor("m5", "电子信息工程"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CompensationPreviewDTO preview = planningStateService.runReview(1L, 1L).getCompensationPreview();
        assertTrue(preview.getTotalActions() > 0);
        assertTrue(preview.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getType())));
        assertTrue(preview.getActions().stream()
                .flatMap(action -> action.getVolunteerIds().stream())
                .anyMatch(volunteerId -> "ps4_m4".equals(volunteerId) || "ps5_m5".equals(volunteerId)));

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        assertTrue(proposalState.getProposals().stream()
                .anyMatch(proposal -> "fill_missing_count".equals(proposal.getStrategy())
                        && "ready".equals(proposal.getStatus())));
    }

    @Test
    void shouldAvoidRiskyCandidatesAndFillProbabilityGapDuringCompensation() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setTotalScore(590);
        response.setBaseData(new VolunteerRecommendListResponse.BaseData());
        response.getBaseData().setNeed_count(4);
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "北京航空航天大学", "北京", 1, buildMajorWithMeta("m1", "飞行器设计", "20", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps6", "s6", "国际学院", "北京", 6, buildMajorWithMeta("m6", "自动化（中外合作办学）", "30", "35000",
                        java.util.Collections.emptyList(), java.util.Arrays.asList("高校专项")))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "北京邮电大学", "北京", 2, buildMajorWithMeta("m2", "计算机科学与技术", "45", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps4", "s4", "北京信息科技大学", "北京", 4, buildMajorWithMeta("m4", "通信工程", "32", "9000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "河北工业大学", "河北", 3, buildMajorWithMeta("m3", "自动化", "70", "7000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps5", "s5", "天津理工大学", "天津", 5, buildMajorWithMeta("m5", "电子信息工程", "60", "7500",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CompensationPreviewDTO preview = planningStateService.runReview(1L, 1L).getCompensationPreview();
        assertTrue(preview.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getType())));
        assertFalse(preview.getActions().stream().flatMap(action -> action.getVolunteerIds().stream()).anyMatch("ps6_m6"::equals));
    }

    @Test
    void shouldApplyFillMissingCountFixProposalWithoutExceedingTarget() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setTotalScore(590);
        response.setBaseData(new VolunteerRecommendListResponse.BaseData());
        response.getBaseData().setNeed_count(4);
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "北京航空航天大学", "北京", 1, buildMajorWithMeta("m1", "飞行器设计", "20", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "北京邮电大学", "北京", 2, buildMajorWithMeta("m2", "计算机科学与技术", "45", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps4", "s4", "北京信息科技大学", "北京", 4, buildMajorWithMeta("m4", "通信工程", "32", "9000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "河北工业大学", "河北", 3, buildMajorWithMeta("m3", "自动化", "70", "7000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps5", "s5", "天津理工大学", "天津", 5, buildMajorWithMeta("m5", "电子信息工程", "60", "7500",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CompensationPreviewDTO preview = planningStateService.runReview(1L, 1L).getCompensationPreview();
        assertEquals("ready", preview.getStatus());
        assertTrue(preview.getTotalActions() > 0);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "fill_missing_count".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("ready", proposal.getStatus());

        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);
        FixProposalApplyRes res = planningStateService.applyFixProposal(1L, 1L, applyReq);
        PlanningStateDTO compensated = res.getState();

        assertEquals(Integer.valueOf(4), compensated.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(4), compensated.getOrderedPlanState().getSummary().getTotal());
    }

    @Test
    void shouldFillMissingCountByRequiredTierShortage() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setTotalScore(590);
        response.setBaseData(buildBaseData(4, 1, 1, 2));
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithMeta("m1", "专业A", "35", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "稳A", "北京", 2, buildMajorWithMeta("m2", "专业B", "50", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps5", "s5", "稳B", "北京", 3, buildMajorWithMeta("m5", "专业E", "52", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "保A", "北京", 8, buildMajorWithMeta("m3", "专业C", "75", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps4", "s4", "保B", "北京", 9, buildMajorWithMeta("m4", "专业D", "78", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CompensationPreviewDTO preview = planningStateService.runReview(1L, 1L).getCompensationPreview();
        CompensationActionDTO countAction = preview.getActions().stream()
                .filter(action -> "fill_total_count".equals(action.getType()))
                .findFirst()
                .orElse(null);

        assertNotNull(countAction);
        assertEquals(java.util.Arrays.asList("ps4_m4"), countAction.getVolunteerIds());
    }

    @Test
    void shouldNotApplyProtectRatioRebalanceAsAddOnlyWhenPlanIsFull() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setTotalScore(590);
        response.setBaseData(buildBaseData(4, 1, 2, 1));
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "冲A", "北京", 1, buildMajorWithMeta("m1", "专业A", "35", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps2", "s2", "冲B", "北京", 2, buildMajorWithMeta("m2", "专业B", "38", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "稳A", "北京", 3, buildMajorWithMeta("m3", "专业C", "50", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps4", "s4", "稳B", "北京", 4, buildMajorWithMeta("m4", "专业D", "55", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps5", "s5", "保A", "北京", 5, buildMajorWithMeta("m5", "专业E", "75", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "rebalance_tier_ratio".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getActions().stream()
                .anyMatch(action -> "rebalance_protect_ratio".equals(action.getActionType())));
        assertTrue(proposal.getActions().stream()
                .filter(action -> "replace_volunteers".equals(action.getActionType()))
                .flatMap(action -> action.getCandidateVolunteerIds().stream())
                .anyMatch("ps5_m5"::equals));
        assertPreviewOnlyFixProposalCannotApply(proposal);
    }

    @Test
    void shouldNotApplyProbabilityGapAsAddOnlyWhenPlanIsFull() {
        bindPlanningStateStore();

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setBaseData(buildBaseData(3, 1, 1, 1));
        response.setUserScoreDetail(buildScoreDetail());
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "学校A", "北京", 1, buildMajorWithRatio("m1", "专业A", "10"))));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "学校B", "北京", 1, buildMajorWithRatio("m2", "专业B", "50"))));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "学校C", "北京", 1, buildMajorWithRatio("m3", "专业C", "90")),
                buildSchool("ps4", "s4", "学校D", "北京", 2, buildMajorWithRatio("m4", "专业D", "92"))));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        FixProposalStateDTO proposalState = planningStateService.generateFixProposals(1L, 1L);
        FixProposalDTO proposal = proposalState.getProposals().stream()
                .filter(item -> "fill_probability_gap".equals(item.getStrategy()))
                .findFirst()
                .orElse(null);
        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getActions().stream()
                .anyMatch(action -> "fill_probability_gap".equals(action.getActionType())));
        assertTrue(proposal.getActions().stream()
                .filter(action -> "replace_volunteers".equals(action.getActionType()))
                .flatMap(action -> action.getCandidateVolunteerIds().stream())
                .anyMatch("ps2_m2"::equals));
        assertPreviewOnlyFixProposalCannotApply(proposal);
    }

    @Test
    void shouldReturnEmptyCompensationPreviewWhenPlanAlreadyExceedsTargetCount() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        response.setUserScoreDetail(new com.ytell.zhiyuan.model.dto.CreateSessionReq());
        response.getUserScoreDetail().setTotalScore(590);
        response.setBaseData(new VolunteerRecommendListResponse.BaseData());
        response.getBaseData().setNeed_count(3);
        response.setSprints(java.util.Arrays.asList(
                buildSchool("ps1", "s1", "北京航空航天大学", "北京", 1, buildMajorWithMeta("m1", "飞行器设计", "20", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setSafes(java.util.Arrays.asList(
                buildSchool("ps2", "s2", "北京邮电大学", "北京", 2, buildMajorWithMeta("m2", "计算机科学与技术", "45", "8000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps4", "s4", "北京信息科技大学", "北京", 4, buildMajorWithMeta("m4", "通信工程", "32", "9000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        response.setProtects(java.util.Arrays.asList(
                buildSchool("ps3", "s3", "河北工业大学", "河北", 3, buildMajorWithMeta("m3", "自动化", "70", "7000",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList())),
                buildSchool("ps5", "s5", "天津理工大学", "天津", 5, buildMajorWithMeta("m5", "电子信息工程", "60", "7500",
                        java.util.Collections.emptyList(), java.util.Collections.emptyList()))
        ));
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps2_m2", "ps3_m3", "ps4_m4"));
        planningStateService.selectDraftItems(1L, selectReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setRegroupByTier(true);
        generateReq.setForceRegenerate(true);
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CompensationPreviewDTO preview = planningStateService.runReview(1L, 1L).getCompensationPreview();
        assertEquals("empty", preview.getStatus());
        assertEquals(Integer.valueOf(0), preview.getTotalActions());
        assertTrue(preview.getActions().isEmpty());
    }

    private ChatSessionExtraData latestStoredStateFromSave() {
        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, times(1)).save(captor.capture());
        ChatSessionExtraData stored = new ChatSessionExtraData();
        stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        stored.setDataValue(captor.getValue().getDataValue());
        reset(chatSessionExtraDataSharedService);
        return stored;
    }

    private ChatSessionExtraData latestStoredStateFromUpdate() {
        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, times(1)).updateById(captor.capture());
        ChatSessionExtraData stored = new ChatSessionExtraData();
        stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        stored.setDataValue(captor.getValue().getDataValue());
        reset(chatSessionExtraDataSharedService);
        return stored;
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

    private VolunteerRecommendListResponse.VolunteerMajor buildMajor(String majorId, String majorName) {
        VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
        major.setMajorId(majorId);
        major.setPlanMajorDataId(majorId);
        major.setMajor_name(majorName);
        return major;
    }

    private VolunteerRecommendListResponse.VolunteerMajor buildMajorWithRatio(String majorId, String majorName, String enrollRatio) {
        VolunteerRecommendListResponse.VolunteerMajor major = buildMajor(majorId, majorName);
        major.setEnroll_ratio(enrollRatio);
        return major;
    }

    private VolunteerRecommendListResponse.VolunteerMajor buildMajorWithIntentScore(String majorId,
                                                                                    String majorName,
                                                                                    String enrollRatio,
                                                                                    Double intentScore) {
        VolunteerRecommendListResponse.VolunteerMajor major = buildMajorWithRatio(majorId, majorName, enrollRatio);
        java.util.Map<String, Object> algTagMap = new java.util.HashMap<String, Object>();
        algTagMap.put("major_score_new", intentScore);
        major.setAlgTagMap(algTagMap);
        return major;
    }

    private VolunteerRecommendListResponse.VolunteerMajor buildMajorWithPlan(String majorId,
                                                                             String planMajorDataId,
                                                                             String majorName,
                                                                             String enrollRatio) {
        VolunteerRecommendListResponse.VolunteerMajor major = buildMajorWithRatio(majorId, majorName, enrollRatio);
        major.setPlanMajorDataId(planMajorDataId);
        return major;
    }

    private VolunteerRecommendListResponse.VolunteerMajor buildMajorWithMeta(String majorId, String majorName, String enrollRatio,
                                                                             String planMoney, java.util.List<String> mustSubjects,
                                                                             java.util.List<String> planTags) {
        VolunteerRecommendListResponse.VolunteerMajor major = buildMajorWithRatio(majorId, majorName, enrollRatio);
        major.setPlanMoney(planMoney);
        major.setMust_subject(mustSubjects);
        major.setPlanTagList(planTags);
        return major;
    }

    private java.util.List<VolunteerRecommendListResponse.VolunteerSchool> buildFlatSchools(String prefix,
                                                                                            String provinceName,
                                                                                            int count,
                                                                                            int ratioStart,
                                                                                            int ratioSpan) {
        java.util.List<VolunteerRecommendListResponse.VolunteerSchool> schools = new java.util.ArrayList<VolunteerRecommendListResponse.VolunteerSchool>();
        for (int i = 1; i <= count; i++) {
            int ratio = ratioStart + (i % ratioSpan);
            schools.add(buildSchool(prefix + "ps" + i,
                    prefix + "school" + i,
                    prefix + "学校" + i,
                    provinceName,
                    i,
                    buildMajorWithRatio(prefix + "major" + i, prefix + "专业" + i, String.valueOf(ratio))));
        }
        return schools;
    }

    private java.util.List<VolunteerRecommendListResponse.VolunteerSchool> buildTaggedHighScoreSchools(String prefix,
                                                                                                        String provinceName,
                                                                                                        int count,
                                                                                                        String majorTag,
                                                                                                        double scoreBase,
                                                                                                        int ratioStart,
                                                                                                        int ratioSpan) {
        java.util.List<VolunteerRecommendListResponse.VolunteerSchool> schools = new java.util.ArrayList<VolunteerRecommendListResponse.VolunteerSchool>();
        for (int i = 1; i <= count; i++) {
            int ratio = ratioStart + (i % ratioSpan);
            VolunteerRecommendListResponse.VolunteerSchool school = buildSchool(prefix + "ps" + i,
                    prefix + "school" + i,
                    prefix + "学校" + i,
                    provinceName,
                    i,
                    buildMajorWithRatio(prefix + "major" + i, prefix + "专业" + i, String.valueOf(ratio)));
            java.util.Map<String, Object> algTagMap = new java.util.HashMap<String, Object>();
            algTagMap.put("volunteer_score", scoreBase - i);
            school.setAlgTagMap(algTagMap);
            school.getMajors().get(0).setRankTagList(java.util.Arrays.asList(majorTag));
            schools.add(school);
        }
        return schools;
    }

    private java.util.List<VolunteerRecommendListResponse.VolunteerSchool> buildGroupSchools(String prefix,
                                                                                              String provinceName,
                                                                                              int count,
                                                                                              int schoolRatioBase,
                                                                                              double safetyDelta) {
        java.util.List<VolunteerRecommendListResponse.VolunteerSchool> schools = new java.util.ArrayList<VolunteerRecommendListResponse.VolunteerSchool>();
        for (int i = 1; i <= count; i++) {
            double schoolRatio = schoolRatioBase + (i % 8);
            VolunteerRecommendListResponse.VolunteerSchool school = buildSchool(prefix + "ps" + i,
                    prefix + "school" + i,
                    prefix + "学校" + i,
                    provinceName,
                    i,
                    buildMajorWithRatio(prefix + "major" + i + "a",
                            prefix + "专业" + i + "_1",
                            String.valueOf((int) Math.round(schoolRatio + safetyDelta))));
            school.setEnroll_ratio(String.valueOf((int) Math.round(schoolRatio)));
            school.setMajors(java.util.Arrays.asList(
                    buildMajorWithRatio(prefix + "major" + i + "a",
                            prefix + "专业" + i + "_1",
                            String.valueOf((int) Math.round(schoolRatio + safetyDelta))),
                    buildMajorWithRatio(prefix + "major" + i + "b",
                            prefix + "专业" + i + "_2",
                            String.valueOf((int) Math.round(schoolRatio + Math.max(2D, safetyDelta / 2D)))),
                    buildMajorWithRatio(prefix + "major" + i + "c",
                            prefix + "专业" + i + "_3",
                            String.valueOf((int) Math.round(schoolRatio - 3D)))
            ));
            schools.add(school);
        }
        return schools;
    }

    private void assertTierSelectionHighScoreFirst(PlanningStateDTO state,
                                                   String tier,
                                                   int minSelected,
                                                   int maxWorstRank) {
        java.util.List<String> selectedIds = state.getInitialRecommendationState().getItems().stream()
                .filter(item -> tier.equals(item.getRecommendTier()))
                .map(item -> item.getVolunteerId())
                .collect(Collectors.toList());
        assertTrue(selectedIds.size() >= minSelected);

        java.util.List<String> rankedIds = state.getCandidatePoolState().getItems().stream()
                .filter(item -> tier.equals(item.getTier()))
                .sorted(Comparator.comparing((CandidateItemDTO item) -> item.getFinalScore() == null ? 0D : item.getFinalScore()).reversed())
                .map(CandidateItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        java.util.List<Integer> selectedRanks = selectedIds.stream()
                .map(id -> rankedIds.indexOf(id) + 1)
                .filter(rank -> rank > 0)
                .collect(Collectors.toList());
        assertTrue(selectedRanks.size() >= minSelected);
        int worstRank = selectedRanks.stream().max(Integer::compareTo).orElse(Integer.MAX_VALUE);
        assertTrue(worstRank <= maxWorstRank);
    }

    private void assertTierSelectionDominatedByTaggedHeadCandidates(PlanningStateDTO state,
                                                                    String tier,
                                                                    String expectedTag,
                                                                    double minRatio) {
        java.util.Map<String, CandidateItemDTO> candidateMap = state.getCandidatePoolState().getItems().stream()
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, item -> item));
        java.util.List<CandidateItemDTO> selected = state.getInitialRecommendationState().getItems().stream()
                .filter(item -> tier.equals(item.getRecommendTier()))
                .map(item -> candidateMap.get(item.getVolunteerId()))
                .collect(Collectors.toList());
        assertFalse(selected.isEmpty());
        long matched = selected.stream().filter(item -> item != null
                && item.getMajorRankTags() != null
                && item.getMajorRankTags().contains(expectedTag)).count();
        assertTrue(((double) matched / (double) selected.size()) >= minRatio);
    }

    private void assertMajorGroupRepresentativeSelectionWithinTopRanks(PlanningStateDTO state,
                                                                       String tier,
                                                                       int expectedSelectedUnits,
                                                                       int topN) {
        Map<String, CandidateItemDTO> bestByUnit = state.getCandidatePoolState().getItems().stream()
                .filter(item -> tier.equals(item.getTier()))
                .collect(Collectors.toMap(
                        CandidateItemDTO::getPlanSchoolDataId,
                        item -> item,
                        (left, right) -> compareByFinalScoreDesc(left, right) <= 0 ? left : right));

        Set<String> selectedUnits = new HashSet<String>();
        for (com.ytell.zhiyuan.model.dto.planning.InitialRecommendationItemDTO item : state.getInitialRecommendationState().getItems()) {
            if (!tier.equals(item.getRecommendTier())) {
                continue;
            }
            String unitId = resolveUnitIdFromVolunteerId(item.getVolunteerId());
            if (unitId != null) {
                selectedUnits.add(unitId);
            }
        }
        assertEquals(expectedSelectedUnits, selectedUnits.size());

        Set<String> topUnits = bestByUnit.values().stream()
                .sorted(this::compareByFinalScoreDesc)
                .limit(topN)
                .map(CandidateItemDTO::getPlanSchoolDataId)
                .collect(Collectors.toSet());
        assertTrue(topUnits.containsAll(selectedUnits));
    }

    private int compareByFinalScoreDesc(CandidateItemDTO left, CandidateItemDTO right) {
        double leftScore = left == null || left.getFinalScore() == null ? 0D : left.getFinalScore();
        double rightScore = right == null || right.getFinalScore() == null ? 0D : right.getFinalScore();
        return Double.compare(rightScore, leftScore);
    }

    private void prepareCountFixProposalState() {
        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        DraftSelectReq selectReq = new DraftSelectReq();
        selectReq.setVolunteerIds(java.util.Arrays.asList("ps1_m1", "ps1_m2", "ps2_m3", "ps2_m4", "ps3_m5", "ps3_m6"));
        planningStateService.selectDraftItems(1L, selectReq);
        planningStateService.generateOrderedPlan(1L, 1L, new OrderedPlanGenerateReq());
        planningStateService.runReview(1L, 1L);
    }

    private void assertPreviewOnlyFixProposalCannotApply(FixProposalDTO proposal) {
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());

        BusinessException ex = assertThrows(BusinessException.class,
                () -> planningStateService.applyFixProposal(1L, 1L, applyReq));
        assertEquals(400, ex.getStatus());
        assertTrue(ex.getMessage().contains("暂不支持自动应用")
                || ex.getMessage().contains("不可应用"));
    }

    private FixProposalApplyReq userGoalApplyReq(FixProposalDTO proposal, UserGoalFixProposalReq userGoalRequest) {
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId(proposal.getProposalId());
        applyReq.setProposalSource("user_goal");
        applyReq.setSourceVersionGuard(proposal.getSourceVersionGuard());
        applyReq.setUserGoalRequest(userGoalRequest);
        return applyReq;
    }

    private UserGoalFixProposalReq userGoalReq(String goalType,
                                               Integer sourceVersionGuard,
                                               UserGoalFixProposalReq.ScopeDTO scope,
                                               boolean negativeScope) {
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType(goalType);
        req.setSourceVersionGuard(sourceVersionGuard);
        if (negativeScope) {
            req.getNegativeScopes().add(scope);
        } else {
            req.getTargetScopes().add(scope);
        }
        return req;
    }

    private UserGoalFixProposalReq.ScopeDTO userGoalScope(String entityType, String normalizedName) {
        UserGoalFixProposalReq.ScopeDTO scope = new UserGoalFixProposalReq.ScopeDTO();
        scope.setEntityType(entityType);
        scope.setNormalizedName(normalizedName);
        return scope;
    }

    private ReviewStateDTO buildFailedReviewState(String code,
                                                  String summary,
                                                  String scopeKind,
                                                  String category) {
        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt("2026-06-08T12:00:00+08:00");
        reviewState.setSourceVersion(3);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode(code);
        check.setLevel("warn");
        check.setPassed(false);
        check.setSummary(summary);
        check.setScopeKind(scopeKind);
        check.setCategory(category);
        reviewState.setChecks(java.util.Arrays.asList(check));
        return reviewState;
    }

    private PlanningStateDTO buildMajorGroupRiskFixState(boolean onlyRiskMajorInAffectedUnit) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        state.setVersion(3);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(VolunteerModel.majorGroup.name());
        candidatePoolState.setRequiredCount(2);

        CandidateItemDTO riskCandidate = buildCandidateItem("ps1_m1", "ps1", "s1", "学校A第101组", "冲", "专业A1", 35D, 92D, 35D, false);
        riskCandidate.getMustSubjects().add("色盲限报");
        candidatePoolState.getItems().add(riskCandidate);
        if (!onlyRiskMajorInAffectedUnit) {
            candidatePoolState.getItems().add(buildCandidateItem("ps1_m2", "ps1", "s1", "学校A第101组", "冲", "专业A2", 42D, 88D, 35D, false));
        }
        candidatePoolState.getItems().add(buildCandidateItem("ps2_m3", "ps2", "s2", "学校B第102组", "稳", "专业B1", 55D, 86D, 55D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps2_m4", "ps2", "s2", "学校B第102组", "稳", "专业B2", 58D, 82D, 55D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps3_m5", "ps3", "s3", "学校C第103组", "保", "专业C1", 75D, 78D, 75D, false));
        candidatePoolState.getItems().add(buildCandidateItem("ps3_m6", "ps3", "s3", "学校C第103组", "保", "专业C2", 78D, 74D, 75D, false));
        state.setCandidatePoolState(candidatePoolState);

        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(buildDraftItem("ps1_m1", "学校A第101组", "专业A1", "冲"));
        if (!onlyRiskMajorInAffectedUnit) {
            draft.getItems().add(buildDraftItem("ps1_m2", "学校A第101组", "专业A2", "冲"));
        }
        draft.getItems().add(buildDraftItem("ps2_m3", "学校B第102组", "专业B1", "稳"));
        draft.getItems().add(buildDraftItem("ps2_m4", "学校B第102组", "专业B2", "稳"));
        ReflectionTestUtils.invokeMethod(planningStateService, "syncWorkingPlanUnitsWithItems", draft, candidatePoolState.getItems(), candidatePoolState);
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateWorkingPlanSummary", draft, candidatePoolState);
        state.setDraftPlanState(draft);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.getItems().add(buildOrderedItem("ps1_m1", "学校A第101组", "专业A1", "冲", 1));
        if (!onlyRiskMajorInAffectedUnit) {
            orderedPlanState.getItems().add(buildOrderedItem("ps1_m2", "学校A第101组", "专业A2", "冲", 2));
            orderedPlanState.getItems().add(buildOrderedItem("ps2_m3", "学校B第102组", "专业B1", "稳", 3));
            orderedPlanState.getItems().add(buildOrderedItem("ps2_m4", "学校B第102组", "专业B2", "稳", 4));
        } else {
            orderedPlanState.getItems().add(buildOrderedItem("ps2_m3", "学校B第102组", "专业B1", "稳", 2));
            orderedPlanState.getItems().add(buildOrderedItem("ps2_m4", "学校B第102组", "专业B2", "稳", 3));
        }
        orderedPlanState.setUnits(ReflectionTestUtils.invokeMethod(planningStateService,
                "buildOrderedUnitsFromOrderedItems", orderedPlanState.getItems(), draft, candidatePoolState.getItems()));
        ReflectionTestUtils.invokeMethod(planningStateService, "recalculateOrderedSummary", orderedPlanState, candidatePoolState);
        state.setOrderedPlanState(orderedPlanState);
        return state;
    }

    private VolunteerRecommendListResponse buildCountFixProposalResponse() {
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = buildBaseData(4, 1, 2, 1);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(4);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);
        response.setUserScoreDetail(buildScoreDetail());

        VolunteerRecommendListResponse.VolunteerSchool sprintGroup = buildSchool("ps1", "s1", "专业组A", "北京", 1,
                buildMajorWithRatio("m1", "专业A1", "20"));
        sprintGroup.setEnroll_ratio("20");
        sprintGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A1", "20"),
                buildMajorWithRatio("m2", "专业A2", "24")
        ));

        VolunteerRecommendListResponse.VolunteerSchool gapFillerGroup = buildSchool("ps4", "s4", "专业组D", "北京", 2,
                buildMajorWithRatio("m7", "专业D1", "50"));
        gapFillerGroup.setEnroll_ratio("50");
        gapFillerGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m7", "专业D1", "50"),
                buildMajorWithRatio("m8", "专业D2", "48")
        ));

        VolunteerRecommendListResponse.VolunteerSchool safeGroup = buildSchool("ps2", "s2", "专业组B", "北京", 1,
                buildMajorWithRatio("m3", "专业B1", "78"));
        safeGroup.setEnroll_ratio("78");
        safeGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m3", "专业B1", "78"),
                buildMajorWithRatio("m4", "专业B2", "74")
        ));

        VolunteerRecommendListResponse.VolunteerSchool protectGroup = buildSchool("ps3", "s3", "专业组C", "河南", 1,
                buildMajorWithRatio("m5", "专业C1", "86"));
        protectGroup.setEnroll_ratio("86");
        protectGroup.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m5", "专业C1", "86"),
                buildMajorWithRatio("m6", "专业C2", "82")
        ));

        response.setSprints(java.util.Arrays.asList(sprintGroup));
        response.setSafes(java.util.Arrays.asList(gapFillerGroup, safeGroup));
        response.setProtects(java.util.Arrays.asList(protectGroup));
        return response;
    }

    private String resolveUnitIdFromVolunteerId(String volunteerId) {
        if (volunteerId == null) {
            return null;
        }
        int index = volunteerId.indexOf('_');
        if (index > 0) {
            return volunteerId.substring(0, index);
        }
        return volunteerId;
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

    private void addCandidateUnits(CandidatePoolStateDTO candidatePoolState, String tier, String prefix, int count) {
        for (int i = 0; i < count; i++) {
            CandidateItemDTO item = new CandidateItemDTO();
            item.setVolunteerId(prefix + "-" + i + "_m1");
            item.setPlanSchoolDataId(prefix + "-" + i);
            item.setSchoolName(prefix + "-" + i);
            item.setTier(tier);
            candidatePoolState.getItems().add(item);
        }
    }

    private AtomicReference<ChatSessionExtraData> bindPlanningStateStore() {
        return bindPlanningStateStore(1L);
    }

    private AtomicReference<ChatSessionExtraData> bindPlanningStateStore(Long chatSessionId) {
        AtomicReference<ChatSessionExtraData> planningStateRef = new AtomicReference<ChatSessionExtraData>();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(chatSessionId), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenAnswer(invocation -> planningStateRef.get());
        doAnswer(invocation -> {
            ChatSessionExtraData data = invocation.getArgument(0);
            ChatSessionExtraData stored = new ChatSessionExtraData();
            stored.setChatSessionId(data.getChatSessionId());
            stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            stored.setDataValue(data.getDataValue());
            planningStateRef.set(stored);
            return true;
        }).when(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        doAnswer(invocation -> {
            ChatSessionExtraData data = invocation.getArgument(0);
            ChatSessionExtraData stored = new ChatSessionExtraData();
            stored.setChatSessionId(data.getChatSessionId());
            stored.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            stored.setDataValue(data.getDataValue());
            planningStateRef.set(stored);
            return true;
        }).when(chatSessionExtraDataSharedService).updateById(any(ChatSessionExtraData.class));
        return planningStateRef;
    }

    private void saveStateToStore(Long chatSessionId, PlanningStateDTO state) {
        saveRawStateToStore(chatSessionId, com.alibaba.fastjson.JSONObject.toJSONString(state));
    }

    private void saveRawStateToStore(Long chatSessionId, String stateJson) {
        ChatSessionExtraData data = new ChatSessionExtraData();
        data.setChatSessionId(chatSessionId);
        data.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        data.setDataValue(stateJson);
        chatSessionExtraDataSharedService.save(data);
    }

    private VolunteerRecommendListResponse buildLatestVolunteerResponse(String schoolId,
                                                                          String majorId,
                                                                          String majorName,
                                                                          Integer planNum) {
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = new VolunteerRecommendListResponse.BaseData();
        baseData.setNeed_count(1);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(1);
        volunteerCount.setMajorCount(1);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.major);
        response.setBaseData(baseData);

        VolunteerRecommendListResponse.VolunteerSchool school = new VolunteerRecommendListResponse.VolunteerSchool();
        school.setPlanSchoolDataId(schoolId);
        school.setSchoolId(schoolId);
        school.setSchool_name("学校A");
        school.setRank_in_tier(1);
        school.setEnroll_ratio("80%");
        VolunteerRecommendListResponse.VolunteerMajor major = new VolunteerRecommendListResponse.VolunteerMajor();
        major.setPlanMajorDataId(majorId);
        major.setMajorId(majorId);
        major.setMajor_name(majorName);
        major.setPlanNum(planNum);
        major.setEnroll_ratio("80%");
        school.setMajors(java.util.Arrays.asList(major));
        response.setSafes(java.util.Arrays.asList(school));
        return response;
    }

    private VolunteerRecommendListResponse buildMajorGroupFreshnessResponse() {
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.BaseData baseData = new VolunteerRecommendListResponse.BaseData();
        baseData.setNeed_count(2);
        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(2);
        volunteerCount.setMajorCount(2);
        baseData.setVolunteerCount(volunteerCount);
        baseData.setVolunteerModel(VolunteerModel.majorGroup);
        response.setBaseData(baseData);

        VolunteerRecommendListResponse.VolunteerSchool police = buildSchool(
                "police", "police-school", "海南警察学院（不限）", "海南", 1,
                buildMajorWithRatio("law", "法学（改）", "75"));
        VolunteerRecommendListResponse.VolunteerSchool luosang = buildSchool(
                "luosang", "luosang-school", "海南洛桑旅游大学（不限）", "海南", 2,
                buildMajorWithRatio("tourism", "旅游管理", "78"));
        response.setProtects(java.util.Arrays.asList(police, luosang));
        return response;
    }

    private boolean staleCandidatePool(StaleFlagsDTO flags) {
        return Boolean.TRUE.equals(flags.getCandidatePool());
    }

    private boolean staleRecommendationOverlay(StaleFlagsDTO flags) {
        return Boolean.TRUE.equals(flags.getRecommendationOverlay());
    }

    private boolean staleInitialRecommendation(StaleFlagsDTO flags) {
        return Boolean.TRUE.equals(flags.getInitialRecommendation());
    }

    private boolean staleOrderedPlan(StaleFlagsDTO flags) {
        return Boolean.TRUE.equals(flags.getOrderedPlan());
    }

    private boolean stalePlanAdjustment(StaleFlagsDTO flags) {
        return Boolean.TRUE.equals(flags.getPlanAdjustment());
    }

    private boolean staleReview(StaleFlagsDTO flags) {
        return Boolean.TRUE.equals(flags.getReview());
    }

    private UserProfileData buildUserProfileData() {
        UserProfileData userProfileData = new UserProfileData();
        userProfileData.getCollege_info().setValues(java.util.Arrays.asList("清华大学"));
        userProfileData.getNegative_city_info().setProvince(java.util.Arrays.asList("河北"));
        return userProfileData;
    }

    private OrderedItemDTO buildOrderedItem(String volunteerId,
                                            String schoolName,
                                            String majorName,
                                            String tier,
                                            Integer position) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setSchoolName(schoolName);
        item.setMajorName(majorName);
        item.setTier(tier);
        item.setPosition(position);
        item.setSource("test");
        return item;
    }

    private DraftItemDTO buildDraftItem(String volunteerId,
                                        String schoolName,
                                        String majorName,
                                        String tier) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        item.setSchoolName(schoolName);
        item.setMajorName(majorName);
        item.setTier(tier);
        item.setSource("test");
        return item;
    }

    private CandidateItemDTO buildCandidateItem(String volunteerId,
                                                String planSchoolDataId,
                                                String schoolId,
                                                String schoolName,
                                                String tier,
                                                String majorName,
                                                Double admissionRatio,
                                                Double finalScore,
                                                Double schoolEnrollRatio,
                                                boolean preferred) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId(volunteerId);
        item.setPlanSchoolDataId(planSchoolDataId);
        item.setSchoolId(schoolId);
        item.setSchoolName(schoolName);
        item.setTier(tier);
        item.setMajorName(majorName);
        item.setAdmissionRatio(admissionRatio);
        item.setFinalScore(finalScore);
        item.setIntentScore(finalScore);
        item.setSchoolEnrollRatio(schoolEnrollRatio);
        item.setPreferred(preferred);
        item.setRankInTier(1);
        return item;
    }

    private PlanningBehaviorEventDTO buildBehaviorEvent(String eventId,
                                                        int planVersion,
                                                        String createdAt) {
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(eventId);
        event.setEventType("plan_export");
        event.setPlanVersion(planVersion);
        event.setCreatedAt(createdAt);
        event.setPositiveFeedback(true);
        return event;
    }

    private PlanningUnitDTO buildPlanningUnitDto(String unitId, String tier) {
        PlanningUnitDTO unit = new PlanningUnitDTO();
        unit.setUnitId(unitId);
        unit.setTier(tier);
        return unit;
    }

    private void assertLegacySubmittedImportMatchesSource(Long sessionId,
                                                          VolunteerRecommendListResponse legacy,
                                                          boolean exactSelectedCount) {
        assertLegacyImportMatchesSource(sessionId, legacy, true, exactSelectedCount);
    }

    private void assertLegacyImportMatchesSource(Long sessionId,
                                                 VolunteerRecommendListResponse legacy,
                                                 boolean exactSelectedCount) {
        assertLegacyImportMatchesSource(sessionId, legacy, false, exactSelectedCount);
    }

    private void assertLegacyImportMatchesSource(Long sessionId,
                                                 VolunteerRecommendListResponse legacy,
                                                 boolean submitted,
                                                 boolean exactSelectedCount) {
        setUp();
        bindPlanningStateStore(sessionId);
        int expectedCandidateCount = countLegacyRecommendEntries(legacy);
        int expectedSelectedCount = countLegacyPreferredEntries(legacy);
        if (expectedSelectedCount == 0) {
            expectedSelectedCount = countLegacyTargetSelectedEntries(legacy);
        }

        if (submitted) {
            when(volunteerBizService.loadFinalSubmitVolunteerData(sessionId)).thenReturn(legacy);
        } else {
            when(volunteerBizService.loadFinalSubmitVolunteerData(sessionId)).thenThrow(new RuntimeException("missing final"));
            when(volunteerBizService.loadCachedRecommendData(sessionId)).thenReturn(legacy);
        }

        PlanningStateDTO state = planningStateService.getPlanningState(sessionId);

        assertEquals(sessionId, state.getSessionId());
        assertEquals(expectedCandidateCount, state.getCandidatePoolState().getItems().size());
        if (exactSelectedCount) {
            assertEquals(expectedSelectedCount, state.getDraftPlanState().getItems().size());
            assertEquals(expectedSelectedCount, state.getOrderedPlanState().getItems().size());
        } else {
            assertTrue(state.getDraftPlanState().getItems().size() > 0);
            assertEquals(state.getDraftPlanState().getItems().size(), state.getOrderedPlanState().getItems().size());
            assertTrue(state.getDraftPlanState().getItems().size() <= expectedCandidateCount);
        }
        assertEquals(submitted ? "legacy_submitted" : "legacy_import", state.getOrderedPlanState().getGenerationMode());
        if (submitted) {
            assertTrue(state.getOrderedPlanState().getItems().stream().allMatch(item -> Boolean.TRUE.equals(item.getLocked())));
            assertTrue(state.getOrderedPlanState().getItems().stream().allMatch(item -> Boolean.TRUE.equals(item.getPinned())));
        } else {
            assertTrue(state.getOrderedPlanState().getItems().stream().noneMatch(item -> Boolean.TRUE.equals(item.getLocked())));
            assertTrue(state.getOrderedPlanState().getItems().stream().noneMatch(item -> Boolean.TRUE.equals(item.getPinned())));
        }
        assertTrue(state.getOperationLogs().stream().anyMatch(log -> "legacy_plan_import".equals(log.getType())));
        verify(chatSessionExtraDataSharedService, times(1)).save(any(ChatSessionExtraData.class));
    }

    private void assertLegacyOriginalImportMatchesSource(Long sessionId,
                                                         VolunteerRecommendListResponse legacy) {
        setUp();
        bindPlanningStateStore(sessionId);
        int expectedCandidateCount = countLegacyRecommendEntries(legacy);

        when(volunteerBizService.loadFinalSubmitVolunteerData(sessionId)).thenThrow(new RuntimeException("missing final"));
        when(volunteerBizService.loadCachedRecommendData(sessionId)).thenThrow(new RuntimeException("missing temp"));
        when(volunteerBizService.loadOriginalVolunteerData(sessionId)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(sessionId);

        assertEquals(sessionId, state.getSessionId());
        assertEquals(expectedCandidateCount, state.getCandidatePoolState().getItems().size());
        assertEquals(0, state.getDraftPlanState().getItems().size());
        assertEquals(0, state.getOrderedPlanState().getItems().size());
        assertEquals("candidate_generated", state.getPhase());
        assertEquals("legacy_import", state.getOrderedPlanState().getGenerationMode());
        assertTrue(state.getOperationLogs().stream().anyMatch(log -> "legacy_plan_import".equals(log.getType())));
        verify(chatSessionExtraDataSharedService, times(1)).save(any(ChatSessionExtraData.class));
    }

    private Long extractSessionId(Path sampleFile) {
        String fileName = sampleFile.getFileName().toString();
        String id = fileName.replaceFirst("^session_volunteer_", "")
                .replaceFirst("(_final|_temp)?\\.json$", "");
        return Long.valueOf(id);
    }

    private int countLegacyRecommendEntries(VolunteerRecommendListResponse response) {
        return countLegacyRecommendEntries(response.getSprints())
                + countLegacyRecommendEntries(response.getSafes())
                + countLegacyRecommendEntries(response.getProtects());
    }

    private int countLegacyRecommendEntries(List<VolunteerRecommendListResponse.VolunteerSchool> schools) {
        if (schools == null) {
            return 0;
        }
        int count = 0;
        for (VolunteerRecommendListResponse.VolunteerSchool school : schools) {
            if (school.getMajors() == null || school.getMajors().isEmpty()) {
                count++;
            } else {
                count += school.getMajors().size();
            }
        }
        return count;
    }

    private int countLegacyPreferredEntries(VolunteerRecommendListResponse response) {
        return countLegacyPreferredEntries(response.getSprints())
                + countLegacyPreferredEntries(response.getSafes())
                + countLegacyPreferredEntries(response.getProtects());
    }

    private int countLegacyPreferredEntries(List<VolunteerRecommendListResponse.VolunteerSchool> schools) {
        if (schools == null) {
            return 0;
        }
        int count = 0;
        for (VolunteerRecommendListResponse.VolunteerSchool school : schools) {
            if (!Boolean.TRUE.equals(school.getIs_preferred())) {
                continue;
            }
            if (school.getMajors() == null || school.getMajors().isEmpty()) {
                count++;
            } else {
                count += school.getMajors().size();
            }
        }
        return count;
    }

    private int countLegacyTargetSelectedEntries(VolunteerRecommendListResponse response) {
        if (response == null || response.getBaseData() == null || response.getBaseData().getThree_target_count_map() == null) {
            return 0;
        }
        Map<String, Integer> counts = response.getBaseData().getThree_target_count_map();
        return Math.min(defaultInt(counts.get("sprints_count")), countLegacyRecommendEntries(response.getSprints()))
                + Math.min(defaultInt(counts.get("safes_count")), countLegacyRecommendEntries(response.getSafes()))
                + Math.min(defaultInt(counts.get("protects_count")), countLegacyRecommendEntries(response.getProtects()));
    }

    private int defaultInt(Integer value) {
        return value == null ? 0 : value;
    }
}
