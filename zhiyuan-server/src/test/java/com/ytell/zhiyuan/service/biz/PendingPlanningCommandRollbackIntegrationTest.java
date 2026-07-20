package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.ytell.zhiyuan.Application;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.RecommendationOverlayStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.ActiveProfiles;

import java.util.Date;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;

@SpringBootTest(classes = Application.class)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "RUN_M2_ROLLBACK_INTEGRATION", matches = "1|true")
class PendingPlanningCommandRollbackIntegrationTest {

    private static final long TENANT_ID = 1L;
    private static final long SESSION_ID = 941000020L;
    private static final String PENDING_ID = "m2-rollback-pending";
    private static final String OPERATION_ID = "m2-rollback-operation";
    private static final String CLAIM_TOKEN = "m2-rollback-claim";

    @Autowired
    private PendingPlanningCommandBizService commandBizService;
    @Autowired
    private PlanningStateService planningStateService;
    @Autowired
    private ChatSessionExtraDataSharedService extraDataSharedService;
    @Autowired
    private PendingConfirmationSharedService pendingSharedService;
    @Autowired
    private PlanningPendingCommandSharedService commandSharedService;
    @Autowired
    private ChatSessionSharedService chatSessionSharedService;
    @MockBean
    private UnifiedPlanPostconditionValidator postconditionValidator;

    @BeforeEach
    void cleanBefore() {
        cleanup();
    }

    @AfterEach
    void cleanAfter() {
        cleanup();
    }

    @Test
    void shouldRollbackPlanTierGoalCommandAndPendingOutcomeWhenPostconditionFails() {
        try {
            saveSession();
            saveState(initialState());
            UserGoalFixProposalReq userGoal = rangeGoal();
            FixProposalDTO proposal = readyProposal(userGoal);
            PlanningStateDTO before = planningStateService.getPlanningState(SESSION_ID);
            String beforeJson = planningStateRow().getDataValue();
            List<String> beforeSelectedIds = selectedIds(before);
            FixProposalStateDTO replayedPreview =
                    planningStateService.generateUserGoalFixProposals(SESSION_ID, userGoal);
            assertTrue(replayedPreview.getProposals().stream()
                            .anyMatch(item -> proposal.getProposalId().equals(item.getProposalId())),
                    "proposal must be reproducible immediately before command execution");
            saveApplyingPending();

            doThrow(new BusinessException(40906, "m2_postcondition_injected_failure"))
                    .when(postconditionValidator).validate(any(), any(), any());

            BusinessException error = assertThrows(BusinessException.class,
                    () -> commandBizService.execute(
                            TENANT_ID, SESSION_ID, command(proposal, userGoal, before.getVersion())));

            assertEquals(40906, error.getStatus(), error.getMessage());
            verify(postconditionValidator).validate(any(), any(), any());

            ChatSessionExtraData persistedRow = planningStateRow();
            PlanningStateDTO persisted = JSONObject.parseObject(
                    persistedRow.getDataValue(), PlanningStateDTO.class);
            assertEquals(beforeJson, persistedRow.getDataValue());
            assertEquals(before.getVersion(), persisted.getVersion());
            assertEquals(beforeSelectedIds, selectedIds(persisted));
            assertNull(TierAllocationSupport.confirmedGoal(persisted));
            assertNull(TierAllocationSupport.confirmedResolution(persisted));

            PlanningPendingCommandEntity command =
                    commandSharedService.getByOperationId(OPERATION_ID);
            assertTrue(command == null || !"succeeded".equals(command.getStatus()));
            PendingConfirmationEntity pending =
                    pendingSharedService.getCurrent(TENANT_ID, SESSION_ID);
            assertEquals("applying", pending.getStatus());
            assertFalse("applied".equals(pending.getStatus()));
        } finally {
            cleanup();
        }
    }

    private FixProposalDTO readyProposal(UserGoalFixProposalReq userGoal) {
        FixProposalStateDTO state =
                planningStateService.generateUserGoalFixProposals(SESSION_ID, userGoal);
        FixProposalDTO proposal = state.getProposals().stream()
                .filter(item -> item != null && "ready".equals(item.getStatus()))
                .findFirst().orElseThrow(() -> new AssertionError("missing ready M2 proposal"));
        assertTrue(proposal.getTierQuotaChange() != null);
        return proposal;
    }

    private PendingPlanningCommandReq command(FixProposalDTO proposal,
                                              UserGoalFixProposalReq userGoal,
                                              Integer sourceVersion) {
        FixProposalApplyReq apply = new FixProposalApplyReq();
        apply.setProposalId(proposal.getProposalId());
        apply.setProposalSource("user_goal");
        apply.setSourceVersionGuard(sourceVersion);
        apply.setCanonicalObjectiveDigest(proposal.getCanonicalObjectiveDigest());
        apply.setSolverVersion(proposal.getSolverVersion());
        apply.setSolverInputDigest(proposal.getSolverInputDigest());
        apply.setRegenerateOrderedPlan(true);
        apply.setRerunReview(true);
        apply.setUserGoalRequest(userGoal);

        PendingPlanningCommandReq command = new PendingPlanningCommandReq();
        command.setOperationId(OPERATION_ID);
        command.setPendingId(PENDING_ID);
        command.setClaimToken(CLAIM_TOKEN);
        command.setExpectedPlanVersion(sourceVersion);
        command.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        command.setProposalApply(apply);
        return command;
    }

