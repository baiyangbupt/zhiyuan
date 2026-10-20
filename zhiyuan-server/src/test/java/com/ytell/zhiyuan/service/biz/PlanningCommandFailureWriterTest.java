package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PlanningCommandFailureWriterTest {
    private PlanningCommandFailureWriter writer;
    private PlanningPendingCommandSharedService commands;
    private PendingConfirmationSharedService pendings;
    private PlanningPendingCommandEntity command;
    private PendingConfirmationEntity owner;

    @BeforeEach
    void setUp() {
        writer = new PlanningCommandFailureWriter();
        commands = mock(PlanningPendingCommandSharedService.class);
        pendings = mock(PendingConfirmationSharedService.class);
        ReflectionTestUtils.setField(writer, "commandSharedService", commands);
        ReflectionTestUtils.setField(writer, "pendingSharedService", pendings);
        command = new PlanningPendingCommandEntity();
        command.setId(98L);
        command.setTenantId(1L);
        command.setChatSessionId(101L);
        command.setPendingId("review-pending");
        command.setOperationId("review-operation");
        command.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        command.setExpectedPlanVersion(12);
        command.setRequestDigest("request-digest");
        owner = new PendingConfirmationEntity();
        owner.setTenantId(1L);
        owner.setChatSessionId(101L);
        owner.setPendingId(command.getPendingId());
        owner.setRevision(3L);
        owner.setStatus("applying");
        owner.setClaimToken("old-claim");
        owner.setClaimExpiresAt(new Date(System.currentTimeMillis() + 120_000L));
        owner.setDataValue("{\"operationId\":\"review-operation\",\"status\":\"applying\",\"revision\":3}");
        when(pendings.lockCurrent(1L, 101L)).thenReturn(copyOwner());
        when(commands.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
    }

    @Test
    void shouldPersistFreshFailedRowAndExpireOnlyTheOriginalClaim() {
        writer.recordFailure(command, owner,
                new BusinessException(40905, "review_fix_postcondition_failed: private session content"));

        ArgumentCaptor<PlanningPendingCommandEntity> saved = ArgumentCaptor.forClass(PlanningPendingCommandEntity.class);
        verify(commands).save(saved.capture());
        PlanningPendingCommandEntity failed = saved.getValue();
        assertNull(failed.getId());
        assertEquals("failed", failed.getStatus());
        assertEquals(command.getOperationId(), failed.getOperationId());
        assertEquals(command.getRequestDigest(), failed.getRequestDigest());
        JSONObject receipt = JSONObject.parseObject(failed.getResultJson());
        assertEquals(40905, receipt.getIntValue("errorCode"));
        assertEquals("review_fix_postcondition_failed", receipt.getString("reasonCode"));
        assertFalse(failed.getResultJson().contains("private session content"));
        assertFalse(failed.getResultJson().contains("old-claim"));
        ArgumentCaptor<PendingConfirmationEntity> expired = ArgumentCaptor.forClass(PendingConfirmationEntity.class);
        verify(pendings).compareAndSet(expired.capture(), eq(3L), eq("review-pending"), eq("applying"));
        assertEquals("expired", expired.getValue().getStatus());
        assertEquals(Long.valueOf(4L), expired.getValue().getRevision());
        assertEquals("40905", expired.getValue().getResultCode());
        assertEquals("fail", expired.getValue().getResolvedAction());
        assertNull(expired.getValue().getClaimExpiresAt());
        JSONObject payload = JSONObject.parseObject(expired.getValue().getDataValue());
        assertEquals("expired", payload.getString("status"));
        assertEquals(4L, payload.getLongValue("revision"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"succeeded", "running", "failed"})
    void shouldNeverOverwriteAnExistingOperation(String status) {
        PlanningPendingCommandEntity existing = new PlanningPendingCommandEntity();
        existing.setStatus(status);
        when(commands.getByOperationId(command.getOperationId())).thenReturn(existing);

        writer.recordFailure(command, owner, new BusinessException(40905, "review_fix_postcondition_failed"));

        verify(commands, never()).save(any(PlanningPendingCommandEntity.class));
        verifyNoPendingTransition();
    }

    @Test
    void shouldKeepAuditWithoutExpiringAReclaimedOwner() {
        PendingConfirmationEntity reclaimed = copyOwner();
        reclaimed.setRevision(4L);
        reclaimed.setClaimToken("new-claim");
        when(pendings.lockCurrent(1L, 101L)).thenReturn(reclaimed);

        writer.recordFailure(command, owner, new BusinessException(409, "review_fix_stale"));

        verify(commands).save(any(PlanningPendingCommandEntity.class));
        verifyNoPendingTransition();
    }

    @ParameterizedTest
    @ValueSource(strings = {"new-pending", "foreign-operation", "applied", "missing-revision", "malformed"})
    void shouldPreserveAuditWhenPendingCannotBeSafelyResolved(String situation) {
        PendingConfirmationEntity changed = copyOwner();
        if ("new-pending".equals(situation)) changed.setPendingId("new-pending");
        if ("foreign-operation".equals(situation)) changed.setDataValue("{\"operationId\":\"foreign\"}");
        if ("applied".equals(situation)) changed.setStatus("applied");
        if ("missing-revision".equals(situation)) changed.setRevision(null);
        if ("malformed".equals(situation)) changed.setDataValue("not-json");
        when(pendings.lockCurrent(1L, 101L)).thenReturn(changed);

        assertDoesNotThrow(() -> writer.recordFailure(command, owner, new IllegalStateException("private error")));

        verify(commands).save(any(PlanningPendingCommandEntity.class));
        verifyNoPendingTransition();
    }

    @Test
    void shouldNotExpirePendingWhenAuditInsertFails() {
        when(commands.save(any(PlanningPendingCommandEntity.class))).thenReturn(false);

        assertThrows(IllegalStateException.class,
                () -> writer.recordFailure(command, owner, new IllegalStateException("failure")));

        verifyNoPendingTransition();
    }

    @Test
    void shouldDeclareIndependentTransactionBoundary() throws Exception {
        Transactional transaction = PlanningCommandFailureWriter.class.getMethod("recordFailure",
                PlanningPendingCommandEntity.class, PendingConfirmationEntity.class, RuntimeException.class)
                .getAnnotation(Transactional.class);

        assertEquals(Propagation.REQUIRES_NEW, transaction.propagation());
    }

    private PendingConfirmationEntity copyOwner() {
        return JSONObject.parseObject(JSONObject.toJSONString(owner), PendingConfirmationEntity.class);
    }

    private void verifyNoPendingTransition() {
        verify(pendings, never()).compareAndSet(any(PendingConfirmationEntity.class), anyLong(), anyString(), anyString());
    }
}
