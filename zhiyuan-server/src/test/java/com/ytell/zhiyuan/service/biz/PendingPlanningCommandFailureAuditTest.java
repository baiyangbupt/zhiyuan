package com.ytell.zhiyuan.service.biz;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PendingPlanningCommandFailureAuditTest {
    private PendingPlanningCommandBizService service;
    private PlanningPendingCommandSharedService commandSharedService;
    private PlanningStateService planningStateService;
    private PlanningCommandFailureWriter failureWriter;
    private PendingPlanningCommandReq request;
    private PendingConfirmationEntity pending;
    private String originalFlag;
    private String originalReviewMode;

    @BeforeEach
    void setUp() {
        originalFlag = System.getProperty(ReviewFixCommandFlags.PROPERTY);
        originalReviewMode = System.getProperty(ReviewPolicy.PROPERTY);
        System.setProperty(ReviewFixCommandFlags.PROPERTY, "true");
        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        service = new PendingPlanningCommandBizService();
        commandSharedService = mock(PlanningPendingCommandSharedService.class);
        planningStateService = mock(PlanningStateService.class);
        failureWriter = mock(PlanningCommandFailureWriter.class);
        PendingConfirmationSharedService pendingSharedService = mock(PendingConfirmationSharedService.class);
        ReflectionTestUtils.setField(service, "commandSharedService", commandSharedService);
        ReflectionTestUtils.setField(service, "pendingSharedService", pendingSharedService);
        ReflectionTestUtils.setField(service, "extraDataSharedService", mock(ChatSessionExtraDataSharedService.class));
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(service, "failureWriter", failureWriter);
        request = request();
        pending = pending();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(pending);
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(12);
        when(planningStateService.loadPlanningStateReadOnly(101L)).thenReturn(state);
        when(planningStateService.getPlanningState(101L)).thenReturn(state);
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
    }

    @AfterEach
    void tearDown() {
        TransactionSynchronizationManager.clear();
        if (originalFlag == null) {
            System.clearProperty(ReviewFixCommandFlags.PROPERTY);
        } else {
            System.setProperty(ReviewFixCommandFlags.PROPERTY, originalFlag);
        }
        if (originalReviewMode == null) {
            System.clearProperty(ReviewPolicy.PROPERTY);
        } else {
            System.setProperty(ReviewPolicy.PROPERTY, originalReviewMode);
        }
    }

    @Test
    void shouldReplayPreviouslySucceededReviewCommandEvenWhenPaused() {
        System.setProperty(ReviewPolicy.PROPERTY, "paused");
        PlanningPendingCommandEntity existing = new PlanningPendingCommandEntity();
        existing.setTenantId(1L);
        existing.setChatSessionId(101L);
        existing.setPendingId(request.getPendingId());
        existing.setOperationId(request.getOperationId());
        existing.setCommandType(request.getCommandType());
        existing.setExpectedPlanVersion(request.getExpectedPlanVersion());
        existing.setRequestDigest((String) ReflectionTestUtils.invokeMethod(service, "requestDigest", request));
        existing.setStatus("succeeded");
        com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes stored =
                new com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes();
        stored.setOperationId(request.getOperationId());
        stored.setPendingId(request.getPendingId());
        stored.setCommandType(request.getCommandType());
        stored.setStatus("applied");
        stored.setSourcePlanVersion(12);
        stored.setResultPlanVersion(13);
        existing.setResultJson(JSONObject.toJSONString(stored));
        when(commandSharedService.getByOperationId(request.getOperationId())).thenReturn(existing);

        com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes replay =
                service.execute(1L, 101L, request);

        assertEquals(Boolean.TRUE, replay.getReplayed());
        assertEquals("applied", replay.getStatus());
        verify(planningStateService, never()).applyClaimedReviewFixProposal(any(), any(), any());
        verify(failureWriter, never()).recordFailure(any(), any(), any());
    }

    @Test
    void shouldRejectPausedReviewExecutionAndAuditAfterRollback() {
        System.setProperty(ReviewPolicy.PROPERTY, "paused");

        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, request));

        assertEquals(409, failure.getStatus());
        assertEquals("review_paused", failure.getMessage());
        verify(planningStateService, never()).applyClaimedReviewFixProposal(any(), any(), any());
        verify(planningStateService, never()).applyFixProposal(any(), any(), any());
        assertEquals(1, TransactionSynchronizationManager.getSynchronizations().size());

        TransactionSynchronizationManager.getSynchronizations().get(0)
                .afterCompletion(TransactionSynchronization.STATUS_ROLLED_BACK);

        verify(failureWriter).recordFailure(any(PlanningPendingCommandEntity.class), eq(pending), eq(failure));
    }

    @Test
    void shouldDeferReviewFailureAuditUntilTransactionRollback() {
        BusinessException failure = new BusinessException(40905, "review_fix_postcondition_failed");
        when(planningStateService.applyClaimedReviewFixProposal(eq(1L), eq(101L), any()))
                .thenThrow(failure);

        assertSame(failure, assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request)));

        assertEquals(1, TransactionSynchronizationManager.getSynchronizations().size());
        verify(commandSharedService).save(any(PlanningPendingCommandEntity.class));
        verify(commandSharedService, never()).updateById(any(PlanningPendingCommandEntity.class));
        verify(failureWriter, never()).recordFailure(any(), any(), any());

        TransactionSynchronizationManager.getSynchronizations().get(0)
                .afterCompletion(TransactionSynchronization.STATUS_ROLLED_BACK);

        verify(failureWriter).recordFailure(any(PlanningPendingCommandEntity.class), eq(pending), eq(failure));
    }

    @Test
    void shouldAuditAuthenticatedPreExecutionVersionDrift() {
        PlanningStateDTO changed = new PlanningStateDTO();
        changed.setVersion(13);
        when(planningStateService.loadPlanningStateReadOnly(101L)).thenReturn(changed);

        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, request));

        assertEquals(40904, failure.getStatus());
        assertEquals(1, TransactionSynchronizationManager.getSynchronizations().size());
        verify(commandSharedService, never()).save(any(PlanningPendingCommandEntity.class));
    }

    @Test
    void shouldNotAuditInvalidClaimOrExpireAnotherOwner() {
        request.setClaimToken("foreign-claim");

        assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request));

        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
        verify(planningStateService, never()).applyClaimedReviewFixProposal(any(), any(), any());
    }

    @Test
    void shouldNotAuditTamperedFrozenDigest() {
        request.getProposalApply().setCommandDigest("tampered");

        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, request));

        assertEquals(40908, failure.getStatus());
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    void shouldNotAuditForeignOperationEvenWithValidClaim() {
        request.setOperationId("foreign-operation");
        when(planningStateService.applyClaimedReviewFixProposal(eq(1L), eq(101L), any()))
                .thenThrow(new BusinessException(409, "review_fix_requires_claim"));

        assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request));

        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    void shouldNotAuditWrongProposalEvenWithValidClaim() {
        request.getProposalApply().setProposalId("foreign-proposal");
        when(planningStateService.applyClaimedReviewFixProposal(eq(1L), eq(101L), any()))
                .thenThrow(new BusinessException(409, "review_fix_changed"));

        assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request));

        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    void shouldNotAuditTamperedSourceVersionEvenWithValidClaim() {
        request.setExpectedPlanVersion(13);
        request.getProposalApply().setSourceVersionGuard(13);

        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, request));

        assertEquals(40904, failure.getStatus());
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
        verify(commandSharedService, never()).save(any(PlanningPendingCommandEntity.class));
    }

    @Test
    void shouldRejectFailedOperationReplayWithoutRetryingPlanMutation() {
        PlanningPendingCommandEntity failed = new PlanningPendingCommandEntity();
        failed.setTenantId(1L);
        failed.setChatSessionId(101L);
        failed.setPendingId(request.getPendingId());
        failed.setOperationId(request.getOperationId());
        failed.setCommandType(request.getCommandType());
        failed.setExpectedPlanVersion(request.getExpectedPlanVersion());
        failed.setRequestDigest((String) ReflectionTestUtils.invokeMethod(service, "requestDigest", request));
        failed.setStatus("failed");
        when(commandSharedService.getByOperationId(request.getOperationId())).thenReturn(failed);

        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, request));

        assertEquals(40903, failure.getStatus());
        assertTrue(failure.getMessage().contains("failed"));
        verify(planningStateService, never()).applyClaimedReviewFixProposal(any(), any(), any());
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    void shouldPreserveUserGoalFailurePathWithReviewFlagEnabled() {
        request.getProposalApply().setProposalSource("user_goal");
        setPendingProposalSource("user_goal");
        UserGoalFixProposalReq goal = new UserGoalFixProposalReq();
        goal.setGoalType("fill_to_count");
        goal.setTargetCount(20);
        goal.setSourceVersionGuard(12);
        request.getProposalApply().setUserGoalRequest(goal);
        when(planningStateService.applyFixProposal(eq(1L), eq(101L), any()))
                .thenThrow(new BusinessException(40905, "user_goal_failure"));

        assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request));

        verify(planningStateService).applyFixProposal(eq(1L), eq(101L), any());
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    void shouldPreserveLegacyReviewFailureAuditWhenReviewFlagIsDisabled() {
        System.setProperty(ReviewFixCommandFlags.PROPERTY, "false");
        when(planningStateService.applyFixProposal(eq(1L), eq(101L), any()))
                .thenThrow(new BusinessException(40905, "legacy_failure"));
        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, request));

        verify(planningStateService).applyFixProposal(eq(1L), eq(101L), any());
        assertEquals(1, TransactionSynchronizationManager.getSynchronizations().size());
        TransactionSynchronizationManager.getSynchronizations().get(0)
                .afterCompletion(TransactionSynchronization.STATUS_ROLLED_BACK);
        verify(failureWriter).recordFailure(any(PlanningPendingCommandEntity.class), eq(pending), eq(failure));
    }

    private void setPendingProposalSource(String source) {
        JSONObject data = JSONObject.parseObject(pending.getDataValue());
        data.put("proposalSource", source);
        pending.setDataValue(data.toJSONString());
    }

    @Test
    void shouldNotWriteFailureAuditOnCommittedOrUnknownCompletion() {
        when(planningStateService.applyClaimedReviewFixProposal(eq(1L), eq(101L), any()))
                .thenThrow(new BusinessException(40905, "review_fix_postcondition_failed"));
        assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request));
        TransactionSynchronization synchronization = TransactionSynchronizationManager.getSynchronizations().get(0);

        synchronization.afterCompletion(TransactionSynchronization.STATUS_COMMITTED);
        synchronization.afterCompletion(TransactionSynchronization.STATUS_UNKNOWN);

        verify(failureWriter, never()).recordFailure(any(), any(), any());
    }

    @Test
    void shouldPreserveOriginalFailureWhenIndependentAuditStorageFails() {
        BusinessException failure = new BusinessException(40905, "review_fix_postcondition_failed");
        when(planningStateService.applyClaimedReviewFixProposal(eq(1L), eq(101L), any())).thenThrow(failure);
        doThrow(new IllegalStateException("audit storage unavailable"))
                .when(failureWriter).recordFailure(any(), any(), any());

        assertSame(failure, assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request)));
        assertDoesNotThrow(() -> TransactionSynchronizationManager.getSynchronizations().get(0)
                .afterCompletion(TransactionSynchronization.STATUS_ROLLED_BACK));
    }

    @Test
    void shouldLogAuditFailureWithoutExceptionPayload() {
        BusinessException failure = new BusinessException(40905, "review_fix_postcondition_failed");
        when(planningStateService.applyClaimedReviewFixProposal(eq(1L), eq(101L), any())).thenThrow(failure);
        doThrow(new IllegalStateException("private-audit-payload-sentinel"))
                .when(failureWriter).recordFailure(any(), any(), any());
        Logger logger = (Logger) LoggerFactory.getLogger(PendingPlanningCommandBizService.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            assertSame(failure, assertThrows(BusinessException.class, () -> service.execute(1L, 101L, request)));
            TransactionSynchronizationManager.getSynchronizations().get(0)
                    .afterCompletion(TransactionSynchronization.STATUS_ROLLED_BACK);

            assertEquals(1, appender.list.size());
            ILoggingEvent event = appender.list.get(0);
            assertTrue(event.getFormattedMessage().contains("review-operation"));
            assertTrue(event.getFormattedMessage().contains("IllegalStateException"));
            assertFalse(event.getFormattedMessage().contains("private-audit-payload-sentinel"));
            assertNull(event.getThrowableProxy());
        } finally {
            logger.detachAppender(appender);
            appender.stop();
        }
    }

    private PendingPlanningCommandReq request() {
        PendingPlanningCommandReq value = new PendingPlanningCommandReq();
        value.setOperationId("review-operation");
        value.setPendingId("review-pending");
        value.setClaimToken("review-claim");
        value.setExpectedPlanVersion(12);
        value.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        FixProposalApplyReq apply = new FixProposalApplyReq();
        apply.setProposalId("review-proposal");
        apply.setSourceVersionGuard(12);
        apply.setCommandDigest("command-digest");
        apply.setPreviewDigest("preview-digest");
        apply.setEvaluationVersion("evaluation-version");
        value.setProposalApply(apply);
        return value;
    }

    private PendingConfirmationEntity pending() {
        PendingConfirmationEntity value = new PendingConfirmationEntity();
        value.setTenantId(1L);
        value.setChatSessionId(101L);
        value.setPendingId(request.getPendingId());
        value.setRevision(3L);
        value.setStatus("applying");
        value.setClaimToken(request.getClaimToken());
        value.setClaimExpiresAt(new Date(System.currentTimeMillis() + 120_000L));
        JSONObject data = new JSONObject(true);
        data.put("operationId", request.getOperationId());
        data.put("proposalId", request.getProposalApply().getProposalId());
        data.put("proposalSource", "review_check");
        data.put("sourceVersion", request.getExpectedPlanVersion());
        data.put("commandDigest", "command-digest");
        data.put("previewDigest", "preview-digest");
        data.put("evaluationVersion", "evaluation-version");
        value.setDataValue(data.toJSONString());
        return value;
    }
}
