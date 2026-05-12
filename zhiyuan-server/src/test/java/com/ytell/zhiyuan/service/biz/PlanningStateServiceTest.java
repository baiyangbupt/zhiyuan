package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.manager.MajorExtraDataManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateFilterOptionsDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryReq;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateViewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationApplyReq;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationPreviewDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintDeriveRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanReorderReq;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftLockReq;
import com.ytell.zhiyuan.model.dto.planning.DraftRemoveReq;
import com.ytell.zhiyuan.model.dto.planning.DraftSelectReq;
import com.ytell.zhiyuan.model.dto.planning.InitialPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedMoveReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPinReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanAdjustmentAnalyzeReq;
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
import com.ytell.zhiyuan.model.dto.planning.UpdateLatentProfileReq;
import com.ytell.zhiyuan.model.dto.planning.InitialRecommendationGenerateReq;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
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
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
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
    private VolunteerBizService volunteerBizService;

    @BeforeEach
    void setUp() {
        planningStateService = new PlanningStateService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        volunteerBizService = Mockito.mock(VolunteerBizService.class);
        MajorExtraDataManager majorExtraDataManager = new MajorExtraDataManager();
        majorExtraDataManager.init();
        ReflectionTestUtils.setField(planningStateService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(planningStateService, "volunteerBizService", volunteerBizService);
        ReflectionTestUtils.setField(planningStateService, "volunteerIntervalService", new VolunteerIntervalService());
        ReflectionTestUtils.setField(planningStateService, "majorExtraDataManager", majorExtraDataManager);
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
        sprint.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m1", "专业A", "18"),
                buildMajorWithRatio("m2", "专业B", "22"),
                buildMajorWithRatio("m3", "专业C", "25")));
        sprint.setIs_preferred(true);
        VolunteerRecommendListResponse.VolunteerSchool safe = buildSchool(
                "ps2", "s2", "学校B第01组", "天津", 1,
                buildMajorWithRatio("m4", "专业D", "52"));
        safe.setMajors(java.util.Arrays.asList(
                buildMajorWithRatio("m4", "专业D", "52"),
                buildMajorWithRatio("m5", "专业E", "58")));
        safe.setIs_preferred(true);
        legacy.setSprints(java.util.Arrays.asList(sprint));
        legacy.setSafes(java.util.Arrays.asList(safe));

        when(volunteerBizService.loadFinalSubmitVolunteerData(1L)).thenThrow(new RuntimeException("missing final"));
        when(volunteerBizService.loadCachedRecommendData(1L)).thenReturn(legacy);

        PlanningStateDTO state = planningStateService.getPlanningState(1L);

        assertEquals("majorGroup", state.getCandidatePoolState().getVolunteerModel());
        assertEquals(5, state.getOrderedPlanState().getItems().size());
        assertEquals(2, state.getOrderedPlanState().getSummary().getTotal());
        assertEquals(1, state.getOrderedPlanState().getSummary().getTierCounts().get("冲"));
        assertEquals(1, state.getOrderedPlanState().getSummary().getTierCounts().get("稳"));
        assertEquals(2, state.getOrderedPlanState().getUnits().size());
        assertTrue(state.getOrderedPlanState().getUnits().stream()
                .allMatch(unit -> unit.getMajorItems() != null && !unit.getMajorItems().isEmpty()));
        assertEquals("legacy_import", state.getOrderedPlanState().getGenerationMode());
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
        assertEquals("专业A1", unit.getSelectedMajors().get(0).getMajorName());
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
    void shouldPopulateDraftSummaryTargetCountsFromCandidatePoolRequiredCount() {
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
                "recalculateDraftSummary",
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
    void shouldExposeWorkflowStatusForEmptyCandidatePool() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(1L);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setGeneratedAt("2026-05-12T10:00:00+08:00");
        candidatePoolState.setStatusCode("empty");
        candidatePoolState.setStatusMessage("当前条件下没有可用志愿候选");
        state.setCandidatePoolState(candidatePoolState);

        PlanningWorkspaceStateRes workspaceState = planningStateService.buildPlanningWorkspaceStateRes(state);

        assertEquals("empty", workspaceState.getWorkflowStatus().getCandidateStatus());
        assertEquals("当前条件下没有可用志愿候选", workspaceState.getWorkflowStatus().getCandidateMessage());
        assertEquals("empty", workspaceState.getWorkflowStatus().getPlanStatus());
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
        assertFalse(ruleHits.containsKey("group_inner_safety_guard"));
        assertFalse(reviewState.getCompensationPreview().getActions().stream()
                .anyMatch(action -> "count_validation".equals(action.getSourceCheckCode())));
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

        CompensationPreviewDTO preview = planningStateService.previewCompensation(1L, 1L);

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
        assertEquals(java.util.Arrays.asList("ps1", "ps2"), probabilityGapCheck.getAffectedUnitIds());
        assertTrue(probabilityGapCheck.getAffectedVolunteerIds().contains("ps1_m1"));
        assertTrue(probabilityGapCheck.getAffectedVolunteerIds().contains("ps2_m3"));
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
        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
        VolunteerRecommendListResponse.VolunteerSchool school = buildSchool("ps1", "s1", "北京邮电大学", "北京", 1, major);
        school.setSchool_batch("本科");
        school.setSchool_level("211");
        school.setSchool_nature("公办");
        school.setSchool_category("理工");
        school.setBasicTagList(java.util.Arrays.asList("公办", "理工", "北京", "华东"));
        school.setRankTagList(java.util.Arrays.asList("双一流", "保研率 18%"));
        school.setPopTagList(java.util.Arrays.asList("低学费", "院校排名 12", "北京市"));
        school.getMajors().get(0).setRankTagList(java.util.Arrays.asList("计算机", "就业率 91%"));
        school.getMajors().get(0).setPlanTagList(java.util.Arrays.asList("选科要求", "计划数:6"));
        response.setSafes(java.util.Arrays.asList(school));
        response.setSprints(java.util.Collections.emptyList());
        response.setProtects(java.util.Collections.emptyList());
        when(volunteerBizService.recommendVolunteerList(1L, 1L, false, false)).thenReturn(response);

        planningStateService.generateCandidatePool(1L, 1L, new CandidatePoolGenerateReq());
        ChatSessionExtraData stored = latestStoredStateFromSave();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CandidateFilterOptionsDTO res = planningStateService.getCandidateFilterOptions(1L, 1L);

        assertTrue(res.getProvinceNames().contains("北京"));
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
        assertTrue(res.getGroups().stream().anyMatch(group ->
                "major.category".equals(group.getGroupCode())
                        && "majorKeywords".equals(group.getFilterField())
                        && group.getValues().contains("计算机类")));
        assertFalse(res.getMajorTags().contains("就业率 91%"));
        assertFalse(res.getMajorTags().contains("计划数:6"));
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
        assertEquals(Integer.valueOf(1), removed.getDraftPlanState().getSummary().getTotal());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        lockReq.setLocked(false);
        PlanningStateDTO unlocked = planningStateService.lockDraftItems(1L, lockReq);
        assertFalse(Boolean.TRUE.equals(unlocked.getDraftPlanState().getItems().get(0).getLocked()));

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        PlanningStateDTO removedAfterUnlock = planningStateService.removeDraftItems(1L, removeReq);
        assertEquals(Integer.valueOf(0), removedAfterUnlock.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(0), removedAfterUnlock.getOrderedPlanState().getSummary().getTotal());
    }

    @Test
    void shouldGenerateMoveAndPinOrderedPlan() {
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(null);

        VolunteerRecommendListResponse response = new VolunteerRecommendListResponse();
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

        OrderedPinReq pinReq = new OrderedPinReq();
        pinReq.setVolunteerId("ps3_m3");
        pinReq.setTargetPosition(1);
        PlanningStateDTO pinned = planningStateService.pinOrderedItem(1L, pinReq);
        assertEquals("ps3_m3", pinned.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertTrue(pinned.getOrderedPlanState().getItems().get(0).getPinned());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        OrderedMoveReq moveReq = new OrderedMoveReq();
        moveReq.setVolunteerId("ps1_m1");
        moveReq.setTargetPosition(3);
        PlanningStateDTO moved = planningStateService.moveOrderedItem(1L, moveReq);
        assertEquals("ps3_m3", moved.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m2", moved.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps1_m1", moved.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertEquals("user", moved.getOrderedPlanState().getItems().get(2).getOrderedBy());

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        PlanningStateDTO unpinned = planningStateService.unpinOrderedItem(1L, pinReq);
        assertFalse(unpinned.getOrderedPlanState().getItems().stream()
                .anyMatch(item -> "ps3_m3".equals(item.getVolunteerId()) && Boolean.TRUE.equals(item.getPinned())));
    }

    @Test
    void shouldAllowMoveAndPinLockedOrderedItems() {
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

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedPinReq pinReq = new OrderedPinReq();
        pinReq.setVolunteerId("ps1_m1");
        pinReq.setTargetPosition(2);
        PlanningStateDTO pinned = planningStateService.pinOrderedItem(1L, pinReq);
        assertTrue(pinned.getOrderedPlanState().getItems().stream()
                .anyMatch(item -> "ps1_m1".equals(item.getVolunteerId()) && Boolean.TRUE.equals(item.getPinned())));
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
    void shouldSkipPinnedOrderedItemsWhenMoving() {
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
        planningStateService.generateOrderedPlan(1L, 1L, generateReq);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedPinReq pinReq = new OrderedPinReq();
        pinReq.setVolunteerId("ps2_m2");
        pinReq.setTargetPosition(2);
        PlanningStateDTO pinned = planningStateService.pinOrderedItem(1L, pinReq);
        assertTrue(Boolean.TRUE.equals(pinned.getOrderedPlanState().getItems().get(1).getPinned()));

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);
        OrderedMoveReq moveReq = new OrderedMoveReq();
        moveReq.setVolunteerId("ps1_m1");
        moveReq.setTargetPosition(2);
        PlanningStateDTO moved = planningStateService.moveOrderedItem(1L, moveReq);
        assertEquals("ps3_m3", moved.getOrderedPlanState().getItems().get(0).getVolunteerId());
        assertEquals("ps2_m2", moved.getOrderedPlanState().getItems().get(1).getVolunteerId());
        assertEquals("ps1_m1", moved.getOrderedPlanState().getItems().get(2).getVolunteerId());
        assertTrue(Boolean.TRUE.equals(moved.getOrderedPlanState().getItems().get(1).getPinned()));
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
        assertEquals(Integer.valueOf(13), reviewState.getSummary().getTotal());
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
        assertTrue(state.getPendingActions().size() > 0);
    }

    @Test
    void shouldPreviewAndApplyCompensation() {
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

        CompensationPreviewDTO preview = planningStateService.previewCompensation(1L, 1L);
        assertTrue(preview.getTotalActions() > 0);
        assertTrue(preview.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getType())));
        assertTrue(preview.getActions().stream().anyMatch(action -> "add_local_protect".equals(action.getType())));

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CompensationApplyReq applyReq = new CompensationApplyReq();
        applyReq.setRegenerateOrderedPlan(true);
        applyReq.setRerunReview(false);
        PlanningStateDTO compensated = planningStateService.applyCompensation(1L, 1L, applyReq);

        assertTrue(compensated.getDraftPlanState().getSummary().getTotal() >= 4);
        assertEquals("ordered", compensated.getPhase());
        assertEquals(Integer.valueOf(0), Integer.valueOf(compensated.getPendingActions().size()));
        assertTrue(compensated.getOperationLogs().stream().anyMatch(log -> "compensation_apply".equals(log.getType())));
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

        CompensationPreviewDTO preview = planningStateService.previewCompensation(1L, 1L);
        assertTrue(preview.getActions().stream().anyMatch(action -> "fill_total_count".equals(action.getType())));
        assertFalse(preview.getActions().stream().flatMap(action -> action.getVolunteerIds().stream()).anyMatch("ps6_m6"::equals));
    }

    @Test
    void shouldCapCompensationActionsByRemainingGapBeforeApply() {
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

        CompensationPreviewDTO preview = planningStateService.previewCompensation(1L, 1L);
        assertEquals("ready", preview.getStatus());
        assertEquals(Integer.valueOf(1), preview.getTotalActions());
        long actionableVolunteerCount = preview.getActions().stream()
                .flatMap(action -> action.getVolunteerIds().stream())
                .distinct()
                .count();
        assertEquals(1L, actionableVolunteerCount);

        stored = latestStoredStateFromUpdate();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(eq(1L), eq(ChatSessionExtraDataConstants.PLANNING_STATE_KEY)))
                .thenReturn(stored);

        CompensationApplyReq applyReq = new CompensationApplyReq();
        applyReq.setRegenerateOrderedPlan(false);
        applyReq.setRerunReview(false);
        PlanningStateDTO compensated = planningStateService.applyCompensation(1L, 1L, applyReq);

        assertEquals(Integer.valueOf(4), compensated.getDraftPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(4), compensated.getOrderedPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(0), Integer.valueOf(compensated.getPendingActions().size()));
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

        CompensationPreviewDTO preview = planningStateService.previewCompensation(1L, 1L);
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

    private UserProfileData buildUserProfileData() {
        UserProfileData userProfileData = new UserProfileData();
        userProfileData.getCollege_info().setValues(java.util.Arrays.asList("清华大学"));
        userProfileData.getNegative_city_info().setProvince(java.util.Arrays.asList("河北"));
        return userProfileData;
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
