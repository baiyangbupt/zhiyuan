package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class TierStructureProjectionTest {

    @Test
    void shouldKeepCurrentCountsWhenTheyAlreadySatisfyBounds() {
        TierCountsDTO projected = TierStructureProjection.project(
                counts(1, 2, 1), 4, bounds(0, 2, 0, 4, 0, 4));

        assertEquals(counts(1, 2, 1), projected);
    }

    @Test
    void shouldPreferHistoricalShapeAfterApplyingSprintMaximum() {
        TierCountsDTO projected = TierStructureProjection.project(
                counts(12, 17, 16), 45, bounds(0, 10, 0, 45, 0, 45));

        assertEquals(counts(10, 18, 17), projected);
    }

    @Test
    void shouldScaleHistoricalShapeWithLargestRemainder() {
        TierCountsDTO projected = TierStructureProjection.project(
                counts(10, 20, 15), 50, bounds(0, 50, 0, 50, 0, 50));

        assertEquals(counts(11, 22, 17), projected);
    }

    @Test
    void shouldApplyMinimumBeforeRedistributingRemainingCapacity() {
        TierCountsDTO projected = TierStructureProjection.project(
                counts(1, 2, 7), 10, bounds(4, 10, 0, 10, 0, 10));

        assertEquals(counts(4, 1, 5), projected);
    }

    @Test
    void shouldReturnNullWhenThereIsNoHistoricalShape() {
        assertNull(TierStructureProjection.project(
                counts(0, 0, 0), 45, bounds(0, 45, 0, 45, 0, 45)));
    }

    private TierAllocationConstraintDTO bounds(int sprintMin,
                                                int sprintMax,
                                                int stableMin,
                                                int stableMax,
                                                int protectMin,
                                                int protectMax) {
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType("count_ranges");
        result.setSourceType("count_ranges");
        result.setSprint(bound(sprintMin, sprintMax));
        result.setStable(bound(stableMin, stableMax));
        result.setProtect(bound(protectMin, protectMax));
        return result;
    }

    private TierCountRangeDTO bound(int min, int max) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        result.setMinCount(min);
        result.setMaxCount(max);
        return result;
    }

    private TierCountsDTO counts(int sprint, int stable, int protect) {
        TierCountsDTO result = new TierCountsDTO();
        result.setSprintCount(sprint);
        result.setStableCount(stable);
        result.setProtectCount(protect);
        return result;
    }
}
