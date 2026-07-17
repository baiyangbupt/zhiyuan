package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class TierQuotaSupportTest {

    @Test
    void shouldValidateCompleteExactCounts() {
        assertNull(TierQuotaSupport.validate(goal(9, 17, 19), 45));
        assertTrue(TierQuotaSupport.validate(goal(9, 17, 18), 45).contains("合计必须等于"));

        TierQuotaGoalDTO partial = goal(9, 17, 19);
        partial.setProtectCount(null);
        assertTrue(TierQuotaSupport.validate(partial, 45).contains("同时给出"));

        TierQuotaGoalDTO negative = goal(9, 17, -1);
        assertTrue(TierQuotaSupport.validate(negative, 25).contains("非负整数"));
    }

    @Test
    void shouldPersistQuotaAsIndependentHardObjective() {
        PlanningStateDTO state = new PlanningStateDTO();
        TierQuotaGoalDTO expected = goal(9, 17, 19);

        TierQuotaSupport.persist(state, expected);

        assertTrue(TierQuotaSupport.isPersisted(state, expected));
        assertEquals("exact_counts", state.getConstraintState().getHardPlanningObjectives()
                .getTierQuotaGoal().getType());
        assertTrue(state.getConstraintState().getHardPlanningObjectives()
                .getCoverageRequirements().isEmpty());
        expected.setProtectCount(18);
        assertFalse(TierQuotaSupport.isPersisted(state, expected));
    }

    @Test
    void shouldBuildOnlySyntheticSolveRequirements() {
        assertEquals(3, TierQuotaSupport.syntheticRequirements(goal(0, 2, 3)).size());
        assertEquals(Integer.valueOf(0), TierQuotaSupport.syntheticRequirements(goal(0, 2, 3))
                .get(0).getMinCount());
        assertEquals("保", TierQuotaSupport.syntheticObjectives(goal(0, 2, 3))
                .get(2).getValues().get(0));
    }

    private TierQuotaGoalDTO goal(Integer sprint, Integer stable, Integer protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }
}
