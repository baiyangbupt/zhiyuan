package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.model.vo.LastProposalVo;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.when;

class ChatSessionBizServiceLastProposalReceiptTest {

    private static final Long TENANT = 1L;
    private static final Long SESSION = 42L;
    private static final String PENDING = "pending-1";
    private static final String OPERATION = "operation-1";
    private static final String ACTION = "move_units";

    private ChatSessionBizService service;
    private PlanningPendingCommandSharedService commands;
    private PendingConfirmationBizService pendings;
    private PendingConfirmationRes pending;

    @BeforeEach
    void setUp() {
        service = new ChatSessionBizService();
        commands = Mockito.mock(PlanningPendingCommandSharedService.class);
        pendings = Mockito.mock(PendingConfirmationBizService.class);
        ReflectionTestUtils.setField(service, "planningPendingCommandSharedService", commands);
        ReflectionTestUtils.setField(service, "pendingConfirmationBizService", pendings);
        pending = new PendingConfirmationRes();
        pending.setPendingId(PENDING);
        pending.setChatSessionId(SESSION);
        pending.setStatus("applied");
        pending.setActionFamily(ACTION);
        pending.setKind("plan_action");
        Map<String, Object> data = new LinkedHashMap<String, Object>();
        data.put("operationId", OPERATION);
        data.put("commandType", ACTION);
        data.put("sourceVersion", 5);
        pending.setDataValue(data);
        when(pendings.getCurrent(TENANT, SESSION)).thenReturn(pending);
    }

    @Test
    void appliedProposalLoadsOnlyTheMatchingSucceededExecutionReceipt() {
        PendingPlanningCommandRes executed = executedReceipt();
        PlanningPendingCommandEntity command = command(executed);
        when(commands.getSucceededForPendingOperation(TENANT, SESSION, PENDING, OPERATION, ACTION))
                .thenReturn(command);

        LastProposalVo proposal = load();

        assertNotNull(proposal);
        assertEquals("applied", proposal.getActionStatus());
        assertEquals(PENDING, proposal.getProposalRef());
        assertNotNull(proposal.getReceipt());
        assertEquals(OPERATION, proposal.getReceipt().getOperationId());
        assertEquals(ACTION, proposal.getReceipt().getActionType());
        assertEquals("unit", proposal.getReceipt().getCountMode());
        assertEquals(Integer.valueOf(20), proposal.getReceipt().getBefore());
        assertEquals(Integer.valueOf(20), proposal.getReceipt().getAfter());
        assertEquals(Integer.valueOf(0), proposal.getReceipt().getAddedCount());
        assertEquals(Integer.valueOf(0), proposal.getReceipt().getRemovedCount());
        assertEquals(Integer.valueOf(2), proposal.getReceipt().getReorderedCount());
        assertEquals(Boolean.TRUE, proposal.getReceipt().getPostconditionSatisfied());
        String publicJson = JSON.toJSONString(proposal);
        assertFalse(publicJson.contains("resultJson"));
        assertFalse(publicJson.contains("claimToken"));
        assertFalse(publicJson.contains("reviewState"));
        Mockito.verify(commands).getSucceededForPendingOperation(
                TENANT, SESSION, PENDING, OPERATION, ACTION);
    }

    @Test
    void applyingAndCancelledProposalsNeverGuessAnExecutionReceipt() {
        pending.setStatus("applying");
        assertNull(load().getReceipt());
        pending.setStatus("cancelled");
        assertNull(load().getReceipt());
        Mockito.verifyNoInteractions(commands);
    }

    @Test
    void anExecutionFromAnotherOperationOrSessionCannotBecomeThisReceipt() {
        PlanningPendingCommandEntity wrong = command(executedReceipt());
        wrong.setOperationId("other-operation");
        when(commands.getSucceededForPendingOperation(TENANT, SESSION, PENDING, OPERATION, ACTION))
                .thenReturn(wrong);
        assertNull(load().getReceipt());

        wrong.setOperationId(OPERATION);
        wrong.setChatSessionId(99L);
        assertNull(load().getReceipt());
    }

    @Test
    void corruptedOrMismatchedResultJsonDoesNotLeakIntoColdProposal() {
        PlanningPendingCommandEntity command = command(executedReceipt());
        when(commands.getSucceededForPendingOperation(TENANT, SESSION, PENDING, OPERATION, ACTION))
                .thenReturn(command);
        command.setResultJson("{broken");
        assertNull(load().getReceipt());

        PendingPlanningCommandRes wrongResult = executedReceipt();
        wrongResult.setPendingId("other-pending");
        command.setResultJson(JSON.toJSONString(wrongResult));
        assertNull(load().getReceipt());
    }

    @Test
    void missingFrozenOperationDoesNotReadAnyOtherSucceededCommand() {
        pending.getDataValue().remove("operationId");
        assertNull(load().getReceipt());
        Mockito.verifyNoInteractions(commands);
    }

    private LastProposalVo load() {
        return ReflectionTestUtils.invokeMethod(service, "buildLastProposal", TENANT, SESSION);
    }

    private PendingPlanningCommandRes executedReceipt() {
        PendingPlanningCommandRes result = new PendingPlanningCommandRes();
        result.setOperationId(OPERATION);
        result.setPendingId(PENDING);
        result.setCommandType(ACTION);
        result.setStatus("applied");
        result.setTargetCountBefore(20);
        result.setTargetCountAfter(20);
        result.setAddedVolunteerCount(0);
        result.setRemovedVolunteerCount(0);
        result.setMovedUnitIds(Arrays.asList("u1", "u2"));
        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setCountMode("unit");
        report.setSatisfied(Boolean.TRUE);
        result.setPostconditionReport(report);
        return result;
    }

    private PlanningPendingCommandEntity command(PendingPlanningCommandRes result) {
        PlanningPendingCommandEntity command = new PlanningPendingCommandEntity();
        command.setTenantId(TENANT);
        command.setChatSessionId(SESSION);
        command.setPendingId(PENDING);
        command.setOperationId(OPERATION);
        command.setCommandType(ACTION);
        command.setStatus("succeeded");
        command.setResultJson(JSON.toJSONString(result));
        return command;
    }
}
