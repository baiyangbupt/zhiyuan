package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
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

    @BeforeEach
    void setUp() {
        service = new ConversationSnapshotService();
        planningStateService = Mockito.mock(PlanningStateService.class);
        pendingConfirmationBizService = Mockito.mock(PendingConfirmationBizService.class);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(service, "pendingConfirmationBizService", pendingConfirmationBizService);
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
    void shouldExposeMissingScoreAndActivePendingWithoutFullWorkspaceState() {
        PlanningWorkspaceStateRes workspace = workspace(null, 101L);
        workspace.setStudentSummary(new StudentPlanningSummaryDTO());
        StaleFlagsDTO staleFlags = new StaleFlagsDTO();
        staleFlags.setReview(true);
        workspace.setStaleFlags(staleFlags);
        doReturn(workspace).when(planningStateService).getPlanningWorkspaceState(eq(7L), eq(101L));
        PendingConfirmationRes pending = new PendingConfirmationRes();
        pending.setPendingId("pending-1");
        pending.setStatus("active");
        pending.setDataValue(java.util.Collections.<String, Object>singletonMap("kind", "plan"));
        doReturn(pending).when(pendingConfirmationBizService).getCurrent(7L, 101L);

        ConversationTurnSnapshotDTO snapshot = service.getTurnSnapshot(7L, 101L, "profile-discovery");

        assertEquals(0, snapshot.getSnapshotVersion());
        assertTrue(snapshot.getMissingFacts().containsAll(Arrays.asList("province", "score", "rank")));
        assertEquals("pending-1", snapshot.getActiveProposal().get("pendingId"));
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
}
