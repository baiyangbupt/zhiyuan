package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TierAllocationSupportTest {

    @Test
    void shouldPatchOnlyExplicitRangeBoundsAndKeepHistoricalBounds() {
        PlanningStateDTO state = state();
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(
                ranges(bound(8, 12), bound(16, 20), bound(18, 22)));

        TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                state, rangeRequest("patch", bound(null, 10), null, null), 45);

        assertEquals(Integer.valueOf(8), compiled.getEffectiveSourceGoal().getSprint().getMinCount());
        assertEquals(Integer.valueOf(10), compiled.getEffectiveSourceGoal().getSprint().getMaxCount());
        assertEquals(Integer.valueOf(16), compiled.getEffectiveSourceGoal().getStable().getMinCount());
        assertEquals(Integer.valueOf(20), compiled.getEffectiveSourceGoal().getStable().getMaxCount());
        assertEquals(Integer.valueOf(18), compiled.getEffectiveSourceGoal().getProtect().getMinCount());
        assertEquals(Integer.valueOf(22), compiled.getEffectiveSourceGoal().getProtect().getMaxCount());
        assertTrue(compiled.isStateChanged());
    }

    @Test
    void shouldReplaceHistoricalRangesAndLeaveUnspecifiedTiersUnbounded() {
        PlanningStateDTO state = state();
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(
                ranges(bound(8, 12), bound(16, 20), bound(18, 22)));

        TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                state, rangeRequest("replace", bound(null, 10), null, null), 45);

        assertNull(compiled.getEffectiveSourceGoal().getStable());
        assertNull(compiled.getEffectiveSourceGoal().getProtect());
        assertEquals(Integer.valueOf(0), compiled.getConstraint().getStable().getMinCount());
        assertEquals(Integer.valueOf(45), compiled.getConstraint().getStable().getMaxCount());
        assertEquals(Integer.valueOf(0), compiled.getConstraint().getProtect().getMinCount());
        assertEquals(Integer.valueOf(45), compiled.getConstraint().getProtect().getMaxCount());
    }

    @Test
    void shouldBlockRangePatchAcrossHistoricalGoalTypes() {
        PlanningStateDTO state = state();
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(exact(9, 17, 19));

        TierAllocationSupport.ContractException error = assertThrows(
                TierAllocationSupport.ContractException.class,
                () -> TierAllocationSupport.compile(
                        state, rangeRequest("patch", bound(null, 10), null, null), 45));

        assertEquals("tier_quota_update_type_conflict", error.getReasonCode());
    }

    @Test
    void shouldCanonicalizeRatioWeightsAndResolveLargestRemainder() {
        TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                state(), ratioRequest("replace", 30, 40, 30), 45);

        assertEquals(Integer.valueOf(30), compiled.getEffectiveSourceGoal().getSprintWeight());
        assertEquals(Integer.valueOf(3), compiled.getCanonicalGoal().getSprintWeight());
        assertEquals(Integer.valueOf(4), compiled.getCanonicalGoal().getStableWeight());
        assertEquals(Integer.valueOf(3), compiled.getCanonicalGoal().getProtectWeight());
        assertEquals(Integer.valueOf(14), compiled.getResolution().getResolvedCounts().getSprintCount());
        assertEquals(Integer.valueOf(18), compiled.getResolution().getResolvedCounts().getStableCount());
        assertEquals(Integer.valueOf(13), compiled.getResolution().getResolvedCounts().getProtectCount());
        assertEquals("largest_remainder", compiled.getResolution().getResolutionMethod());
        assertEquals("sprint", compiled.getResolution().getTieBreakOrder().get(0));
    }

    @Test
    void shouldResolveEqualRemaindersInCanonicalTierOrder() {
        TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                state(), ratioRequest("replace", 1, 1, 1), 2);

        assertEquals(Integer.valueOf(1), compiled.getResolution().getResolvedCounts().getSprintCount());
        assertEquals(Integer.valueOf(1), compiled.getResolution().getResolvedCounts().getStableCount());
        assertEquals(Integer.valueOf(0), compiled.getResolution().getResolvedCounts().getProtectCount());
    }

    @Test
    void shouldTreatEquivalentRatioRestatementAsNoStateChange() {
        PlanningStateDTO state = state();
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(
                ratioGoal(30, 40, 30));

        TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                state, ratioRequest("replace", 3, 4, 3), 45);

        assertFalse(compiled.isStateChanged());
        assertEquals(Integer.valueOf(30), compiled.getEffectiveSourceGoal().getSprintWeight());
        assertEquals(Integer.valueOf(3), compiled.getCanonicalGoal().getSprintWeight());
    }

    @Test
    void shouldReturnTypedErrorsForInvalidRangeAndRatioContracts() {
        assertContractError("tier_range_bound_invalid",
                rangeRequest("replace", bound(-1, 10), null, null), 45);
        assertContractError("tier_range_bound_invalid",
                rangeRequest("replace", bound(11, 10), null, null), 45);
        assertContractError("tier_range_bound_invalid",
                rangeRequest("replace", bound(null, null), null, null), 45);
        assertContractError("tier_range_min_infeasible",
                rangeRequest("replace", bound(20, null), bound(20, null), bound(10, null)), 45);
        assertContractError("tier_range_max_infeasible",
                rangeRequest("replace", bound(null, 10), bound(null, 10), bound(null, 10)), 45);
        assertContractError("tier_ratio_weight_invalid", ratioRequest("replace", 0, 0, 0), 45);
        assertContractError("tier_quota_update_mode_invalid", ratioRequest("patch", 3, 4, 3), 45);

        TierQuotaGoalRequestDTO exactPatch = exactRequest(9, 17, 19);
        exactPatch.setUpdateMode("patch");
        assertContractError("tier_quota_update_mode_invalid", exactPatch, 45);
        assertContractError("tier_exact_total_mismatch", exactRequest(9, 17, 18), 45);
    }

    @Test
    void shouldPersistEffectiveGoalAndFrozenResolution() {
        PlanningStateDTO state = state();
        TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                state, ratioRequest("replace", 30, 40, 30), 45);

        TierAllocationSupport.persist(
                state, compiled.getEffectiveSourceGoal(), compiled.getResolution());

        assertTrue(TierAllocationSupport.isPersisted(
                state, compiled.getEffectiveSourceGoal(), compiled.getResolution()));
        assertEquals(Integer.valueOf(30), TierAllocationSupport.confirmedGoal(state).getSprintWeight());
        assertEquals(Integer.valueOf(45), TierAllocationSupport.confirmedResolution(state).getTargetCount());
    }

    @Test
    void shouldReResolveConfirmedRatioWhenTargetCountChanges() {
        PlanningStateDTO state = state();
        TierAllocationSupport.CompiledTierAllocation initial = TierAllocationSupport.compile(
                state, ratioRequest("replace", 3, 4, 3), 45);
        TierAllocationSupport.persist(state, initial.getEffectiveSourceGoal(), initial.getResolution());

        TierAllocationSupport.CompiledTierAllocation resized =
                TierAllocationSupport.compileConfirmed(state, 46);

        assertTrue(resized.isStateChanged());
        assertEquals(Integer.valueOf(14), resized.getResolution().getResolvedCounts().getSprintCount());
        assertEquals(Integer.valueOf(18), resized.getResolution().getResolvedCounts().getStableCount());
        assertEquals(Integer.valueOf(14), resized.getResolution().getResolvedCounts().getProtectCount());
    }

    private void assertContractError(String reasonCode,
                                     TierQuotaGoalRequestDTO request,
                                     int targetCount) {
        TierAllocationSupport.ContractException error = assertThrows(
                TierAllocationSupport.ContractException.class,
                () -> TierAllocationSupport.compile(state(), request, targetCount));
        assertEquals(reasonCode, error.getReasonCode());
    }

    private PlanningStateDTO state() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setConstraintState(new ConstraintStateDTO());
        return state;
    }

    private TierQuotaGoalDTO exact(int sprint, int stable, int protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }

    private TierQuotaGoalRequestDTO exactRequest(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO goal = new TierQuotaGoalRequestDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }

    private TierQuotaGoalDTO ranges(TierCountRangeDTO sprint,
                                    TierCountRangeDTO stable,
                                    TierCountRangeDTO protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("count_ranges");
        goal.setSprint(sprint);
        goal.setStable(stable);
        goal.setProtect(protect);
        return goal;
    }

    private TierQuotaGoalDTO ratioGoal(int sprint, int stable, int protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("ratios");
        goal.setSprintWeight(sprint);
        goal.setStableWeight(stable);
        goal.setProtectWeight(protect);
        return goal;
    }

    private TierQuotaGoalRequestDTO rangeRequest(String updateMode,
                                                 TierCountRangeDTO sprint,
                                                 TierCountRangeDTO stable,
                                                 TierCountRangeDTO protect) {
        TierQuotaGoalRequestDTO goal = new TierQuotaGoalRequestDTO();
        goal.setType("count_ranges");
        goal.setUpdateMode(updateMode);
        goal.setSprint(sprint);
        goal.setStable(stable);
        goal.setProtect(protect);
        return goal;
    }

    private TierQuotaGoalRequestDTO ratioRequest(String updateMode,
                                                 int sprint,
                                                 int stable,
                                                 int protect) {
        TierQuotaGoalRequestDTO goal = new TierQuotaGoalRequestDTO();
        goal.setType("ratios");
        goal.setUpdateMode(updateMode);
        goal.setSprintWeight(sprint);
        goal.setStableWeight(stable);
        goal.setProtectWeight(protect);
        return goal;
    }

    private TierCountRangeDTO bound(Integer min, Integer max) {
        TierCountRangeDTO bound = new TierCountRangeDTO();
        bound.setMinCount(min);
        bound.setMaxCount(max);
        return bound;
    }
}
