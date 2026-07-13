package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UpdateConstraintStateReq;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class PendingPlanningCommandBizServiceTest {

    private PendingPlanningCommandBizService service;
    private PlanningPendingCommandSharedService commandSharedService;
    private PendingConfirmationSharedService pendingSharedService;
    private ChatSessionExtraDataSharedService extraDataSharedService;
    private PlanningStateService planningStateService;
    private ChatSessionBizService chatSessionBizService;

    @BeforeEach
    void setUp() {
        service = new PendingPlanningCommandBizService();
        commandSharedService = mock(PlanningPendingCommandSharedService.class);
        pendingSharedService = mock(PendingConfirmationSharedService.class);
        extraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        planningStateService = mock(PlanningStateService.class);
        chatSessionBizService = mock(ChatSessionBizService.class);
        ReflectionTestUtils.setField(service, "commandSharedService", commandSharedService);
        ReflectionTestUtils.setField(service, "pendingSharedService", pendingSharedService);
        ReflectionTestUtils.setField(service, "extraDataSharedService", extraDataSharedService);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(service, "chatSessionBizService", chatSessionBizService);
    }

    @Test
    void shouldReplaySucceededOperationWithoutCallingPlanningServices() {
        PendingPlanningCommandReq req = replaceReq();
        PendingPlanningCommandRes storedResult = result(req, 12, 15);
        PlanningPendingCommandEntity existing = commandEntity(req);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(storedResult));
        when(commandSharedService.getByOperationId(req.getOperationId())).thenReturn(existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getReplayed());
        assertEquals(Integer.valueOf(15), response.getResultPlanVersion());
        verify(planningStateService, never()).removeOrderedUnits(any(), any());
    }

    @Test
    void shouldReplaySucceededOperationAfterLeaseOwnerChanged() {
        PendingPlanningCommandReq original = replaceReq();
        PlanningPendingCommandEntity existing = commandEntity(original);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(result(original, 12, 15)));
        PendingPlanningCommandReq reclaimed = replaceReq();
        reclaimed.setClaimToken("claim-2");
        PendingConfirmationEntity pending = applyingPending();
        pending.setClaimToken("claim-2");
        when(commandSharedService.getByOperationId(reclaimed.getOperationId())).thenReturn(existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(pending);

        PendingPlanningCommandRes response = service.execute(1L, 101L, reclaimed);

        assertTrue(response.getReplayed());
        verify(planningStateService, never()).removeOrderedUnits(any(), any());
    }

    @Test
    void shouldReplayOperationFoundAfterWaitingForPlanningLock() {
        PendingPlanningCommandReq req = replaceReq();
        PlanningPendingCommandEntity existing = commandEntity(req);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(result(req, 12, 15)));
        when(commandSharedService.getByOperationId(req.getOperationId())).thenReturn(null, existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getReplayed());
        verify(extraDataSharedService).lockBySessionIdAndDataKey(any(), any());
        verify(planningStateService, never()).getPlanningState(any());
        verify(commandSharedService, never()).save(any());
    }

    @Test
    void shouldRejectPlanVersionConflictBeforeMutation() {
        PendingPlanningCommandReq req = replaceReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(13));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.PLAN_VERSION_CONFLICT_CODE, error.getStatus());
        verify(planningStateService, never()).removeOrderedUnits(any(), any());
        verify(commandSharedService, never()).save(any());
    }

    @Test
    void shouldRejectPendingClaimOwnerMismatch() {
        PendingPlanningCommandReq req = replaceReq();
        PendingConfirmationEntity pending = applyingPending();
        pending.setClaimToken("another-owner");
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(pending);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingConfirmationBizService.PENDING_MISMATCH_CODE, error.getStatus());
        verify(extraDataSharedService, never()).lockBySessionIdAndDataKey(any(), any());
    }

    @Test
    void shouldRejectExpiredPendingClaimOwner() {
        PendingPlanningCommandReq req = replaceReq();
        PendingConfirmationEntity pending = applyingPending();
        pending.setClaimExpiresAt(new Date(System.currentTimeMillis() - 1000L));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(pending);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingConfirmationBizService.PENDING_MISMATCH_CODE, error.getStatus());
        verify(extraDataSharedService, never()).lockBySessionIdAndDataKey(any(), any());
    }

    @Test
    void shouldRejectOperationReplayWithDifferentPayload() {
        PendingPlanningCommandReq original = replaceReq();
        PlanningPendingCommandEntity existing = commandEntity(original);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(result(original, 12, 15)));
        PendingPlanningCommandReq changed = replaceReq();
        changed.setVolunteerIds(Arrays.asList("v-different"));
        when(commandSharedService.getByOperationId(changed.getOperationId())).thenReturn(existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, changed));

        assertEquals(PendingPlanningCommandBizService.COMMAND_CONFLICT_CODE, error.getStatus());
    }

    @Test
    void shouldExecuteReplaceAsOneOrderedCommand() {
        PendingPlanningCommandReq req = replaceReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.generateOrderedPlan(eq(1L), eq(101L), any(OrderedPlanGenerateReq.class)))
                .thenReturn(state(15));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertFalse(response.getReplayed());
        assertEquals(Arrays.asList(
                "ordered_units_removed", "working_plan_items_selected", "ordered_plan_regenerated"),
                response.getCompletedSteps());
        assertEquals(Integer.valueOf(15), response.getResultPlanVersion());
        InOrder order = inOrder(planningStateService);
        order.verify(planningStateService).removeOrderedUnits(eq(101L), any());
        order.verify(planningStateService).selectWorkingPlanItems(eq(101L), any());
        order.verify(planningStateService).generateOrderedPlan(eq(1L), eq(101L), any());
        ArgumentCaptor<PlanningPendingCommandEntity> commandCaptor =
                ArgumentCaptor.forClass(PlanningPendingCommandEntity.class);
        verify(commandSharedService).updateById(commandCaptor.capture());
        assertFalse(commandCaptor.getValue().getResultJson().contains("candidatePoolState"));
    }

    @Test
    void shouldExecuteAddAsOneOrderedCommand() {
        PendingPlanningCommandReq req = addReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.generateOrderedPlan(eq(1L), eq(101L), any(OrderedPlanGenerateReq.class)))
                .thenReturn(state(14));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertEquals(Arrays.asList("working_plan_items_selected", "ordered_plan_regenerated"),
                response.getCompletedSteps());
        assertEquals(Integer.valueOf(14), response.getResultPlanVersion());
        InOrder order = inOrder(planningStateService);
        order.verify(planningStateService).selectWorkingPlanItems(eq(101L), any());
        order.verify(planningStateService).generateOrderedPlan(eq(1L), eq(101L), any());
        verify(planningStateService, never()).removeOrderedUnits(any(), any());
    }

    @Test
    void shouldExecuteConstraintAndRegenerateCommand() {
        PendingPlanningCommandReq req = constraintReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.generateOrderedPlan(eq(1L), eq(101L), any(OrderedPlanGenerateReq.class)))
                .thenReturn(state(14));
        when(chatSessionBizService.updateTuitionRange(1L, 101L, 0, 20000)).thenReturn(true);

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertEquals(Arrays.asList("constraint_updated", "tuition_updated", "ordered_plan_regenerated"),
                response.getCompletedSteps());
        assertEquals(Integer.valueOf(14), response.getResultPlanVersion());
        verify(planningStateService).updateConstraintState(eq(101L), any(UpdateConstraintStateReq.class));
        verify(chatSessionBizService).updateTuitionRange(1L, 101L, 0, 20000);
    }

    private PendingPlanningCommandReq replaceReq() {
        PendingPlanningCommandReq req = baseReq();
        req.setCommandType(PendingPlanningCommandBizService.REPLACE_UNITS);
        req.setUnitIds(Arrays.asList("u-old"));
        req.setVolunteerIds(Arrays.asList("v-new"));
        return req;
    }

    private PendingPlanningCommandReq addReq() {
        PendingPlanningCommandReq req = baseReq();
        req.setOperationId("pending:p-1:add_units");
        req.setCommandType(PendingPlanningCommandBizService.ADD_UNITS);
        req.setVolunteerIds(Arrays.asList("v-new"));
        return req;
    }

    private PendingPlanningCommandReq constraintReq() {
        PendingPlanningCommandReq req = baseReq();
        req.setCommandType(PendingPlanningCommandBizService.APPLY_CONSTRAINT_AND_REGENERATE);
        UpdateConstraintStateReq update = new UpdateConstraintStateReq();
        update.setIntentMode("constraint");
        req.setConstraintUpdate(update);
        req.setMinTuitionPerYear(0);
        req.setMaxTuitionPerYear(20000);
        req.setRegenerateOrderedPlan(true);
        return req;
    }

    private PendingPlanningCommandReq baseReq() {
        PendingPlanningCommandReq req = new PendingPlanningCommandReq();
        req.setOperationId("pending:p-1:replace_units");
        req.setPendingId("p-1");
        req.setClaimToken("claim-1");
        req.setExpectedPlanVersion(12);
        return req;
    }

    private PendingConfirmationEntity applyingPending() {
        PendingConfirmationEntity pending = new PendingConfirmationEntity();
        pending.setTenantId(1L);
        pending.setChatSessionId(101L);
        pending.setPendingId("p-1");
        pending.setStatus("applying");
        pending.setClaimToken("claim-1");
        pending.setClaimExpiresAt(new Date(System.currentTimeMillis() + 300000L));
        return pending;
    }

    private PlanningStateDTO state(int version) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(101L);
        state.setVersion(version);
        return state;
    }

    private PendingPlanningCommandRes result(PendingPlanningCommandReq req, int source, int target) {
        PendingPlanningCommandRes result = new PendingPlanningCommandRes();
        result.setOperationId(req.getOperationId());
        result.setPendingId(req.getPendingId());
        result.setCommandType(req.getCommandType());
        result.setSourcePlanVersion(source);
        result.setResultPlanVersion(target);
        result.setPlanningState(state(target));
        result.setReplayed(false);
        return result;
    }

    private PlanningPendingCommandEntity commandEntity(PendingPlanningCommandReq req) {
        PlanningPendingCommandEntity entity = new PlanningPendingCommandEntity();
        entity.setTenantId(1L);
        entity.setChatSessionId(101L);
        entity.setPendingId(req.getPendingId());
        entity.setOperationId(req.getOperationId());
        entity.setCommandType(req.getCommandType());
        entity.setExpectedPlanVersion(req.getExpectedPlanVersion());
        entity.setRequestDigest(ReflectionTestUtils.invokeMethod(service, "requestDigest", req));
        return entity;
    }
}
