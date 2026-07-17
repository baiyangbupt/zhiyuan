package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.RepairReportDTO;
import com.ytell.zhiyuan.model.dto.planning.UpdateConstraintStateReq;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
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
    void shouldReplaySucceededPlanChangeWithPostconditionReport() {
        PendingPlanningCommandReq req = planChangeReq(3);
        PendingPlanningCommandRes storedResult = result(req, 12, 16);
        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setGoalType("fill_to_count");
        report.setCountMode("volunteer");
        report.setTargetCount(3);
        report.setActualCount(3);
        report.setSatisfied(true);
        storedResult.setPostconditionReport(report);
        PlanningPendingCommandEntity existing = commandEntity(req);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(storedResult));
        when(commandSharedService.getByOperationId(req.getOperationId())).thenReturn(existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getReplayed());
        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(3), response.getPostconditionReport().getActualCount());
        verify(planningStateService, never()).applyFixProposal(any(), any(), any());
    }

    @Test
    void shouldRejectPlanChangeReplayWhenTargetCountChanges() {
        PendingPlanningCommandReq original = planChangeReq(3);
        PlanningPendingCommandEntity existing = commandEntity(original);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(result(original, 12, 16)));
        PendingPlanningCommandReq changed = planChangeReq(4);
        when(commandSharedService.getByOperationId(changed.getOperationId())).thenReturn(existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, changed));

        assertEquals(PendingPlanningCommandBizService.COMMAND_CONFLICT_CODE, error.getStatus());
        verify(planningStateService, never()).applyFixProposal(any(), any(), any());
    }

    @Test
    void shouldRejectPlanChangeReplayWhenTargetPersistenceModeChanges() {
        PendingPlanningCommandReq original = planChangeReq(3);
        PlanningPendingCommandEntity existing = commandEntity(original);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(result(original, 12, 16)));
        PendingPlanningCommandReq changed = planChangeReq(3);
        changed.getProposalApply().getUserGoalRequest().setPersistTargetCount(false);
        when(commandSharedService.getByOperationId(changed.getOperationId())).thenReturn(existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, changed));

        assertEquals(PendingPlanningCommandBizService.COMMAND_CONFLICT_CODE, error.getStatus());
        verify(planningStateService, never()).applyFixProposal(any(), any(), any());
    }

    @Test
    void shouldRejectPlanChangeReplayWhenProjectedRequirementsChange() {
        PendingPlanningCommandReq original = planChangeReq(3);
        original.getProposalApply().getUserGoalRequest().getRequirements()
                .add(requirement("exclude", "school", "school_nature", "民办"));
        PlanningPendingCommandEntity existing = commandEntity(original);
        existing.setStatus("succeeded");
        existing.setResultJson(JSONObject.toJSONString(result(original, 12, 16)));
        PendingPlanningCommandReq changed = planChangeReq(3);
        changed.getProposalApply().getUserGoalRequest().getRequirements()
                .add(requirement("exclude", "school", "school_nature", "中外合作"));
        when(commandSharedService.getByOperationId(changed.getOperationId())).thenReturn(existing);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, changed));

        assertEquals(PendingPlanningCommandBizService.COMMAND_CONFLICT_CODE, error.getStatus());
        verify(planningStateService, never()).applyFixProposal(any(), any(), any());
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

    @Test
    void shouldApplyPlanChangeProposalAndVerifyExactCount() {
        PendingPlanningCommandReq req = planChangeReq(3);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResult(3, 16));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertFalse(response.getReplayed());
        assertEquals(Arrays.asList(
                "proposal_applied", "ordered_plan_regenerated", "review_rerun", "postcondition_verified"),
                response.getCompletedSteps());
        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(3), response.getPostconditionReport().getActualCount());
        assertEquals("volunteer", response.getPostconditionReport().getCountMode());
        verify(planningStateService).applyFixProposal(1L, 101L, req.getProposalApply());
        ArgumentCaptor<PlanningPendingCommandEntity> commandCaptor =
                ArgumentCaptor.forClass(PlanningPendingCommandEntity.class);
        verify(commandSharedService).updateById(commandCaptor.capture());
        assertTrue(commandCaptor.getValue().getResultJson().contains("postconditionReport"));
        assertFalse(commandCaptor.getValue().getResultJson().contains("candidatePoolState"));
    }

    @Test
    void shouldApplyReviewFixProposalAndVerifyPostValidation() {
        PendingPlanningCommandReq req = reviewFixPlanChangeReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(reviewFixApplyResult(true));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals("review_check", response.getPostconditionReport().getProposalSource());
        assertEquals("fp-group-safety", response.getPostconditionReport().getProposalId());
        assertEquals("adjust_major_group_inner_safety",
                response.getPostconditionReport().getProposalStrategy());
        assertEquals(Arrays.asList("group_inner_safety_guard"),
                response.getPostconditionReport().getSourceReviewIssueCodes());
        assertEquals(Integer.valueOf(3), response.getPostconditionReport().getAddedVolunteerCount());
    }

    @Test
    void shouldRejectReviewFixProposalWhenPostValidationFails() {
        PendingPlanningCommandReq req = reviewFixPlanChangeReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(reviewFixApplyResult(false));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
    }

    @Test
    void shouldRejectReviewFixProposalContainingUserGoalRequest() {
        PendingPlanningCommandReq req = reviewFixPlanChangeReq();
        req.getProposalApply().setUserGoalRequest(new UserGoalFixProposalReq());

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(40001, error.getStatus());
        verify(pendingSharedService, never()).lockCurrent(any(), any());
    }

    @Test
    void shouldRejectReviewFixProposalWhoseSourceVersionDoesNotMatchCommand() {
        PendingPlanningCommandReq req = reviewFixPlanChangeReq();
        req.getProposalApply().setSourceVersionGuard(11);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(40001, error.getStatus());
        verify(pendingSharedService, never()).lockCurrent(any(), any());
    }

    @Test
    void shouldApplyPriorityProposalAndVerifyPersistedWithinTierOrder() {
        PendingPlanningCommandReq req = priorityPlanChangeReq("上海");
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(priorityApplyResult("上海", true));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(null, response.getPostconditionReport().getTargetCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getPriorityRuleCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getSatisfiedPriorityRuleCount());
        assertEquals(Integer.valueOf(1),
                response.getPostconditionReport().getPriorityRuleResults().get(0).getMatchedCount());
        assertEquals(Integer.valueOf(0),
                response.getPostconditionReport().getPriorityRuleResults().get(0).getInversionCount());
        assertTrue(response.getPostconditionReport().getPriorityRuleResults().get(0).getPersisted());
    }

    @Test
    void shouldAcceptFillProposalWithPriorityRuleAndVerifyBothObjectives() {
        PendingPlanningCommandReq req = planChangeReq(2);
        req.getProposalApply().getUserGoalRequest().getPriorityRules().add(priorityRule("上海"));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(priorityApplyResult("上海", true));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(2), response.getPostconditionReport().getActualCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getPriorityRuleCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getSatisfiedPriorityRuleCount());
    }

    @Test
    void shouldRejectPriorityPostconditionWhenRuleWasNotPersisted() {
        PendingPlanningCommandReq req = priorityPlanChangeReq("上海");
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(priorityApplyResult("上海", false));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any(PlanningPendingCommandEntity.class));
    }

    @Test
    void shouldVerifyProjectedRequirementInPlanAndPersistedConstraint() {
        PendingPlanningCommandReq req = planChangeReq(2);
        req.getProposalApply().getUserGoalRequest().getRequirements()
                .add(requirement("exclude", "school", "school_nature", "民办"));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithExcludedNature(false));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getRequirementCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getSatisfiedRequirementCount());
        assertTrue(response.getPostconditionReport().getRequirementResults().get(0).getPlanSatisfied());
        assertTrue(response.getPostconditionReport().getRequirementResults().get(0).getPersisted());
    }

    @Test
    void shouldFailProjectedRequirementPostconditionWhenExcludedItemRemains() {
        PendingPlanningCommandReq req = planChangeReq(2);
        req.getProposalApply().getUserGoalRequest().getRequirements()
                .add(requirement("exclude", "school", "school_nature", "民办"));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithExcludedNature(true));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
    }

    @Test
    void shouldVerifyIncludeCoverageInPlanAndPersistedObjective() {
        PendingPlanningCommandReq req = planChangeReq(2);
        req.getProposalApply().getUserGoalRequest().getRequirements()
                .add(requirement("include", "major", "major", "法学"));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithIncludedMajor(true, true));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getRequirementCount());
        assertTrue(response.getPostconditionReport().getRequirementResults().get(0).getPlanSatisfied());
        assertTrue(response.getPostconditionReport().getRequirementResults().get(0).getPersisted());
    }

    @Test
    void shouldVerifyPreservedCountWithoutRequiringPlanningTargetOverwrite() {
        PendingPlanningCommandReq req = planChangeReq(2);
        req.getProposalApply().getUserGoalRequest().setPersistTargetCount(false);
        req.getProposalApply().getUserGoalRequest().getRequirements()
                .add(requirement("include", "major", "major", "法学"));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        FixProposalApplyRes applied = planChangeApplyResultWithIncludedMajor(true, true);
        applied.getState().getCandidatePoolState().setRequiredCount(48);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply())).thenReturn(applied);

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(2), response.getPostconditionReport().getActualCount());
        assertEquals(Integer.valueOf(2), response.getPostconditionReport().getTargetCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getSatisfiedRequirementCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport()
                .getRequirementResults().get(0).getMinCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport()
                .getRequirementResults().get(0).getMatchedCount());
    }

    @Test
    void shouldVerifyAdmissionTierMinimumAndPersistedObjective() {
        PendingPlanningCommandReq req = planChangeReq(2);
        req.getProposalApply().getUserGoalRequest().setPersistTargetCount(false);
        UserGoalFixProposalReq.RequirementDTO minimum = requirement(
                "include", "admission", "tier", "保");
        minimum.setMinCount(2);
        req.getProposalApply().getUserGoalRequest().getRequirements().add(minimum);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithTierMinimum());

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(2), response.getPostconditionReport().getActualCount());
        assertEquals(Integer.valueOf(2), response.getPostconditionReport()
                .getRequirementResults().get(0).getMinCount());
        assertEquals(Integer.valueOf(2), response.getPostconditionReport()
                .getRequirementResults().get(0).getMatchedCount());
        assertTrue(response.getPostconditionReport().getRequirementResults().get(0).getPersisted());
    }

    @Test
    void shouldVerifyExactTierQuotaAndPersistedObjective() {
        PendingPlanningCommandReq req = planChangeReq(3);
        req.getProposalApply().getUserGoalRequest().setPersistTargetCount(false);
        req.getProposalApply().getUserGoalRequest().setTierQuotaGoal(tierQuota(1, 1, 1));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithTierQuota());

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        PlanChangePostconditionReportDTO.TierQuotaResultDTO quotaResult =
                response.getPostconditionReport().getTierQuotaResult();
        assertTrue(quotaResult.getSatisfied());
        assertTrue(quotaResult.getPersisted());
        assertEquals(Integer.valueOf(1), quotaResult.getActualSprintCount());
        assertEquals(Integer.valueOf(1), quotaResult.getActualStableCount());
        assertEquals(Integer.valueOf(1), quotaResult.getActualProtectCount());
    }

    @Test
    void shouldCountMajorGroupCoverageByUnitInsteadOfMajorDetail() {
        PendingPlanningCommandReq req = planChangeReq(3);
        req.getProposalApply().getUserGoalRequest().setPersistTargetCount(false);
        UserGoalFixProposalReq.RequirementDTO coverage = requirement(
                "include", "region", "province", "山东");
        coverage.setMinCount(3);
        req.getProposalApply().getUserGoalRequest().getRequirements().add(coverage);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(majorGroupCoverageApplyResult());

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(3), response.getPostconditionReport().getActualCount());
        assertEquals(Integer.valueOf(3), response.getPostconditionReport()
                .getRequirementResults().get(0).getMinCount());
        assertEquals(Integer.valueOf(3), response.getPostconditionReport()
                .getRequirementResults().get(0).getMatchedCount());
    }

    @Test
    void shouldFailIncludePostconditionWhenCoverageObjectiveWasNotPersisted() {
        PendingPlanningCommandReq req = planChangeReq(2);
        req.getProposalApply().getUserGoalRequest().getRequirements()
                .add(requirement("include", "major", "major", "法学"));
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithIncludedMajor(true, false));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
    }

    @Test
    void shouldFailPlanChangeCommandWhenExactCountPostconditionIsNotMet() {
        PendingPlanningCommandReq req = planChangeReq(3);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResult(2, 16));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
    }

    @Test
    void shouldRejectPlanChangeRequestWhoseSourceVersionDoesNotMatchCommand() {
        PendingPlanningCommandReq req = planChangeReq(3);
        req.getProposalApply().getUserGoalRequest().setSourceVersionGuard(11);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(40001, error.getStatus());
        verify(pendingSharedService, never()).lockCurrent(any(), any());
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

    private PendingPlanningCommandReq planChangeReq(int targetCount) {
        PendingPlanningCommandReq req = baseReq();
        req.setOperationId("pending:p-1:apply_plan_change_proposal");
        req.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(targetCount);
        userGoal.setSourceVersionGuard(12);
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId("ugp-fill");
        applyReq.setProposalSource("user_goal");
        applyReq.setSourceVersionGuard(12);
        applyReq.setRegenerateOrderedPlan(true);
        applyReq.setRerunReview(true);
        applyReq.setUserGoalRequest(userGoal);
        req.setProposalApply(applyReq);
        return req;
    }

    private PendingPlanningCommandReq reviewFixPlanChangeReq() {
        PendingPlanningCommandReq req = baseReq();
        req.setOperationId("pending:p-1:apply_plan_change_proposal");
        req.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId("fp-group-safety");
        applyReq.setProposalSource("review_check");
        applyReq.setSourceVersionGuard(12);
        applyReq.setRegenerateOrderedPlan(true);
        applyReq.setRerunReview(true);
        req.setProposalApply(applyReq);
        return req;
    }

    private PendingPlanningCommandReq priorityPlanChangeReq(String province) {
        PendingPlanningCommandReq req = baseReq();
        req.setOperationId("pending:p-1:apply_plan_change_proposal");
        req.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("prioritize_within_tier");
        userGoal.setSourceVersionGuard(12);
        userGoal.getPriorityRules().add(priorityRule(province));
        FixProposalApplyReq applyReq = new FixProposalApplyReq();
        applyReq.setProposalId("ugp-priority");
        applyReq.setProposalSource("user_goal");
        applyReq.setSourceVersionGuard(12);
        applyReq.setRegenerateOrderedPlan(true);
        applyReq.setRerunReview(true);
        applyReq.setUserGoalRequest(userGoal);
        req.setProposalApply(applyReq);
        return req;
    }

    private FixProposalApplyRes planChangeApplyResult(int actualCount, int version) {
        PlanningStateDTO state = state(version);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(3);
        for (int index = 0; index < actualCount; index++) {
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId("v-" + index);
            state.getOrderedPlanState().getItems().add(item);
        }
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setState(state);
        return result;
    }

    private FixProposalApplyRes reviewFixApplyResult(boolean postValidationPassed) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("fp-group-safety");
        proposal.setProposalSource("review_check");
        proposal.setStrategy("adjust_major_group_inner_safety");
        proposal.setSourceCheckCodes(Arrays.asList("group_inner_safety_guard"));
        RepairReportDTO repairReport = new RepairReportDTO();
        repairReport.setProposalId(proposal.getProposalId());
        repairReport.setStrategy(proposal.getStrategy());
        repairReport.setSourceCheckCodes(proposal.getSourceCheckCodes());
        repairReport.setPostValidationPassed(postValidationPassed);
        repairReport.setAppliedActionCount(3);
        repairReport.setAffectedUnitCount(3);
        repairReport.setAddedVolunteerCount(3);
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setProposal(proposal);
        result.setRepairReport(repairReport);
        result.setState(state(16));
        return result;
    }

    private FixProposalApplyRes planChangeApplyResultWithExcludedNature(boolean keepPrivate) {
        PlanningStateDTO state = state(16);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getConstraintState().getHardConstraints().getMustExcludeSchools().add("院校性质:民办");
        CandidateItemDTO publicOne = candidate("v-public-1", "公办");
        CandidateItemDTO second = candidate("v-second", keepPrivate ? "民办" : "公办");
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(publicOne, second));
        OrderedItemDTO firstItem = new OrderedItemDTO();
        firstItem.setVolunteerId(publicOne.getVolunteerId());
        OrderedItemDTO secondItem = new OrderedItemDTO();
        secondItem.setVolunteerId(second.getVolunteerId());
        state.getOrderedPlanState().getItems().addAll(Arrays.asList(firstItem, secondItem));
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setState(state);
        return result;
    }

    private FixProposalApplyRes planChangeApplyResultWithIncludedMajor(boolean includeLaw,
                                                                       boolean persistObjective) {
        PlanningStateDTO state = state(16);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        CandidateItemDTO first = candidate("v-1", "公办");
        first.setMajorName(includeLaw ? "法学" : "数学");
        CandidateItemDTO second = candidate("v-2", "公办");
        second.setMajorName("金融学");
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(first, second));
        OrderedItemDTO firstItem = new OrderedItemDTO();
        firstItem.setVolunteerId(first.getVolunteerId());
        OrderedItemDTO secondItem = new OrderedItemDTO();
        secondItem.setVolunteerId(second.getVolunteerId());
        state.getOrderedPlanState().getItems().addAll(Arrays.asList(firstItem, secondItem));
        if (persistObjective) {
            com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO objective =
                    new com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO();
            objective.setDomain("major");
            objective.setKey("major");
            objective.setValues(Arrays.asList("法学"));
            objective.setMinCount(1);
            state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements().add(objective);
        }
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setState(state);
        return result;
    }

    private FixProposalApplyRes planChangeApplyResultWithTierMinimum() {
        PlanningStateDTO state = state(16);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(48);
        for (int index = 1; index <= 2; index++) {
            CandidateItemDTO candidate = candidate("v-protect-" + index, "公办");
            candidate.setTier(index == 1 ? "保底" : "protect");
            state.getCandidatePoolState().getItems().add(candidate);
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId(candidate.getVolunteerId());
            item.setTier("保");
            state.getOrderedPlanState().getItems().add(item);
        }
        com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO objective =
                new com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO();
        objective.setDomain("admission");
        objective.setKey("tier");
        objective.setValues(Arrays.asList("保"));
        objective.setMinCount(2);
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements().add(objective);
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setState(state);
        return result;
    }

    private FixProposalApplyRes planChangeApplyResultWithTierQuota() {
        PlanningStateDTO state = state(16);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(48);
        TierQuotaGoalDTO quota = tierQuota(1, 1, 1);
        TierQuotaSupport.persist(state, quota);
        String[] tiers = {"冲刺", "safe", "保底"};
        for (int index = 0; index < tiers.length; index++) {
            CandidateItemDTO candidate = candidate("v-tier-" + index, "公办");
            candidate.setTier(tiers[index]);
            state.getCandidatePoolState().getItems().add(candidate);
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId(candidate.getVolunteerId());
            item.setTier(tiers[index]);
            state.getOrderedPlanState().getItems().add(item);
        }
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setState(state);
        return result;
    }

    private TierQuotaGoalDTO tierQuota(int sprint, int stable, int protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }

    private FixProposalApplyRes priorityApplyResult(String province, boolean persistRule) {
        PlanningStateDTO state = state(16);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(2);
        CandidateItemDTO shanghai = candidate("v-shanghai", "公办");
        shanghai.setProvinceName(province);
        CandidateItemDTO beijing = candidate("v-beijing", "公办");
        beijing.setProvinceName("北京");
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(shanghai, beijing));
        OrderedItemDTO first = new OrderedItemDTO();
        first.setVolunteerId(shanghai.getVolunteerId());
        first.setTier("稳");
        OrderedItemDTO second = new OrderedItemDTO();
        second.setVolunteerId(beijing.getVolunteerId());
        second.setTier("稳");
        state.getOrderedPlanState().getItems().addAll(Arrays.asList(first, second));
        if (persistRule) {
            state.getConstraintState().getHardPlanningObjectives().getPriorityRules()
                    .add(priorityRule(province));
        }
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setState(state);
        return result;
    }

    private FixProposalApplyRes majorGroupCoverageApplyResult() {
        PlanningStateDTO state = state(16);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(48);
        for (int unitIndex = 1; unitIndex <= 3; unitIndex++) {
            OrderedUnitDTO unit = new OrderedUnitDTO();
            unit.setUnitId("u-" + unitIndex);
            unit.setProvinceName("山东");
            for (int majorIndex = 1; majorIndex <= 2; majorIndex++) {
                String volunteerId = "u-" + unitIndex + "-v-" + majorIndex;
                CandidateItemDTO candidate = candidate(volunteerId, "公办");
                candidate.setPlanSchoolDataId(unit.getUnitId());
                candidate.setProvinceName("山东");
                state.getCandidatePoolState().getItems().add(candidate);
                PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
                major.setVolunteerId(volunteerId);
                major.setMajorName("专业" + majorIndex);
                unit.getMajorItems().add(major);
            }
            state.getOrderedPlanState().getUnits().add(unit);
        }
        com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO objective =
                new com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO();
        objective.setDomain("region");
        objective.setKey("province");
        objective.setValues(Arrays.asList("山东"));
        objective.setMinCount(3);
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements().add(objective);
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setState(state);
        return result;
    }

    private PriorityRuleDTO priorityRule(String province) {
        PriorityRuleDTO rule = new PriorityRuleDTO();
        rule.setDomain("region");
        rule.setKey("province");
        rule.setValues(Arrays.asList(province));
        rule.setOrderingTarget("rank_before");
        rule.setScope("within_tier");
        return rule;
    }

    private CandidateItemDTO candidate(String volunteerId, String schoolNature) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setSchoolName(volunteerId);
        candidate.setSchoolNature(schoolNature);
        return candidate;
    }

    private UserGoalFixProposalReq.RequirementDTO requirement(String kind,
                                                              String domain,
                                                              String key,
                                                              String value) {
        UserGoalFixProposalReq.RequirementDTO requirement = new UserGoalFixProposalReq.RequirementDTO();
        requirement.setKind(kind);
        requirement.setDomain(domain);
        requirement.setKey(key);
        requirement.setValues(Arrays.asList(value));
        return requirement;
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
