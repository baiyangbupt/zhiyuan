package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UpdateScoreDetailRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanGenerateReq;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaChangeDTO;
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
    private ConversationAccessService conversationAccessService;

    @BeforeEach
    void setUp() {
        service = new PendingPlanningCommandBizService();
        commandSharedService = mock(PlanningPendingCommandSharedService.class);
        pendingSharedService = mock(PendingConfirmationSharedService.class);
        extraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        planningStateService = mock(PlanningStateService.class);
        chatSessionBizService = mock(ChatSessionBizService.class);
        conversationAccessService = mock(ConversationAccessService.class);
        ReflectionTestUtils.setField(service, "commandSharedService", commandSharedService);
        ReflectionTestUtils.setField(service, "pendingSharedService", pendingSharedService);
        ReflectionTestUtils.setField(service, "extraDataSharedService", extraDataSharedService);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(service, "chatSessionBizService", chatSessionBizService);
        ReflectionTestUtils.setField(service, "conversationAccessService", conversationAccessService);
        ReflectionTestUtils.setField(service, "postconditionValidator",
                new UnifiedPlanPostconditionValidator());
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

        assertEquals(Arrays.asList("constraint_updated", "tuition_updated", "ordered_plan_regenerated",
                "working_plan_refilled", "postcondition_verified"),
                response.getCompletedSteps());
        assertEquals(Integer.valueOf(14), response.getResultPlanVersion());
        verify(planningStateService).updateConstraintState(eq(101L), any(UpdateConstraintStateReq.class));
        verify(chatSessionBizService).updateTuitionRange(1L, 101L, 0, 20000);
    }

    /**
     * 约束把工作方案排空时必须**整条命令失败**，不能留一个被清空的方案。
     *
     * <p>真栈形态（2026-09-25）：`mustExcludeMajors=["中西医临床医学"]` 经双向子串匹配把
     * 全部门类为"医学"的候选一起排掉 → 工作方案被同步成 0 行 → 有序方案 0 单元。
     * 工作方案的清空不可逆：有序方案由它生成，此后任何重生成都从空方案出发（实测：修好
     * 匹配器后仍为 0 单元）。所以这里要的是"这次没改成"，不是"方案没了"。
     */
    @Test
    void shouldRejectConstraintCommandWhenItWouldEmptyWorkingPlan() {
        PendingPlanningCommandReq req = constraintReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(stateWithWorkingPlan(12, 3));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.generateOrderedPlan(eq(1L), eq(101L), any(OrderedPlanGenerateReq.class)))
                .thenReturn(stateWithWorkingPlan(14, 0));
        when(chatSessionBizService.updateTuitionRange(1L, 101L, 0, 20000)).thenReturn(true);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.CONSTRAINT_EMPTIES_PLAN_CODE, error.getStatus());
    }

    /** 对照：约束只是筛掉一部分、方案还剩条目时，命令照常成功。 */
    @Test
    void shouldAllowConstraintCommandWhenWorkingPlanSurvives() {
        PendingPlanningCommandReq req = constraintReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(stateWithWorkingPlan(12, 3));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.generateOrderedPlan(eq(1L), eq(101L), any(OrderedPlanGenerateReq.class)))
                .thenReturn(stateWithWorkingPlan(14, 2));
        when(chatSessionBizService.updateTuitionRange(1L, 101L, 0, 20000)).thenReturn(true);

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertEquals(Arrays.asList("constraint_updated", "tuition_updated", "ordered_plan_regenerated",
                "working_plan_refilled", "postcondition_verified"),
                response.getCompletedSteps());
    }

    @Test
    void shouldApplyPlanChangeProposalAndVerifyExactCount() {
        PendingPlanningCommandReq req = canonicalPlanChangeReq(3);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        FixProposalApplyRes applied = planChangeApplyResult(3, 16);
        applied.getState().getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(3);
        String persistedDigest = PlanningObjectiveCompiler.compileConfirmed(
                applied.getState()).getObjectiveDigest();
        req.getProposalApply().setCanonicalObjectiveDigest(persistedDigest);
        FixProposalDTO proposal = canonicalProposal(
                Arrays.asList("v-0", "v-1", "v-2"),
                Arrays.asList("v-0", "v-1", "v-2"), 3);
        proposal.setCanonicalObjectiveDigest(persistedDigest);
        applied.setProposal(proposal);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(applied);

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertFalse(response.getReplayed());
        assertEquals(Arrays.asList(
                "proposal_applied", "ordered_plan_regenerated", "review_rerun", "postcondition_verified"),
                response.getCompletedSteps());
        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(3), response.getPostconditionReport().getActualCount());
        assertEquals("volunteer", response.getPostconditionReport().getCountMode());
        assertEquals(persistedDigest, response.getPostconditionReport().getCanonicalObjectiveDigest());
        assertEquals("ojalgo-48.4.2-m1", response.getPostconditionReport().getSolverVersion());
        assertEquals("input-digest", response.getPostconditionReport().getSolverInputDigest());
        assertEquals(1, response.getPostconditionReport().getObjectiveResults().size());
        assertEquals("selection_target", response.getPostconditionReport()
                .getObjectiveResults().get(0).getObjectiveType());
        assertTrue(response.getPostconditionReport().getObjectiveResults().get(0).getSatisfied());
        verify(planningStateService).applyFixProposal(1L, 101L, req.getProposalApply());
        ArgumentCaptor<PlanningPendingCommandEntity> commandCaptor =
                ArgumentCaptor.forClass(PlanningPendingCommandEntity.class);
        verify(commandSharedService).updateById(commandCaptor.capture());
        assertTrue(commandCaptor.getValue().getResultJson().contains("postconditionReport"));
        assertFalse(commandCaptor.getValue().getResultJson().contains("candidatePoolState"));
    }

    @Test
    void shouldRejectCanonicalPostconditionWhenFrozenOrderDoesNotMatchFinalPlan() {
        PendingPlanningCommandReq req = canonicalPlanChangeReq(3);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        FixProposalApplyRes applied = planChangeApplyResult(3, 16);
        FixProposalDTO proposal = canonicalProposal(
                Arrays.asList("v-0", "v-1", "v-2"),
                Arrays.asList("v-1", "v-0", "v-2"), 3);
        applied.setProposal(proposal);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply())).thenReturn(applied);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
    }

    @Test
    void shouldRejectCanonicalPostconditionWhenPersistedObjectiveDigestDoesNotMatchProposal() {
        PendingPlanningCommandReq req = canonicalPlanChangeReq(3);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        FixProposalApplyRes applied = planChangeApplyResult(3, 16);
        applied.getState().getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(3);
        applied.setProposal(canonicalProposal(
                Arrays.asList("v-0", "v-1", "v-2"),
                Arrays.asList("v-0", "v-1", "v-2"), 3));
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply())).thenReturn(applied);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
    }

    @Test
    void shouldRejectCanonicalPostconditionWhenFrozenObjectiveResultDoesNotMatchFinalFacts() {
        PendingPlanningCommandReq req = canonicalPlanChangeReq(3);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        FixProposalApplyRes applied = planChangeApplyResult(3, 16);
        applied.getState().getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(3);
        String persistedDigest = PlanningObjectiveCompiler.compileConfirmed(
                applied.getState()).getObjectiveDigest();
        req.getProposalApply().setCanonicalObjectiveDigest(persistedDigest);
        FixProposalDTO proposal = canonicalProposal(
                Arrays.asList("v-0", "v-1", "v-2"),
                Arrays.asList("v-0", "v-1", "v-2"), 3);
        proposal.setCanonicalObjectiveDigest(persistedDigest);
        proposal.getSolverResult().getObjectiveResults().get(0).setActualCount(2);
        applied.setProposal(proposal);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply())).thenReturn(applied);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
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
    void shouldVerifyCanonicalPriorityAgainstFrozenSelectionAndObjectiveResults() {
        PendingPlanningCommandReq req = priorityPlanChangeReq("上海");
        req.getProposalApply().setSolverVersion("ojalgo-48.4.2-m1");
        req.getProposalApply().setSolverInputDigest("input-digest");
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        FixProposalApplyRes applied = priorityApplyResult("上海", true);
        String persistedDigest = PlanningObjectiveCompiler.compileConfirmed(
                applied.getState()).getObjectiveDigest();
        req.getProposalApply().setCanonicalObjectiveDigest(persistedDigest);
        FixProposalDTO proposal = canonicalPriorityProposal(persistedDigest);
        applied.setProposal(proposal);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply())).thenReturn(applied);

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(2, response.getPostconditionReport().getObjectiveResults().size());
        assertEquals("selection_target", response.getPostconditionReport()
                .getObjectiveResults().get(0).getObjectiveId());
        assertEquals("priority:0", response.getPostconditionReport()
                .getObjectiveResults().get(1).getObjectiveId());
    }

    /**
     * 40905 定案回归（2026-10-16，355→358 卡 rev15 100% 复现）：请求 `priorityRules=[]`、
     * state 里有**已持久化**优先规则（"浙江优先"）时，报告侧必须按 state 规则重建 ✓——
     * 生成侧 `PlanningObjectiveCompiler.compile`（:58-60）请求为空即回落已确认规则，
     * 冻结目标因此带 `priority:0`；报告侧以前只遍历请求 ⇒ 这条 objective 无对应报告项 ⇒
     * `frozen objective result mismatch` ⇒ 必挂 40905 ✗。修复后：执行通过、报告含该规则 ✓。
     */
    @Test
    void shouldAcceptFillProposalWhenRequestOmitsStatePersistedPriorityRule() {
        PendingPlanningCommandReq req = canonicalPlanChangeReq(2);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        FixProposalApplyRes applied = priorityApplyResult("浙江", true);
        String persistedDigest = PlanningObjectiveCompiler.compileConfirmed(
                applied.getState()).getObjectiveDigest();
        req.getProposalApply().setCanonicalObjectiveDigest(persistedDigest);
        FixProposalDTO proposal = canonicalProposal(
                Arrays.asList("v-shanghai", "v-beijing"),
                Arrays.asList("v-shanghai", "v-beijing"), 2);
        proposal.setProposalId("ugp-fill-priority-from-state");
        proposal.setCanonicalObjectiveDigest(persistedDigest);
        PlanSolverResultDTO.ObjectiveResultDTO priority = new PlanSolverResultDTO.ObjectiveResultDTO();
        priority.setObjectiveId("priority:0");
        priority.setObjectiveType("priority_within_tier");
        priority.setRequiredMin(0);
        priority.setRequiredMax(0);
        priority.setActualCount(0);
        priority.setSatisfied(true);
        proposal.getSolverResult().getObjectiveResults().add(priority);
        applied.setProposal(proposal);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply())).thenReturn(applied);

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getPriorityRuleCount());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport().getSatisfiedPriorityRuleCount());
        assertEquals("priority:0", response.getPostconditionReport()
                .getObjectiveResults().get(1).getObjectiveId());
        verify(planningStateService).applyFixProposal(1L, 101L, req.getProposalApply());
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
        req.getProposalApply().getUserGoalRequest().setTierQuotaGoal(tierQuotaRequest(1, 1, 1));
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
        assertEquals(3, response.getPostconditionReport().getObjectiveResults().stream()
                .filter(item -> "tier_exact".equals(item.getObjectiveType())).count());
    }

    @Test
    void shouldVerifyPersistedRangeAndActualCounts() {
        PendingPlanningCommandReq req = rangePlanChangeReq(2);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithTierRange(2));

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertTrue(response.getPostconditionReport().getSatisfied());
        assertTrue(response.getPostconditionReport().getTierQuotaResult().getPlanSatisfied());
        assertTrue(response.getPostconditionReport().getTierQuotaResult().getPersisted());
        assertEquals(Integer.valueOf(1), response.getPostconditionReport()
                .getTierQuotaResult().getActualCounts().getSprintCount());
        verify(commandSharedService).updateById(any(PlanningPendingCommandEntity.class));
    }

    @Test
    void shouldNotSucceedCommandWhenRangePostconditionFails() {
        PendingPlanningCommandReq req = rangePlanChangeReq(0);
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(commandSharedService.save(any(PlanningPendingCommandEntity.class))).thenReturn(true);
        when(planningStateService.applyFixProposal(1L, 101L, req.getProposalApply()))
                .thenReturn(planChangeApplyResultWithTierRange(0));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
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

    private PendingPlanningCommandReq canonicalPlanChangeReq(int targetCount) {
        PendingPlanningCommandReq req = planChangeReq(targetCount);
        req.getProposalApply().setCanonicalObjectiveDigest("objective-digest");
        req.getProposalApply().setSolverVersion("ojalgo-48.4.2-m1");
        req.getProposalApply().setSolverInputDigest("input-digest");
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

    private FixProposalDTO canonicalProposal(java.util.List<String> selected,
                                              java.util.List<String> ordered,
                                              int targetCount) {
        PlanSolverResultDTO solverResult = new PlanSolverResultDTO();
        solverResult.setStatus("ready");
        solverResult.setSelectedEntityIds(selected);
        solverResult.setOrderedEntityIds(ordered);
        solverResult.setSolverVersion("ojalgo-48.4.2-m1");
        solverResult.setInputDigest("input-digest");
        PlanSolverResultDTO.ObjectiveResultDTO objective = new PlanSolverResultDTO.ObjectiveResultDTO();
        objective.setObjectiveId("selection_target");
        objective.setObjectiveType("selection_target");
        objective.setRequiredMin(targetCount);
        objective.setRequiredMax(targetCount);
        objective.setActualCount(targetCount);
        objective.setSatisfied(true);
        solverResult.getObjectiveResults().add(objective);
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("ugp-fill");
        proposal.setProposalSource("user_goal");
        proposal.setStrategy("fill_missing_count");
        proposal.setCanonicalObjectiveDigest("objective-digest");
        proposal.setSolverVersion("ojalgo-48.4.2-m1");
        proposal.setSolverInputDigest("input-digest");
        proposal.setSolverResult(solverResult);
        return proposal;
    }

    private FixProposalDTO canonicalPriorityProposal(String objectiveDigest) {
        FixProposalDTO proposal = canonicalProposal(
                Arrays.asList("v-shanghai", "v-beijing"),
                Arrays.asList("v-shanghai", "v-beijing"), 2);
        proposal.setProposalId("ugp-priority");
        proposal.setStrategy("prioritize_within_tier");
        proposal.setCanonicalObjectiveDigest(objectiveDigest);
        proposal.getSolverResult().setStatus("no_change");
        PlanSolverResultDTO.ObjectiveResultDTO priority = new PlanSolverResultDTO.ObjectiveResultDTO();
        priority.setObjectiveId("priority:0");
        priority.setObjectiveType("priority_within_tier");
        priority.setRequiredMin(0);
        priority.setRequiredMax(0);
        priority.setActualCount(0);
        priority.setSatisfied(true);
        proposal.getSolverResult().getObjectiveResults().add(priority);
        return proposal;
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
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota);
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

    private PendingPlanningCommandReq rangePlanChangeReq(int sprintMaximum) {
        PendingPlanningCommandReq req = planChangeReq(4);
        req.getProposalApply().getUserGoalRequest().setPersistTargetCount(false);
        TierQuotaGoalRequestDTO quota = new TierQuotaGoalRequestDTO();
        quota.setType("count_ranges");
        quota.setUpdateMode("replace");
        TierCountRangeDTO sprint = new TierCountRangeDTO();
        sprint.setMinCount(0);
        sprint.setMaxCount(sprintMaximum);
        quota.setSprint(sprint);
        req.getProposalApply().getUserGoalRequest().setTierQuotaGoal(quota);
        return req;
    }

    private FixProposalApplyRes planChangeApplyResultWithTierRange(int sprintMaximum) {
        PlanningStateDTO state = state(16);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(48);
        TierQuotaGoalRequestDTO requestGoal = rangePlanChangeReq(sprintMaximum)
                .getProposalApply().getUserGoalRequest().getTierQuotaGoal();
        TierAllocationSupport.CompiledTierAllocation compiled =
                TierAllocationSupport.compile(new PlanningStateDTO(), requestGoal, 4);
        TierAllocationSupport.persist(
                state, compiled.getEffectiveSourceGoal(), compiled.getResolution());
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(4);
        String[] tiers = {"冲", "稳", "稳", "保"};
        for (int index = 0; index < tiers.length; index++) {
            CandidateItemDTO candidate = candidate("v-range-" + index, "公办");
            candidate.setTier(tiers[index]);
            state.getCandidatePoolState().getItems().add(candidate);
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId(candidate.getVolunteerId());
            item.setTier(tiers[index]);
            state.getOrderedPlanState().getItems().add(item);
        }
        TierQuotaChangeDTO change = new TierQuotaChangeDTO();
        change.setRequestedGoal(requestGoal);
        change.setEffectiveGoal(compiled.getEffectiveSourceGoal());
        change.setResolution(compiled.getResolution());
        change.setStateChanged(true);
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("ugp-fill");
        proposal.setProposalSource("user_goal");
        proposal.setStrategy("fill_missing_count");
        proposal.setTierQuotaChange(change);
        FixProposalApplyRes result = new FixProposalApplyRes();
        result.setStatus("applied");
        result.setProposal(proposal);
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

    private TierQuotaGoalRequestDTO tierQuotaRequest(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO goal = new TierQuotaGoalRequestDTO();
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

    /**
     * 补录成绩（score_update 动作族）的执行：**归属用户从会话行解析**（inner 端点没有
     * 登录态）、执行体与表单补录同一条核心、结果显式报 `applied`（网关据此把卡置为
     * "已生效"——这条路上没有 postconditionReport 可读）。
     */
    @Test
    void shouldExecuteScoreUpdateAndReportApplied() {
        PendingPlanningCommandReq req = scoreUpdateReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12), state(13));
        when(conversationAccessService.requireSessionUserId(1L, 101L)).thenReturn(7L);
        UpdateScoreDetailRes scoreRes = new UpdateScoreDetailRes();
        scoreRes.setSuccess(Boolean.TRUE);
        scoreRes.setChatSessionId(101L);
        scoreRes.setPlanningVersion(13);
        when(chatSessionBizService.updateScoreDetailForUser(1L, 101L, req.getScoreUpdate(), 7L))
                .thenReturn(scoreRes);

        PendingPlanningCommandRes response = service.execute(1L, 101L, req);

        assertEquals("applied", response.getStatus(), "网关只认这个显式状态");
        assertEquals(Integer.valueOf(13), response.getResultPlanVersion());
        assertTrue(response.getCompletedSteps().contains("score_detail_updated"));
        verify(chatSessionBizService).updateScoreDetailForUser(1L, 101L, req.getScoreUpdate(), 7L);
    }

    /**
     * 校验失败（110）**必须原样抛出**：它是"卡上显示未生效 + 原因"的唯一来源，
     * 吞掉就变成静默失败 ✗。同时命令行不许被标成 succeeded。
     */
    @Test
    void shouldPropagateScoreUpdateFailureInsteadOfSilentlySucceeding() {
        PendingPlanningCommandReq req = scoreUpdateReq();
        when(pendingSharedService.lockCurrent(1L, 101L)).thenReturn(applyingPending());
        when(planningStateService.getPlanningState(101L)).thenReturn(state(12));
        when(conversationAccessService.requireSessionUserId(1L, 101L)).thenReturn(7L);
        when(chatSessionBizService.updateScoreDetailForUser(any(), any(), any(), any()))
                .thenThrow(new BusinessException(110, "请填写各科成绩后再创建会话"));

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(110, error.getStatus());
        verify(commandSharedService, never()).updateById(any());
    }

    /** 缺 `scoreUpdate` 的请求在**执行前**就被拒（40001），不会走到写核心。 */
    @Test
    void shouldRejectScoreUpdateCommandWithoutPayload() {
        PendingPlanningCommandReq req = scoreUpdateReq();
        req.setScoreUpdate(null);

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.execute(1L, 101L, req));

        assertEquals(40001, error.getStatus());
        verify(chatSessionBizService, never()).updateScoreDetailForUser(any(), any(), any(), any());
    }

    private PendingPlanningCommandReq scoreUpdateReq() {
        PendingPlanningCommandReq req = baseReq();
        req.setOperationId("pending:p-1:update_score_detail");
        req.setCommandType(PendingPlanningCommandBizService.UPDATE_SCORE_DETAIL);
        CreateSessionReq scoreUpdate = new CreateSessionReq();
        scoreUpdate.setTotalScore(621);
        req.setScoreUpdate(scoreUpdate);
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

    private PlanningStateDTO stateWithWorkingPlan(int version, int itemCount) {
        PlanningStateDTO state = state(version);
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        for (int i = 0; i < itemCount; i++) {
            DraftItemDTO item = new DraftItemDTO();
            item.setVolunteerId("v-" + i);
            item.setSchoolName("测试大学" + i);
            draft.getItems().add(item);
        }
        state.setDraftPlanState(draft);
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
