package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import org.junit.jupiter.api.Test;

import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairProposalStateBuilderTest {

    @Test
    void shouldExplainCannotSatisfyReasonByReviewRule() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_gap");
        check.setSummary("录取率梯度断层");
        check.setScopeKind("structure");
        check.setCategory("structure_risk");

        FixProposalDTO proposal = RepairProposalStateBuilder.buildBaseProposal(
                state, check, Collections.emptyList(), 3, null);

        assertEquals("cannot_satisfy", proposal.getStrategy());
        assertTrue(proposal.getSummary().contains("断层区间"));
        assertEquals(proposal.getSummary(), proposal.getBlockingReason());
        assertEquals(Collections.singletonList("probability_gap_candidate_insufficient"), proposal.getBlockingReasonCodes());
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals("review_check", proposal.getProposalSource());
    }

    @Test
    void shouldBuildUserGoalProposalStateWithoutReviewApplySemantics() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(12);

        FixProposalStateDTO proposalState = RepairProposalStateBuilder.newUserGoalState(state);

        assertEquals("user_goal", proposalState.getProposalSource());
        assertEquals("empty", proposalState.getStatus());
        assertEquals(Integer.valueOf(12), proposalState.getSourceVersion());
        assertEquals(Integer.valueOf(12), proposalState.getSourceVersionGuard());
        assertTrue(proposalState.getProposals().isEmpty());
    }

    @Test
    void shouldNotAttributeShortageToPolicyOrProfileWithoutFilterCounts() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(8);
        state.getCandidatePoolState().setRequiredCount(3);
        state.getProfileState().getPhysicalConstraints().getColorVision().add("色弱");
        state.getProfileState().getPhysicalConstraints().getSpecialLimits().add("专项资格");

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("count_validation");
        check.setSummary("志愿数量不足");
        check.setScopeKind("structure");
        check.setCategory("structure_risk");

        FixProposalDTO proposal = RepairProposalStateBuilder.buildBaseProposal(
                state, check, Collections.emptyList(), 4, null);
        RepairProposalStateBuilder.populateCandidateShortages(state, check, proposal);

        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("candidate_pool", proposal.getCandidateShortages().get(0).getScope());
        assertFalse("policy_or_profile_constraints".equals(proposal.getCandidateShortages().get(0).getScope()));
    }

    @Test
    void shouldRepresentCountOverLimitAsCurrentPlanIssue() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(8);
        state.getCandidatePoolState().setRequiredCount(2);
        state.getOrderedPlanState().getItems().add(new OrderedItemDTO());
        state.getOrderedPlanState().getItems().add(new OrderedItemDTO());
        state.getOrderedPlanState().getItems().add(new OrderedItemDTO());

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("count_validation");
        check.setReasonCode("count_over_limit");
        check.setSummary("当前志愿数量多于官方要求");
        check.setScopeKind("structure");
        check.setCategory("structure_risk");

        FixProposalDTO proposal = RepairProposalStateBuilder.buildBaseProposal(
                state, check, Collections.emptyList(), 4, null);
        RepairProposalStateBuilder.populateCandidateShortages(state, check, proposal);

        assertEquals("cannot_satisfy", proposal.getStrategy());
        assertEquals(Collections.singletonList("count_over_limit"), proposal.getBlockingReasonCodes());
        assertTrue(proposal.getSummary().contains("多于官方要求"));
        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("current_plan", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("count_over_limit", proposal.getCandidateShortages().get(0).getReasonCode());
        assertEquals(Integer.valueOf(2), proposal.getCandidateShortages().get(0).getRequiredCount());
        assertEquals(Integer.valueOf(3), proposal.getCandidateShortages().get(0).getCurrentCount());
        assertEquals(null, proposal.getCandidateShortages().get(0).getShortageCount());
        assertEquals(null, proposal.getCandidateShortages().get(0).getAvailableCount());
    }

    @Test
    void shouldUseConcreteBlockingReasonForObjectiveValidationShortage() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(9);

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setSummary("高收费");

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("replace_risk_items");
        proposal.setBlockingReason("替换预览会改变专业组数量，暂不允许确认应用。");
        proposal.setBlockingReasonCodes(Collections.singletonList("objective_validation_not_improved"));

        RepairProposalStateBuilder.populateCandidateShortages(state, check, proposal);

        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("objective_validation", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("objective_validation_not_improved", proposal.getCandidateShortages().get(0).getReasonCode());
        assertEquals(proposal.getBlockingReason(), proposal.getCandidateShortages().get(0).getMessage());
    }

    @Test
    void shouldSuppressActionPreviewWhenObjectiveValidationBlocked() {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStatus("blocked");
        proposal.setBlockingReasonCodes(Collections.singletonList("objective_validation_not_improved"));
        proposal.getActions().add(new FixProposalActionDTO());

        RepairProposalStateBuilder.suppressInvalidBlockedActionPreview(proposal);

        assertTrue(proposal.getActions().isEmpty());
    }
}
