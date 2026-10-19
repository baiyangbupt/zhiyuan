package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertThrows;

class PlanOrderingEngineTest {

    @Test
    void movesPriorityMatchesToFrontWithinTierStably() {
        PlanOrderingEngine.OrderResult result = PlanOrderingEngine.order(Arrays.asList(
                entry("a", "稳", false, false),
                entry("b", "冲", true, false),
                entry("c", "稳", true, false),
                entry("d", "稳", false, false)), true);

        // 档位按首次出现顺序保留：稳组内 c 前置，冲组 b 不动。
        assertEquals(Arrays.asList("c", "b", "a", "d"), result.orderedIds);
        assertEquals(Arrays.asList("a", "b", "c", "d"), result.selectedIds);
        assertEquals(0, result.inversionCount);
        assertFalse(result.pinnedConflict);
        assertTrue(result.changed());
    }

    @Test
    void pinnedItemInChangedTierConflicts() {
        PlanOrderingEngine.OrderResult result = PlanOrderingEngine.order(Arrays.asList(
                entry("a", "稳", false, true),
                entry("b", "稳", true, false)), true);

        assertEquals(Arrays.asList("b", "a"), result.orderedIds);
        assertTrue(result.pinnedConflict);
    }

    @Test
    void priorityDisabledKeepsOriginalOrder() {
        PlanOrderingEngine.OrderResult result = PlanOrderingEngine.order(Arrays.asList(
                entry("a", "稳", false, false),
                entry("b", "稳", true, false)), false);

        assertEquals(Arrays.asList("a", "b"), result.orderedIds);
        assertFalse(result.changed());
        assertFalse(result.pinnedConflict);
    }

    @Test
    void probabilitySortIsAscendingStableAndKeepsUnauthorizedSlots() {
        Map<String, Double> ratios = new LinkedHashMap<String, Double>();
        ratios.put("high", 90D);
        ratios.put("fixed", 50D);
        ratios.put("low", 30D);
        ratios.put("equal", 30D);
        PlanOrderingEngine.OrderResult result = PlanOrderingEngine.orderByProbability(Arrays.asList(
                entry("high", "protect", false, false), entry("fixed", "protect", false, true),
                entry("low", "protect", false, false), entry("equal", "protect", false, false)), ratios);
        assertEquals(Arrays.asList("low", "fixed", "equal", "high"), result.orderedIds);
        assertEquals(Arrays.asList("high", "fixed", "low", "equal"), result.selectedIds);
        assertFalse(result.pinnedConflict);
    }

    @Test
    void probabilitySortRejectsMissingAndNonFiniteRatios() {
        Map<String, Double> ratios = new LinkedHashMap<String, Double>();
        assertThrows(IllegalArgumentException.class, () -> PlanOrderingEngine.orderByProbability(
                Arrays.asList(entry("missing", "protect", false, false)), ratios));
        ratios.put("missing", Double.POSITIVE_INFINITY);
        assertThrows(IllegalArgumentException.class, () -> PlanOrderingEngine.orderByProbability(
                Arrays.asList(entry("missing", "protect", false, false)), ratios));
    }

    private PlanOrderingEngine.OrderEntry entry(String id, String tier,
                                                boolean matched, boolean pinned) {
        return new PlanOrderingEngine.OrderEntry(id, tier, matched, pinned);
    }
}