    private UserGoalFixProposalReq rangeGoal() {
        TierCountRangeDTO sprint = new TierCountRangeDTO();
        sprint.setMaxCount(2);
        TierQuotaGoalRequestDTO tierGoal = new TierQuotaGoalRequestDTO();
        tierGoal.setType("count_ranges");
        tierGoal.setUpdateMode("replace");
        tierGoal.setSprint(sprint);

        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(4);
        userGoal.setPersistTargetCount(false);
        userGoal.setSourceVersionGuard(9);
        userGoal.setTierQuotaGoal(tierGoal);
        return userGoal;
    }

    private PlanningStateDTO initialState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(SESSION_ID);
        state.setVersion(9);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(48);
        addCandidate(state, "m2-rb-1", "冲", 91D);
        addCandidate(state, "m2-rb-2", "冲", 90D);
        addCandidate(state, "m2-rb-3", "稳", 89D);
        addCandidate(state, "m2-rb-4", "保", 88D);
        RecommendationOverlayStateDTO.Item overlayItem = new RecommendationOverlayStateDTO.Item();
        overlayItem.setVolunteerId("m2-rb-1");
        overlayItem.setFinalScore(91D);
        state.getRecommendationOverlayState().getItems().add(overlayItem);
        state.getStaleFlags().setRecommendationOverlay(false);
        return state;
    }

    private void saveSession() {
        ChatSession session = new ChatSession();
        session.setId(SESSION_ID);
        session.setTenantId(TENANT_ID);
        session.setUserId(SESSION_ID);
        session.setBotId(1L);
        session.setSessionStatus(SessionStatus.GOING);
        assertTrue(chatSessionSharedService.save(session));
    }

    private void addCandidate(PlanningStateDTO state, String id, String tier, double score) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setPlanSchoolDataId("unit-" + id);
        candidate.setSchoolId("school-" + id);
        candidate.setSchoolName("学校" + id);
        candidate.setDisplaySchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setTier(tier);
        candidate.setFinalScore(score);
        candidate.setIntentScore(score);
        candidate.setAdmissionRatio(score);
        candidate.setRankInTier(1);
        state.getCandidatePoolState().getItems().add(candidate);

        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(id);
        item.setSchoolName(candidate.getSchoolName());
        item.setMajorName(candidate.getMajorName());
        item.setTier(tier);
        item.setPosition(state.getOrderedPlanState().getItems().size() + 1);
        item.setSource("m2_rollback_integration");
        state.getOrderedPlanState().getItems().add(item);
    }

    private void saveState(PlanningStateDTO state) {
        ChatSessionExtraData row = new ChatSessionExtraData();
        row.setChatSessionId(SESSION_ID);
        row.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        row.setDataVersion(0);
        row.setDataType(DataType.JSON_OBJECT);
        row.setDataValue(JSONObject.toJSONString(state));
        assertTrue(extraDataSharedService.save(row));
    }

    private void saveApplyingPending() {
        PendingConfirmationEntity pending = new PendingConfirmationEntity();
        pending.setTenantId(TENANT_ID);
        pending.setChatSessionId(SESSION_ID);
        pending.setPendingId(PENDING_ID);
        pending.setRevision(2L);
        pending.setKind("plan_change");
        pending.setActionFamily(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        pending.setStatus("applying");
        pending.setClaimToken(CLAIM_TOKEN);
        pending.setClaimExpiresAt(new Date(System.currentTimeMillis() + 120_000L));
        pending.setDataValue("{}");
        assertTrue(pendingSharedService.save(pending));
    }

    private ChatSessionExtraData planningStateRow() {
        ChatSessionExtraData row = extraDataSharedService.getBySessionIdAndDataKey(
                SESSION_ID, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        if (row == null) {
            throw new AssertionError("missing isolated planning state");
        }
        return row;
    }

    private List<String> selectedIds(PlanningStateDTO state) {
        return state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toList());
    }

    private void cleanup() {
        commandSharedService.remove(Wrappers.<PlanningPendingCommandEntity>lambdaQuery()
                .eq(PlanningPendingCommandEntity::getChatSessionId, SESSION_ID));
        pendingSharedService.remove(Wrappers.<PendingConfirmationEntity>lambdaQuery()
                .eq(PendingConfirmationEntity::getTenantId, TENANT_ID)
                .eq(PendingConfirmationEntity::getChatSessionId, SESSION_ID));
        extraDataSharedService.remove(Wrappers.<ChatSessionExtraData>lambdaQuery()
                .eq(ChatSessionExtraData::getChatSessionId, SESSION_ID)
                .eq(ChatSessionExtraData::getDataKey,
                        ChatSessionExtraDataConstants.PLANNING_STATE_KEY));
        chatSessionSharedService.removeById(SESSION_ID);
        assertNull(commandSharedService.getByOperationId(OPERATION_ID));
        assertNull(pendingSharedService.getCurrent(TENANT_ID, SESSION_ID));
        assertNull(extraDataSharedService.getBySessionIdAndDataKey(
                SESSION_ID, ChatSessionExtraDataConstants.PLANNING_STATE_KEY));
        assertNull(chatSessionSharedService.getById(SESSION_ID));
    }
}
