package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaChangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class UnifiedPlanPostconditionValidatorTest {

    private final UnifiedPlanPostconditionValidator validator =
            new UnifiedPlanPostconditionValidator();

    @Test
    void shouldVerifyPersistedRangeAndActualCounts() {
        TierQuotaGoalRequestDTO requestGoal = rangeRequest(0, 2);
        Fixture fixture = fixture(requestGoal, 1, 2, 1);

        PlanChangePostconditionReportDTO report = validator.validate(
                fixture.request, fixture.state, fixture.applyResult);

        assertTrue(report.getSatisfied());
        assertTrue(report.getTierQuotaResult().getPlanSatisfied());
        assertTrue(report.getTierQuotaResult().getPersisted());
        assertEquals(Integer.valueOf(2), report.getTierQuotaResult()
                .getEffectiveGoal().getSprint().getMaxCount());
        assertEquals(Integer.valueOf(1), report.getTierQuotaResult()
                .getActualCounts().getSprintCount());
    }

    @Test
    void shouldVerifySubmittedAndCanonicalRatioState() {
        TierQuotaGoalRequestDTO requestGoal = ratioRequest(30, 40, 30);
        Fixture fixture = fixture(requestGoal, 1, 2, 1);

        PlanChangePostconditionReportDTO report = validator.validate(
                fixture.request, fixture.state, fixture.applyResult);

        assertEquals(Integer.valueOf(30), report.getTierQuotaResult()
                .getEffectiveGoal().getSprintWeight());
        assertEquals(Integer.valueOf(3), report.getTierQuotaResult()
                .getResolution().getCanonicalWeights().getSprintWeight());
        assertEquals(Integer.valueOf(2), report.getTierQuotaResult()
                .getResolution().getResolvedCounts().getStableCount());
    }

    @Test
    void shouldFailWhenFinalTierCountExceedsPersistedMaximum() {
        Fixture fixture = fixture(rangeRequest(0, 0), 1, 2, 1);

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validate(fixture.request, fixture.state, fixture.applyResult));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
    }

    @Test
    void shouldFailWhenPersistedResolutionMetadataDiffersFromProposal() {
        Fixture fixture = fixture(rangeRequest(0, 2), 1, 2, 1);
        TierAllocationSupport.confirmedResolution(fixture.state)
                .setObjectiveDigest("different-objective-digest");

        BusinessException error = assertThrows(BusinessException.class,
                () -> validator.validate(fixture.request, fixture.state, fixture.applyResult));

        assertEquals(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE, error.getStatus());
    }

    private Fixture fixture(TierQuotaGoalRequestDTO requested,
                            int sprint,
                            int stable,
                            int protect) {
        int targetCount = sprint + stable + protect;
        PlanningStateDTO empty = new PlanningStateDTO();
        TierAllocationSupport.CompiledTierAllocation compiled =
                TierAllocationSupport.compile(empty, requested, targetCount);
        TierCountsDTO frozenCounts = new TierCountsDTO();
        frozenCounts.setSprintCount(sprint);
        frozenCounts.setStableCount(stable);
        frozenCounts.setProtectCount(protect);
        compiled.getResolution().setResolvedCounts(frozenCounts);
        compiled.getResolution().setObjectiveDigest("fixture-objective-digest");
        compiled.getResolution().setSolverVersion("ojalgo-48.4.2-m2");

        PlanningStateDTO state = stateWithTiers(sprint, stable, protect);
        TierAllocationSupport.persist(
                state, compiled.getEffectiveSourceGoal(), compiled.getResolution());
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(targetCount);

        TierQuotaChangeDTO change = new TierQuotaChangeDTO();
        change.setRequestedGoal(requested);
        change.setEffectiveGoal(compiled.getEffectiveSourceGoal());
        change.setResolution(compiled.getResolution());
        change.setStateChanged(true);
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("m2-tier-proposal");
        proposal.setProposalSource("user_goal");
        proposal.setStrategy("fill_missing_count");
        proposal.setTierQuotaChange(change);

        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(targetCount);
        userGoal.setPersistTargetCount(false);
        userGoal.setTierQuotaGoal(requested);
        FixProposalApplyReq apply = new FixProposalApplyReq();
        apply.setProposalId(proposal.getProposalId());
        apply.setProposalSource("user_goal");
        apply.setUserGoalRequest(userGoal);
        PendingPlanningCommandReq command = new PendingPlanningCommandReq();
        command.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        command.setProposalApply(apply);

        FixProposalApplyRes applyResult = new FixProposalApplyRes();
        applyResult.setStatus("applied");
        applyResult.setProposal(proposal);
        applyResult.setState(state);
        return new Fixture(command, state, applyResult);
    }

    private PlanningStateDTO stateWithTiers(int sprint, int stable, int protect) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(sprint + stable + protect);
        int index = 0;
        index = addTier(state, index, sprint, "冲");
        index = addTier(state, index, stable, "稳");
        addTier(state, index, protect, "保");
        return state;
    }

    private int addTier(PlanningStateDTO state, int index, int count, String tier) {
        for (int offset = 0; offset < count; offset++) {
            String id = "v-" + index++;
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(id);
            candidate.setTier(tier);
            state.getCandidatePoolState().getItems().add(candidate);
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId(id);
            item.setTier(tier);
            state.getOrderedPlanState().getItems().add(item);
        }
        return index;
    }

    private TierQuotaGoalRequestDTO rangeRequest(int minimum, int maximum) {
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        result.setType("count_ranges");
        result.setUpdateMode("replace");
        TierCountRangeDTO sprint = new TierCountRangeDTO();
        sprint.setMinCount(minimum);
        sprint.setMaxCount(maximum);
        result.setSprint(sprint);
        return result;
    }

    private TierQuotaGoalRequestDTO ratioRequest(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        result.setType("ratios");
        result.setUpdateMode("replace");
        result.setSprintWeight(sprint);
        result.setStableWeight(stable);
        result.setProtectWeight(protect);
        return result;
    }

    private static final class Fixture {
        private final PendingPlanningCommandReq request;
        private final PlanningStateDTO state;
        private final FixProposalApplyRes applyResult;

        private Fixture(PendingPlanningCommandReq request,
                        PlanningStateDTO state,
                        FixProposalApplyRes applyResult) {
            this.request = request;
            this.state = state;
            this.applyResult = applyResult;
        }
    }
}
