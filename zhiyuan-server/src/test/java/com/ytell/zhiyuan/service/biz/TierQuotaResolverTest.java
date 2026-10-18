package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TierQuotaResolverTest {

    @Test
    void explicitExactQuotaWinsOverSoftBand() {
        // 10/0/0 在 20/40% 软带下会被判“冲区过高”，但显式配额就是 10/0/0。
        PlanningStateDTO state = state(10, exact(10, 0, 0));
        addUnits(state, "冲", 10);

        TierQuotaResolver.ExplicitCheck check = TierQuotaResolver.evaluateExplicit(state);

        assertTrue(check.isPassed());
        assertNull(check.getReasonCode());
        assertTrue(check.getDetail().contains("配额10"));
        assertEquals(Integer.valueOf(10), TierQuotaResolver.explicitAnchor(state).getSprintCount());
    }

    @Test
    void explicitQuotaMismatchReportsProtectMissing() {
        PlanningStateDTO state = state(10, exact(5, 0, 5));
        addUnits(state, "冲", 5);

        TierQuotaResolver.ExplicitCheck check = TierQuotaResolver.evaluateExplicit(state);

        assertFalse(check.isPassed());
        assertTrue("protect_tier_missing".equals(check.getReasonCode()));
        assertTrue("risk".equals(check.getLevel()));
    }

    @Test
    void noExplicitGoalFallsBackToLegacyBand() {
        PlanningStateDTO state = state(10, null);
        addUnits(state, "冲", 10);

        assertNull(TierQuotaResolver.evaluateExplicit(state));
    }

    @Test
    void rangeQuotaChecksBounds() {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("count_ranges");
        goal.setSprint(range(8, 10));
        goal.setStable(range(0, 2));
        goal.setProtect(range(0, 2));
        PlanningStateDTO state = state(10, goal);
        addUnits(state, "冲", 9);
        addUnits(state, "稳", 1);

        TierQuotaResolver.ExplicitCheck check = TierQuotaResolver.evaluateExplicit(state);

        assertTrue(check.isPassed());
    }

    private PlanningStateDTO state(int target, TierQuotaGoalDTO goal) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(target);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(target);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(goal);
        return state;
    }

    private void addUnits(PlanningStateDTO state, String tier, int count) {
        for (int index = 0; index < count; index++) {
            OrderedUnitDTO unit = new OrderedUnitDTO();
            unit.setUnitId("u-" + tier + "-" + index);
            unit.setTier(tier);
            state.getOrderedPlanState().getUnits().add(unit);
        }
    }

    private TierQuotaGoalDTO exact(int sprint, int stable, int protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }

    private TierCountRangeDTO range(int min, int max) {
        TierCountRangeDTO range = new TierCountRangeDTO();
        range.setMinCount(min);
        range.setMaxCount(max);
        return range;
    }
}
