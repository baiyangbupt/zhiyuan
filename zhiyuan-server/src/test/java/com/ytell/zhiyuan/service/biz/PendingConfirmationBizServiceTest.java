package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationResolveReq;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class PendingConfirmationBizServiceTest {

    private PendingConfirmationBizService service;
    private PendingConfirmationSharedService sharedService;

    @BeforeEach
    void setUp() {
        service = new PendingConfirmationBizService();
        sharedService = mock(PendingConfirmationSharedService.class);
        ReflectionTestUtils.setField(service, "pendingConfirmationSharedService", sharedService);
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
