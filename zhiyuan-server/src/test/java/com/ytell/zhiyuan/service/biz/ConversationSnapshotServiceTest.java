package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationTurnSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewSummaryDTO;
import com.ytell.zhiyuan.model.dto.planning.StudentPlanningSummaryDTO;
import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;

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
        doReturn(null).when(pendingConfirmationBizService).getCurrent(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L, "candidate-recommendation");

        assertEquals(42, snapshot.getSnapshotVersion());
        assertEquals("浙江", snapshot.getScoreContext().get("province"));
        assertEquals(2026, snapshot.getScoreContext().get("examYear"));
        assertEquals(18420, snapshot.getScoreContext().get("rank"));
        assertTrue(snapshot.getAllowedCapabilities().contains("admission_read"));
        assertTrue(!snapshot.getAllowedCapabilities().contains("plan_apply"));
        assertTrue(snapshot.getPreferences().containsKey("candidateSummary"));
        assertTrue(snapshot.getPreferences().containsKey("reviewSummary"));
    }

    @Test
    void shouldProjectMajorGroupAsCanonicalAdmissionMode() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        workspace.getCandidatePoolState().setVolunteerModel("majorGroup");
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        doReturn(null).when(pendingConfirmationBizService).getCurrent(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L, "candidate-recommendation");

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
        doReturn(pending).when(pendingConfirmationBizService).getCurrent(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L, "profile-discovery");

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
    void shouldRejectWorkspaceForAnotherSession() {
        PlanningWorkspaceStateRes workspace = workspace(42, 999L);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));

        assertThrows(IllegalStateException.class,
                () -> service.getTurnSnapshot(7L, 101L, "candidate-recommendation"));
    }

    private PlanningWorkspaceStateRes workspace(Integer version, Long sessionId) {
        PlanningWorkspaceStateRes workspace = new PlanningWorkspaceStateRes();
        workspace.setVersion(version);
        workspace.setSessionId(sessionId);
        workspace.setPhase("candidate_exploration");
        ReviewSummaryDTO reviewSummary = new ReviewSummaryDTO();
        reviewSummary.setRiskCount(1);
        workspace.getReviewState().setSummary(reviewSummary);
        CandidatePoolStateDTO candidatePool = new CandidatePoolStateDTO();
        candidatePool.getSummary().setTotal(12);
        workspace.setCandidatePoolState(candidatePool);
        return workspace;
    }

    @Test
    void shouldCarrySessionEvidenceIntoTheSnapshot() {
        PlanningWorkspaceStateRes workspace = workspace(42, 101L);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(1L, 101L);
        doReturn(null).when(pendingConfirmationBizService).getCurrent(1L, 101L);

        ConversationEvidenceDTO ledgerRow = new ConversationEvidenceDTO();
        ledgerRow.setEvidenceId("ev_real");
        ledgerRow.setSourceLevel("authoritative");
        ledgerRow.setDataVersion("sha256:abc");
        doReturn(java.util.Collections.singletonList(ledgerRow))
                .when(evidenceLedgerService).listSessionEvidence(eq(1L), eq(101L), org.mockito.ArgumentMatchers.any(java.util.Date.class));

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(1L, 101L, null);

        // 空实现时代这里恒为 0：快照永远不带证据，模型看到的是"什么都不记得"的上下文。
        assertEquals(1, snapshot.getEvidence().size());
        assertEquals("ev_real", snapshot.getEvidence().get(0).getEvidenceId());
    }
}
