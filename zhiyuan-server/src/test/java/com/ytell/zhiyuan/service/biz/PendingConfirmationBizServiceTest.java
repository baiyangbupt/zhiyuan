package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationResolveReq;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.inner.PendingReconcileRes;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class PendingConfirmationBizServiceTest {

    private PendingConfirmationBizService service;
    private PendingConfirmationSharedService sharedService;
    private PlanningPendingCommandSharedService commandSharedService;

    @BeforeEach
    void setUp() {
        service = new PendingConfirmationBizService();
        sharedService = mock(PendingConfirmationSharedService.class);
        commandSharedService = mock(PlanningPendingCommandSharedService.class);
        ReflectionTestUtils.setField(service, "pendingConfirmationSharedService", sharedService);
        ReflectionTestUtils.setField(service, "pendingCommandSharedService", commandSharedService);
    }

    @Test
    void shouldCreateFirstRevision() {
        when(sharedService.getCurrent(1L, 101L)).thenReturn(null);
        when(sharedService.save(any(PendingConfirmationEntity.class))).thenReturn(true);

        PendingConfirmationRes response = service.upsert(1L, upsert(101L, "p-1", 0L));

        assertEquals(Long.valueOf(1L), response.getRevision());
        assertEquals("active", response.getStatus());
        assertTrue(response.getTransitionApplied());
        assertEquals(1L, ((Number) response.getDataValue().get("revision")).longValue());
    }

    @Test
    void shouldReplaceWithMatchingRevision() {
        PendingConfirmationEntity current = entity(101L, "p-1", 3L, "active");
        when(sharedService.getCurrent(1L, 101L)).thenReturn(current);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class), anyLong(), anyString(), anyString()))
                .thenReturn(true);

        PendingConfirmationRes response = service.upsert(1L, upsert(101L, "p-2", 3L));

        assertEquals(Long.valueOf(4L), response.getRevision());
        assertEquals("p-2", response.getPendingId());
        ArgumentCaptor<PendingConfirmationEntity> captor = ArgumentCaptor.forClass(PendingConfirmationEntity.class);
        verify(sharedService).compareAndSet(captor.capture(), org.mockito.ArgumentMatchers.eq(3L),
                org.mockito.ArgumentMatchers.eq("p-1"), org.mockito.ArgumentMatchers.eq("active"));
        assertEquals("p-2", captor.getValue().getPendingId());
    }

    @Test
    void shouldRejectStaleRevision() {
        when(sharedService.getCurrent(1L, 101L)).thenReturn(entity(101L, "p-current", 4L, "active"));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.upsert(1L, upsert(101L, "p-new", 3L)));

        assertEquals(PendingConfirmationBizService.CAS_CONFLICT_CODE, error.getStatus());
    }

    @Test
    void shouldRejectUpsertWhenCurrentIsApplying() {
        // 交错形状：回合开始时快照不是 applying，随后另一请求 claim 成 applying；
        // 发展方向路径重新读到的就是这一行（revision 也是最新的）。只比 revision 的
        // CAS 会成功覆盖，所以写入口必须直接拒绝。
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        when(sharedService.getCurrent(1L, 101L)).thenReturn(current);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.upsert(1L, upsert(101L, "p-new", 5L)));

        assertEquals(409, error.getStatus());
        verify(sharedService, never()).compareAndSet(any(PendingConfirmationEntity.class),
                anyLong(), anyString(), anyString());
    }

    @Test
    void shouldRejectPendingIdMismatchBeforeResolve() {
        when(sharedService.getCurrent(1L, 101L)).thenReturn(entity(101L, "p-current", 4L, "active"));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.resolve(1L, resolve(101L, "p-stale", 4L, "cancel")));

        assertEquals(PendingConfirmationBizService.PENDING_MISMATCH_CODE, error.getStatus());
    }

    @Test
    void shouldClaimConfirmExactlyOnce() {
        PendingConfirmationEntity current = entity(101L, "p-1", 4L, "active");
        when(sharedService.getCurrent(1L, 101L)).thenReturn(current);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class), anyLong(), anyString(), anyString()))
                .thenReturn(true);

        PendingConfirmationRes response = service.resolve(1L, resolve(101L, "p-1", 4L, "confirm"));

        assertEquals("applying", response.getStatus());
        assertEquals(Long.valueOf(5L), response.getRevision());
        assertTrue(response.getTransitionApplied());
        assertEquals("claim-1", response.getClaimToken());
        assertTrue(response.getClaimExpiresAt().after(new Date()));
    }

    @Test
    void shouldReturnIdempotentCancelWithoutSecondTransition() {
        PendingConfirmationEntity cancelled = entity(101L, "p-1", 5L, "cancelled");
        when(sharedService.getCurrent(1L, 101L)).thenReturn(cancelled);

        PendingConfirmationRes response = service.resolve(1L, resolve(101L, "p-1", 4L, "cancel"));

        assertEquals("cancelled", response.getStatus());
        assertFalse(response.getTransitionApplied());
    }

    @Test
    void shouldCompleteClaimedPending() {
        PendingConfirmationEntity applying = entity(101L, "p-1", 5L, "applying");
        when(sharedService.getCurrent(1L, 101L)).thenReturn(applying);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class), anyLong(), anyString(), anyString()))
                .thenReturn(true);
        PendingConfirmationResolveReq req = resolve(101L, "p-1", 5L, "complete");
        req.setResultCode("applied");

        PendingConfirmationRes response = service.resolve(1L, req);

        assertEquals("applied", response.getStatus());
        assertEquals(Long.valueOf(6L), response.getRevision());
        assertEquals("applied", response.getResultCode());
    }

    @Test
    void shouldNotReclaimUnexpiredApplyingLease() {
        PendingConfirmationEntity applying = entity(101L, "p-1", 5L, "applying");
        when(sharedService.getCurrent(1L, 101L)).thenReturn(applying);
        PendingConfirmationResolveReq req = resolve(101L, "p-1", 5L, "confirm");
        req.setClaimToken("claim-2");

        PendingConfirmationRes response = service.resolve(1L, req);

        assertFalse(response.getTransitionApplied());
        assertEquals(Long.valueOf(5L), response.getRevision());
        assertEquals("claim-1", response.getClaimToken());
    }

    @Test
    void shouldReclaimExpiredApplyingLeaseWithNewToken() {
        PendingConfirmationEntity applying = entity(101L, "p-1", 5L, "applying");
        applying.setClaimExpiresAt(new Date(System.currentTimeMillis() - 1000L));
        when(sharedService.getCurrent(1L, 101L)).thenReturn(applying);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class), anyLong(), anyString(), anyString()))
                .thenReturn(true);
        PendingConfirmationResolveReq req = resolve(101L, "p-1", 5L, "confirm");
        req.setClaimToken("claim-2");

        PendingConfirmationRes response = service.resolve(1L, req);

        assertTrue(response.getTransitionApplied());
        assertEquals(Long.valueOf(6L), response.getRevision());
        assertEquals("claim-2", response.getClaimToken());
    }

    @Test
    void shouldRejectCompletionFromPreviousLeaseOwner() {
        PendingConfirmationEntity applying = entity(101L, "p-1", 6L, "applying");
        applying.setClaimToken("claim-2");
        when(sharedService.getCurrent(1L, 101L)).thenReturn(applying);
        PendingConfirmationResolveReq req = resolve(101L, "p-1", 6L, "complete");
        req.setClaimToken("claim-1");

        BusinessException error = assertThrows(BusinessException.class, () -> service.resolve(1L, req));

        assertEquals(PendingConfirmationBizService.PENDING_MISMATCH_CODE, error.getStatus());
    }

    @Test
    void shouldReconcileSucceededCommandToApplied() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setDataValue("{\"operationId\":\"op-1\"}");
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        PlanningPendingCommandEntity command = new PlanningPendingCommandEntity();
        command.setOperationId("op-1");
        command.setPendingId("p-1");
        command.setTenantId(1L);
        command.setChatSessionId(101L);
        command.setStatus("succeeded");
        command.setResultJson("{\"resultPlanVersion\":87}");
        when(commandSharedService.getByOperationId("op-1")).thenReturn(command);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class),
                eq(5L), eq("p-1"), eq("applying"))).thenReturn(true);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_APPLIED, response.getOutcome());
        assertEquals("applied", response.getPendingStatus());
        assertEquals(Integer.valueOf(87), response.getResultPlanVersion());
        assertTrue(response.getReceiptAvailable());
        ArgumentCaptor<PendingConfirmationEntity> captor =
                ArgumentCaptor.forClass(PendingConfirmationEntity.class);
        verify(sharedService).compareAndSet(captor.capture(),
                eq(5L), eq("p-1"), eq("applying"));
        assertEquals("applied", captor.getValue().getStatus());
        assertEquals("reconcile", captor.getValue().getResolvedAction());
    }

    @Test
    void shouldReconcileFailedCommandAsKnownFailureInsteadOfUnknownResult() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setDataValue("{\"operationId\":\"op-failed\"}");
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        PlanningPendingCommandEntity command = new PlanningPendingCommandEntity();
        command.setTenantId(1L);
        command.setChatSessionId(101L);
        command.setPendingId("p-1");
        command.setOperationId("op-failed");
        command.setStatus("failed");
        command.setResultJson("{\"status\":\"failed\",\"errorCode\":40905,\"reasonCode\":\"review_fix_postcondition_failed\"}");
        when(commandSharedService.getByOperationId("op-failed")).thenReturn(command);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class),
                eq(5L), eq("p-1"), eq("applying"))).thenReturn(true);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_EXPIRED, response.getOutcome());
        assertEquals("failed", response.getOperationStatus());
        assertEquals("40905", response.getResultCode());
        assertTrue(response.getReceiptAvailable());
        assertEquals("expired", response.getPendingStatus());
    }

    @Test
    void shouldReturnPersistedFailureCodeForAlreadyExpiredPending() {
        PendingConfirmationEntity current = entity(101L, "p-1", 6L, "expired");
        current.setResultCode("40905");
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_NOT_APPLYING, response.getOutcome());
        assertEquals("40905", response.getResultCode());
        verify(sharedService, never()).compareAndSet(any(), anyLong(), anyString(), anyString());
    }

    @Test
    void shouldExpireMissingOperationWithinProofWindow() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setDataValue("{\"operationId\":\"op-missing\"}");
        current.setClaimExpiresAt(new Date(System.currentTimeMillis() - 1000L));
        current.setCreateTime(new Date());
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        when(commandSharedService.getByOperationId("op-missing")).thenReturn(null);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class),
                eq(5L), eq("p-1"), eq("applying"))).thenReturn(true);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_EXPIRED, response.getOutcome());
        assertEquals(PendingReconcileRes.RESULT_NO_OPERATION_SUBMITTED, response.getResultCode());
        assertEquals("expired", response.getPendingStatus());
    }

    @Test
    void shouldNotClaimNoOperationForGatewayExecutedCareerUpdate() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setKind("career_update");
        current.setActionFamily("update_career_types");
        current.setClaimExpiresAt(new Date(System.currentTimeMillis() - 1000L));
        current.setCreateTime(new Date());
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        when(commandSharedService.getByOperationId(anyString())).thenReturn(null);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class),
                eq(5L), eq("p-1"), eq("applying"))).thenReturn(true);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_EXPIRED, response.getOutcome());
        assertEquals(PendingReconcileRes.RESULT_OPERATION_UNKNOWN, response.getResultCode());
    }

    @Test
    void shouldNotApplyGatewayExecutedKindFromPlanCommandLedger() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setKind("career_update");
        current.setActionFamily("update_career_types");
        current.setDataValue("{\"operationId\":\"op-career\"}");
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        PlanningPendingCommandEntity command = new PlanningPendingCommandEntity();
        command.setOperationId("op-career");
        command.setPendingId("p-1");
        command.setTenantId(1L);
        command.setChatSessionId(101L);
        command.setStatus("succeeded");
        when(commandSharedService.getByOperationId("op-career")).thenReturn(command);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertTrue(PendingReconcileRes.OUTCOME_STILL_APPLYING.equals(response.getOutcome())
                || PendingReconcileRes.OUTCOME_EXPIRED.equals(response.getOutcome()));
        verify(sharedService, never()).compareAndSet(any(PendingConfirmationEntity.class),
                anyLong(), anyString(), anyString());
    }

    @Test
    void shouldNotClaimNoOperationOutsideProofWindow() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setDataValue("{\"operationId\":\"op-missing\"}");
        current.setClaimExpiresAt(new Date(System.currentTimeMillis() - 1000L));
        current.setCreateTime(new Date(System.currentTimeMillis() - 2L * 24L * 60L * 60L * 1000L));
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        when(commandSharedService.getByOperationId("op-missing")).thenReturn(null);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class),
                eq(5L), eq("p-1"), eq("applying"))).thenReturn(true);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_EXPIRED, response.getOutcome());
        assertEquals(PendingReconcileRes.RESULT_OPERATION_UNKNOWN, response.getResultCode());
    }

    @Test
    void shouldWaitForRunningCommandWhileClaimIsAlive() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setDataValue("{\"operationId\":\"op-running\"}");
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        PlanningPendingCommandEntity command = new PlanningPendingCommandEntity();
        command.setOperationId("op-running");
        command.setPendingId("p-1");
        command.setTenantId(1L);
        command.setChatSessionId(101L);
        command.setStatus("running");
        command.setUpdateTime(new Date());
        when(commandSharedService.getByOperationId("op-running")).thenReturn(command);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_STILL_APPLYING, response.getOutcome());
        assertEquals("running", response.getOperationStatus());
        verify(sharedService, never()).compareAndSet(any(PendingConfirmationEntity.class),
                anyLong(), anyString(), anyString());
    }

    @Test
    void shouldExpireRunningCommandAfterGrace() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "applying");
        current.setDataValue("{\"operationId\":\"op-running\"}");
        current.setClaimExpiresAt(new Date(System.currentTimeMillis() - 1000L));
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);
        PlanningPendingCommandEntity command = new PlanningPendingCommandEntity();
        command.setOperationId("op-running");
        command.setPendingId("p-1");
        command.setTenantId(1L);
        command.setChatSessionId(101L);
        command.setStatus("running");
        command.setUpdateTime(new Date(System.currentTimeMillis() - 11L * 60L * 1000L));
        when(commandSharedService.getByOperationId("op-running")).thenReturn(command);
        when(sharedService.compareAndSet(any(PendingConfirmationEntity.class),
                eq(5L), eq("p-1"), eq("applying"))).thenReturn(true);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_EXPIRED, response.getOutcome());
        assertEquals(PendingReconcileRes.RESULT_OPERATION_UNKNOWN, response.getResultCode());
    }

    @Test
    void shouldBeIdempotentWhenPendingIsNotApplying() {
        PendingConfirmationEntity current = entity(101L, "p-1", 5L, "active");
        when(sharedService.lockCurrent(1L, 101L)).thenReturn(current);

        PendingReconcileRes response = service.reconcile(1L, 101L);

        assertEquals(PendingReconcileRes.OUTCOME_NOT_APPLYING, response.getOutcome());
        assertEquals("active", response.getPendingStatus());
        verify(sharedService, never()).compareAndSet(any(PendingConfirmationEntity.class),
                anyLong(), anyString(), anyString());
    }

    private PendingConfirmationUpsertReq upsert(Long sessionId, String pendingId, Long revision) {
        PendingConfirmationUpsertReq req = new PendingConfirmationUpsertReq();
        req.setChatSessionId(sessionId);
        req.setPendingId(pendingId);
        req.setExpectedRevision(revision);
        req.setKind("plan_mutation");
        req.setActionFamily("remove_units");
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("pendingId", pendingId);
        payload.put("kind", "plan_mutation");
        payload.put("actionFamily", "remove_units");
        payload.put("status", "active");
        req.setDataValue(payload);
        return req;
    }

    private PendingConfirmationResolveReq resolve(Long sessionId, String pendingId, Long revision, String action) {
        PendingConfirmationResolveReq req = new PendingConfirmationResolveReq();
        req.setChatSessionId(sessionId);
        req.setPendingId(pendingId);
        req.setExpectedRevision(revision);
        req.setAction(action);
        if ("confirm".equals(action) || "complete".equals(action) || "fail".equals(action)) {
            req.setClaimToken("claim-1");
        }
        return req;
    }

    private PendingConfirmationEntity entity(Long sessionId, String pendingId, Long revision, String status) {
        PendingConfirmationEntity entity = new PendingConfirmationEntity();
        entity.setId(9L);
        entity.setTenantId(1L);
        entity.setChatSessionId(sessionId);
        entity.setPendingId(pendingId);
        entity.setRevision(revision);
        entity.setKind("plan_mutation");
        entity.setActionFamily("remove_units");
        entity.setStatus(status);
        if ("applying".equals(status) || "applied".equals(status) || "expired".equals(status)) {
            entity.setClaimToken("claim-1");
            entity.setClaimExpiresAt(new Date(System.currentTimeMillis() + 300000L));
        }
        entity.setDataValue("{\"pendingId\":\"" + pendingId + "\",\"kind\":\"plan_mutation\","
                + "\"actionFamily\":\"remove_units\",\"status\":\"" + status + "\",\"revision\":" + revision + "}");
        return entity;
    }
}
