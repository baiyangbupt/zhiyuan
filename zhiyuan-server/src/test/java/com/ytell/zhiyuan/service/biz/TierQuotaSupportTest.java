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
    void shouldNormalizeAllSupportedTierAliasesToInternalKeys() {
        assertTierAliases("sprint", "冲", "冲刺", "sprint", " SPRINT ", "reach");
        assertTierAliases("stable", "稳", "稳妥", "stable", " STABLE ", "safe");
        assertTierAliases("protect", "保", "保底", "兜底", "保险",
                "protect", " PROTECTIVE ", "safety");
    }

    @Test
    void shouldReturnEmptyCanonicalKeyForMissingOrUnknownTier() {
        assertEquals("", TierQuotaSupport.canonicalTierKey(null));
        assertEquals("", TierQuotaSupport.canonicalTierKey("  CUSTOM  "));
        assertEquals("", TierQuotaSupport.canonicalTierKey("超稳"));
    }

    private void assertTierAliases(String expected, String... aliases) {
        for (String alias : aliases) {
            assertEquals(expected, TierQuotaSupport.canonicalTierKey(alias), alias);
        }
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
