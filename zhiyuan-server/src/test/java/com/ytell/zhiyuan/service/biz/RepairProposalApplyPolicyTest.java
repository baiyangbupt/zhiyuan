package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.function.Executable;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairProposalApplyPolicyTest {

    @Test
    void shouldRejectMissingProposalId() {
        FixProposalApplyReq req = RepairProposalApplyPolicy.safeRequest(null);

        assertBusinessException(400, "缺少修复建议ID",
                () -> RepairProposalApplyPolicy.validateRequest(req));
    }

    @Test
    void shouldRejectSourceVersionGuardMismatch() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        FixProposalApplyReq req = request("proposal_1", 6);

        assertBusinessException(409, "当前方案已变化，请重新生成修复建议",
                () -> RepairProposalApplyPolicy.validateStateVersionGuard(req, state));
    }

    @Test
    void shouldRejectMissingSourceVersionGuard() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        FixProposalApplyReq req = request("proposal_1", null);

        assertBusinessException(409, "当前方案已变化，请重新生成修复建议",
                () -> RepairProposalApplyPolicy.validateStateVersionGuard(req, state));
    }

    @Test
    void shouldRejectStaleReview() {
        PlanningStateDTO state = reviewedState();
        state.getStaleFlags().setReview(true);

        assertBusinessException(409, "当前审查结果已过期，请重新生成修复建议",
                () -> RepairProposalApplyPolicy.ensureReviewReady(state));
    }

    @Test
    void shouldRejectMissingReviewChecks() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setReviewState(new ReviewStateDTO());

        assertBusinessException(409, "当前审查结果已过期，请重新生成修复建议",
                () -> RepairProposalApplyPolicy.ensureReviewReady(state));
    }

    @Test
    void shouldRejectPreviewOnlyUnsupportedProposal() {
        FixProposalApplyReq req = request("proposal_1", 7);
        FixProposalDTO proposal = proposal("preview_only", "rebalance_tier_ratio", 7);

        assertBusinessException(400, "当前修复建议暂不支持自动应用",
                () -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
    }

    @Test
    void shouldRejectUserGoalProposalWithoutOriginalRequest() {
        FixProposalApplyReq req = request("proposal_1", 7);
        req.setProposalSource("user_goal");
        FixProposalDTO proposal = proposal("ready", "only_keep_scope", 7);
        proposal.setProposalSource("user_goal");

        assertBusinessException(400, "缺少用户目标调整请求",
                () -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
    }

    @Test
    void shouldAllowReadyUserGoalProposalWithOriginalRequest() {
        FixProposalApplyReq req = request("proposal_1", 7);
        req.setProposalSource("user_goal");
        req.setUserGoalRequest(userGoalRequest("only_keep_scope", 7));
        FixProposalDTO proposal = proposal("ready", "only_keep_scope", 7);
        proposal.setProposalSource("user_goal");

        assertDoesNotThrow(() -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
    }

    @Test
    void shouldRejectUnsupportedUserGoalStrategy() {
        FixProposalApplyReq req = request("proposal_1", 7);
        req.setProposalSource("user_goal");
        req.setUserGoalRequest(userGoalRequest("mixed_adjustment", 7));
        FixProposalDTO proposal = proposal("ready", "mixed_adjustment", 7);
        proposal.setProposalSource("user_goal");

        assertBusinessException(400, "当前调整预览暂不支持自动应用",
                () -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
    }

    @Test
    void shouldRejectNonReadyProposalBeforeStrategyCheck() {
        FixProposalApplyReq req = request("proposal_1", 7);
        FixProposalDTO proposal = proposal("blocked", "fill_missing_count", 7);

        assertBusinessException(400, "当前修复建议不可应用",
                () -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
    }

    @Test
    void shouldRejectProposalVersionMismatch() {
        FixProposalApplyReq req = request("proposal_1", 7);
        FixProposalDTO proposal = proposal("ready", "fill_missing_count", 8);

        assertBusinessException(409, "修复建议版本已变化，请重新确认",
                () -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
    }

    @Test
    void shouldRejectReadyUnsupportedStrategy() {
        FixProposalApplyReq req = request("proposal_1", 7);
        FixProposalDTO proposal = proposal("ready", "rebalance_tier_ratio", 7);

        assertBusinessException(400, "当前修复建议暂不支持自动应用",
                () -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
    }

    @Test
    void shouldRejectStructuralReplacementStrategiesUntilExplicitlyAllowlisted() {
        for (String strategy : Arrays.asList("rebalance_tier_ratio", "fill_probability_gap")) {
            FixProposalApplyReq req = request("proposal_1", 7);
            FixProposalDTO proposal = proposal("ready", strategy, 7);

            assertBusinessException(400, "当前修复建议暂不支持自动应用",
                    () -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
        }
    }

    @Test
    void shouldAllowSupportedReadyStrategies() {
        for (String strategy : Arrays.asList(
                "fill_missing_count",
                "sort_by_probability",
                "remove_risk_items",
                "replace_risk_items",
                "adjust_major_group_inner_safety")) {
            FixProposalApplyReq req = request("proposal_1", 7);
            FixProposalDTO proposal = proposal("ready", strategy, 7);

            assertTrue(RepairProposalApplyPolicy.isSupportedStrategy(strategy));
            assertDoesNotThrow(() -> RepairProposalApplyPolicy.validateProposalForApply(req, proposal));
        }
    }

    private FixProposalApplyReq request(String proposalId, Integer sourceVersionGuard) {
        FixProposalApplyReq req = new FixProposalApplyReq();
        req.setProposalId(proposalId);
        req.setSourceVersionGuard(sourceVersionGuard);
        return req;
    }

    private FixProposalDTO proposal(String status, String strategy, Integer sourceVersionGuard) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStatus(status);
        proposal.setStrategy(strategy);
        proposal.setSourceVersionGuard(sourceVersionGuard);
        return proposal;
    }

    private UserGoalFixProposalReq userGoalRequest(String goalType, Integer sourceVersionGuard) {
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType(goalType);
        req.setSourceVersionGuard(sourceVersionGuard);
        return req;
    }

    private PlanningStateDTO reviewedState() {
        PlanningStateDTO state = new PlanningStateDTO();
        ReviewStateDTO reviewState = new ReviewStateDTO();
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("count_validation");
        reviewState.getChecks().add(check);
        state.setReviewState(reviewState);
        return state;
    }

    private void assertBusinessException(int status, String message, Executable executable) {
        BusinessException ex = assertThrows(BusinessException.class, executable);
        assertEquals(status, ex.getStatus());
        assertEquals(message, ex.getMessage());
    }
}
