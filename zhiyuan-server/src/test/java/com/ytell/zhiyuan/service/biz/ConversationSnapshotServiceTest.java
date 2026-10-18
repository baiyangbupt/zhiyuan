package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationTurnSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewSummaryDTO;
import com.ytell.zhiyuan.model.dto.planning.StudentPlanningSummaryDTO;
import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

public class ConversationSnapshotServiceTest {

    private ConversationSnapshotService service;
    private PlanningStateService planningStateService;
    private PendingConfirmationBizService pendingConfirmationBizService;
    private EvidenceLedgerService evidenceLedgerService;

    @BeforeEach
    void setUp() {
        service = new ConversationSnapshotService();
        planningStateService = Mockito.mock(PlanningStateService.class);
        pendingConfirmationBizService = Mockito.mock(PendingConfirmationBizService.class);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(service, "pendingConfirmationBizService", pendingConfirmationBizService);
        // 快照现在会去台账捞当前会话的有效证据；不注入的话是 NPE，而不是"没有证据"。
        evidenceLedgerService = Mockito.mock(EvidenceLedgerService.class);
        ReflectionTestUtils.setField(service, "evidenceLedgerService", evidenceLedgerService);
    }

    @Test
    void shouldProjectAuthoritativeScoreAndReadOnlyCapabilities() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        StudentPlanningSummaryDTO student = new StudentPlanningSummaryDTO();
        student.setProvinceName("浙江");
        student.setExamYear(2026);
        student.setScore(612);
        student.setRank(18420);
        workspace.setStudentSummary(student);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertEquals(42, snapshot.getSnapshotVersion());
        assertEquals("浙江", snapshot.getScoreContext().get("province"));
        assertEquals(2026, snapshot.getScoreContext().get("examYear"));
        assertEquals(18420, snapshot.getScoreContext().get("rank"));
        assertTrue(snapshot.getAllowedCapabilities().contains("admission_read"));
        assertTrue(!snapshot.getAllowedCapabilities().contains("plan_apply"));
        assertTrue(snapshot.getPreferences().containsKey("candidateSummary"));
        assertTrue(snapshot.getPreferences().containsKey("reviewSummary"));
        assertEquals("completed", snapshot.getPreferences().get("reviewEvaluationStatus"));
        assertEquals("eval-v1", snapshot.getPreferences().get("reviewEvaluationVersion"));
        assertEquals(true, snapshot.getPreferences().get("reviewHardFeasible"));
    }

    @Test
    void shouldProjectMajorGroupAsCanonicalAdmissionMode() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        workspace.getCandidatePoolState().setVolunteerModel("majorGroup");
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertEquals("major_group", snapshot.getAdmissionMode());
    }

    @Test
    void shouldExposeMissingScoreAndActivePendingWithoutFullWorkspaceState() {
        PlanningWorkspaceStateRes workspace = workspace(null, 101L);
        workspace.setStudentSummary(new StudentPlanningSummaryDTO());
        StaleFlagsDTO staleFlags = new StaleFlagsDTO();
        staleFlags.setReview(true);
        workspace.setStaleFlags(staleFlags);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        PendingConfirmationRes pending = new PendingConfirmationRes();
        pending.setPendingId("pending-1");
        pending.setRevision(3L);
        pending.setKind("plan_mutation");
        pending.setActionFamily("apply_plan_change_proposal");
        pending.setStatus("active");
        pending.setDataValue(new java.util.LinkedHashMap<String, Object>() {{
            put("kind", "plan");
            put("sourceBackendVersion", 42);
        }});
        doReturn(pending).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertEquals(0, snapshot.getSnapshotVersion());
        assertTrue(snapshot.getMissingFacts().containsAll(Arrays.asList("province", "score", "rank")));
        assertEquals("pending-1", snapshot.getActiveProposal().get("pendingId"));
        assertEquals("pending-1", snapshot.getActiveProposal().get("proposalRef"));
        assertEquals(3L, snapshot.getActiveProposal().get("revision"));
        assertEquals(42, snapshot.getActiveProposal().get("sourceVersion"));
        assertEquals(true, snapshot.getActiveProposal().get("requiresConfirmation"));
        assertEquals("apply_plan_change_proposal", snapshot.getActiveProposal().get("actionFamily"));
        assertTrue(snapshot.getActiveProposal().containsKey("data"));
        assertTrue(snapshot.getConfirmedConstraints().containsKey("staleFlags"));
    }

    @Test
    void shouldExposeConfirmedPlanningObjectivesInSnapshot() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO rule =
                new com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO();
        rule.setDomain("region");
        rule.setKey("city");
        rule.setValues(Arrays.asList("北京"));
        rule.setOrderingTarget("rank_before");
        rule.setScope("within_tier");
        workspace.getConstraintState().getHardPlanningObjectives().getPriorityRules().add(rule);
        com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO quota =
                new com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO();
        quota.setType("exact_counts");
        quota.setSprintCount(16);
        quota.setStableCount(24);
        quota.setProtectCount(20);
        workspace.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        // 已确认的规划目标（同档前置规则/数量目标）必须对模型可见（review §五-21-C）：
        // 缺了它们，模型读到的约束与真实生效的硬性目标不一致。
        Object objectives = snapshot.getConfirmedConstraints().get("hardPlanningObjectives");
        assertTrue(objectives instanceof com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO,
                "hardPlanningObjectives 必须进 confirmedConstraints，实际: " + objectives);
        com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO typed =
                (com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO) objectives;
        assertEquals(1, typed.getPriorityRules().size());
        assertEquals("北京", typed.getPriorityRules().get(0).getValues().get(0));
        assertEquals(Integer.valueOf(16), typed.getTierQuotaGoal().getSprintCount());
    }

    @Test
    void shouldRejectWorkspaceForAnotherSession() {
        PlanningWorkspaceStateRes workspace = workspace(42, 999L);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));

        assertThrows(IllegalStateException.class,
                () -> service.getTurnSnapshot(7L, 101L));
    }

    @Test
    void shouldProjectJourneyFactsForEmptySession() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        workspace.getCandidatePoolState().getSummary().setTotal(0);
        workspace.setStudentSummary(new StudentPlanningSummaryDTO());
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertNotNull(snapshot.getJourney());
        assertFalse(snapshot.getJourney().getHasProfile());
        assertTrue(snapshot.getJourney().getProfileMissing().containsAll(
                Arrays.asList("province", "examYear", "batch", "subjectType", "scoreOrRank")));
        assertFalse(snapshot.getJourney().getHasCandidates());
        assertFalse(snapshot.getJourney().getHasPlan());
        assertFalse(snapshot.getJourney().getPlanInterpretable());
        assertEquals(42, snapshot.getJourney().getPlanVersion().intValue());
        assertNull(snapshot.getJourney().getPendingStatus());
    }

    @Test
    void shouldProjectCompleteProfileCandidatesAndReviewFreshness() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        StudentPlanningSummaryDTO student = new StudentPlanningSummaryDTO();
        student.setProvinceName("浙江");
        student.setExamYear(2026);
        student.setBatchName("普通类一段");
        student.setSubjectType("综合");
        student.setScore(612);
        workspace.setStudentSummary(student);
        workspace.getCandidatePoolState().setSourceVersion(7);
        workspace.getReviewState().setStatus("completed");
        workspace.getReviewState().setSourceVersion(41);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertTrue(snapshot.getJourney().getHasProfile());
        assertTrue(snapshot.getJourney().getProfileMissing().isEmpty());
        assertTrue(snapshot.getJourney().getHasCandidates());
        assertEquals(12, snapshot.getJourney().getCandidateEntryCount().intValue());
        assertEquals(7, snapshot.getJourney().getCandidateSourceVersion().intValue());
        assertEquals("fresh", snapshot.getJourney().getCandidateFreshness());
        assertEquals("absent", snapshot.getJourney().getPlanFreshness());
        assertEquals("fresh", snapshot.getJourney().getReviewFreshness());
        assertEquals("plan", snapshot.getJourney().getRefreshRequirement());
    }

    @Test
    void shouldTreatWorkingUnitOnlyPlanAsPlanButNotInterpretable() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        DraftUnitDTO unit = new DraftUnitDTO();
        unit.setUnitId("unit-1");
        unit.setSchoolName("示例大学");
        workspace.getWorkingPlanState().getUnits().add(unit);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertTrue(snapshot.getJourney().getHasPlan());
        assertEquals(1, snapshot.getJourney().getPlanEntryCount().intValue());
        assertEquals(0, snapshot.getJourney().getOrderedEntryCount().intValue());
        assertFalse(snapshot.getJourney().getPlanInterpretable());
        assertEquals(
                EvaluationVersion.sha256("working|" + JSON.toJSONString(workspace.getWorkingPlanState())),
                snapshot.getJourney().getPlanContentDigest());
    }

    @Test
    void shouldCountOrderedEntriesByAdmissionMode() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        workspace.getCandidatePoolState().setVolunteerModel("majorGroup");
        OrderedUnitDTO first = new OrderedUnitDTO();
        first.setUnitId("unit-1");
        OrderedUnitDTO second = new OrderedUnitDTO();
        second.setUnitId("unit-2");
        workspace.getOrderedPlanState().getUnits().add(first);
        workspace.getOrderedPlanState().getUnits().add(second);
        workspace.getOrderedPlanState().getUnits().add(null);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertEquals("major_group", snapshot.getAdmissionMode());
        assertTrue(snapshot.getJourney().getHasPlan());
        assertEquals(2, snapshot.getJourney().getPlanEntryCount().intValue());
        assertEquals(2, snapshot.getJourney().getOrderedEntryCount().intValue());
        assertTrue(snapshot.getJourney().getPlanInterpretable());

        PlanningStateDTO state = new PlanningStateDTO();
        state.setOrderedPlanState(workspace.getOrderedPlanState());
        state.setCandidatePoolState(workspace.getCandidatePoolState());
        assertEquals(
                PlanAdmissionInterpretationFacade.buildEntries(state, true).size(),
                snapshot.getJourney().getOrderedEntryCount().intValue());
    }

    @Test
    void shouldExposeComponentFreshnessAfterScoreUpdate() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        StudentPlanningSummaryDTO student = new StudentPlanningSummaryDTO();
        student.setProvinceName("浙江");
        student.setExamYear(2026);
        student.setBatchName("普通类一段");
        student.setSubjectType("综合");
        student.setScore(612);
        workspace.setStudentSummary(student);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        workspace.getOrderedPlanState().getItems().add(item);
        StaleFlagsDTO flags = new StaleFlagsDTO();
        flags.setCandidatePool(true);
        flags.setOrderedPlan(true);
        flags.setReview(true);
        flags.setReasonCode("score_detail_updated");
        flags.setMessage("成绩信息已补录");
        workspace.setStaleFlags(flags);
        workspace.getDataFreshnessState().setRequiresCandidateRefresh(true);
        workspace.getReviewState().setStatus("completed");
        workspace.getReviewState().setSourceVersion(41);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertTrue(snapshot.getJourney().getHasPlan());
        assertEquals("stale", snapshot.getJourney().getCandidateFreshness());
        assertEquals("stale", snapshot.getJourney().getPlanFreshness());
        assertEquals("stale", snapshot.getJourney().getReviewFreshness());
        assertEquals("candidates", snapshot.getJourney().getRefreshRequirement());
        assertTrue(snapshot.getJourney().getStale());
        assertEquals("score_detail_updated", snapshot.getJourney().getStaleReasonCode());
        assertEquals("成绩信息已补录", snapshot.getJourney().getStaleMessage());
    }

    @Test
    void shouldNotTreatPlanAdjustmentAsPlanDataStaleness() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        workspace.getOrderedPlanState().getItems().add(item);
        StaleFlagsDTO flags = new StaleFlagsDTO();
        flags.setPlanAdjustment(true);
        workspace.setStaleFlags(flags);
        workspace.getReviewState().setStatus("completed");
        workspace.getReviewState().setSourceVersion(41);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertEquals("fresh", snapshot.getJourney().getPlanFreshness());
        assertTrue(snapshot.getJourney().getPlanAdjustmentStale());
        assertEquals("none", snapshot.getJourney().getRefreshRequirement());
    }

    @Test
    void shouldExposePendingStatusFromTheSameRead() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        PendingConfirmationRes active = new PendingConfirmationRes();
        active.setPendingId("pending-1");
        active.setRevision(3L);
        active.setStatus("active");
        active.setKind("plan_action");
        doReturn(active).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO first = service.getTurnSnapshot(7L, 101L);
        assertNotNull(first.getActiveProposal());
        assertEquals("active", first.getJourney().getPendingStatus());

        active.setStatus("applying");
        ConversationTurnSnapshotDTO second = service.getTurnSnapshot(7L, 101L);
        assertNull(second.getActiveProposal());
        assertEquals("applying", second.getJourney().getPendingStatus());
        verify(pendingConfirmationBizService, times(2)).getActiveOrApplying(7L, 101L);
        verify(pendingConfirmationBizService, never()).getCurrent(7L, 101L);
    }

    @Test
    void shouldMatchEvaluationDigestForOrderedPlan() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        item.setPosition(1);
        workspace.getOrderedPlanState().getItems().add(item);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);
        PlanningStateDTO state = new PlanningStateDTO();
        state.setOrderedPlanState(workspace.getOrderedPlanState());
        state.setCandidatePoolState(workspace.getCandidatePoolState());
        ReviewStateDTO review = new ReviewStateDTO();
        String evaluationDigest = new EvaluationContextBuilder()
                .build(state, null, review).getPlanContentDigest();

        assertEquals(evaluationDigest, snapshot.getJourney().getPlanContentDigest());
    }

    @Test
    void shouldCopySelectionCountsIntoJourney() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        workspace.setSelectionTargetCount(45);
        workspace.setSelectionCurrentCount(43);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L);

        assertEquals(45, snapshot.getJourney().getSelectionTargetCount().intValue());
        assertEquals(43, snapshot.getJourney().getSelectionCurrentCount().intValue());
    }

    private PlanningWorkspaceStateRes workspace(Integer version, Long sessionId) {
        PlanningWorkspaceStateRes workspace = new PlanningWorkspaceStateRes();
        workspace.setVersion(version);
        workspace.setSessionId(sessionId);
        workspace.setPhase("candidate_exploration");
        ReviewSummaryDTO reviewSummary = new ReviewSummaryDTO();
        reviewSummary.setRiskCount(1);
        workspace.getReviewState().setSummary(reviewSummary);
        workspace.getReviewState().setEvaluationStatus("completed");
        workspace.getReviewState().setEvaluationVersion("eval-v1");
        workspace.getReviewState().setHardFeasible(true);
        CandidatePoolStateDTO candidatePool = new CandidatePoolStateDTO();
        candidatePool.getSummary().setTotal(12);
        workspace.setCandidatePoolState(candidatePool);
        return workspace;
    }

    @Test
    void shouldCarrySessionEvidenceIntoTheSnapshot() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(1L, 101L);
        doReturn(null).when(pendingConfirmationBizService).getActiveOrApplying(1L, 101L);

        ConversationEvidenceDTO ledgerRow = new ConversationEvidenceDTO();
        ledgerRow.setEvidenceId("ev_real");
        ledgerRow.setSourceLevel("authoritative");
        ledgerRow.setDataVersion("sha256:abc");
        doReturn(java.util.Collections.singletonList(ledgerRow))
                .when(evidenceLedgerService).listSessionEvidence(eq(1L), eq(101L), org.mockito.ArgumentMatchers.any(java.util.Date.class));

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(1L, 101L);

        // 空实现时代这里恒为 0：快照永远不带证据，模型看到的是"什么都不记得"的上下文。
        assertEquals(1, snapshot.getEvidence().size());
        assertEquals("ev_real", snapshot.getEvidence().get(0).getEvidenceId());
    }
}
