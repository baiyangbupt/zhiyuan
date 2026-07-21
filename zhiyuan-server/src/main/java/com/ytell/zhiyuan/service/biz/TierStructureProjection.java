package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

final class TierStructureProjection {

    private static final int TIER_COUNT = 3;

    private TierStructureProjection() {
    }

    static TierCountsDTO project(TierCountsDTO current,
                                 int targetCount,
                                 TierAllocationConstraintDTO constraint) {
        int[] weights = values(current);
        long totalWeight = (long) weights[0] + weights[1] + weights[2];
        if (totalWeight == 0L) {
            return null;
        }
        int[] minima = minima(constraint);
        int[] maxima = maxima(constraint, targetCount);
        if (sum(weights) == targetCount && within(weights, minima, maxima)) {
            return counts(weights);
        }
        if (sum(minima) > targetCount || sum(maxima) < targetCount) {
            return null;
        }

        int[] result = {-1, -1, -1};
        boolean[] active = {true, true, true};
        int remaining = targetCount;
        while (activeCount(active) > 0) {
            long activeWeight = activeWeight(weights, active);
            if (activeWeight == 0L) {
                allocateWithoutHistoricalWeight(result, active, minima, maxima, remaining);
                break;
            }
            List<Integer> fixed = new ArrayList<Integer>();
            for (int tier = 0; tier < TIER_COUNT; tier++) {
                if (!active[tier]) {
                    continue;
                }
                long product = (long) remaining * weights[tier];
                if (product < (long) minima[tier] * activeWeight) {
                    result[tier] = minima[tier];
                    fixed.add(tier);
                } else if (product > (long) maxima[tier] * activeWeight) {
                    result[tier] = maxima[tier];
                    fixed.add(tier);
                }
            }
            if (fixed.isEmpty()) {
                allocateLargestRemainder(result, active, weights, maxima, remaining, activeWeight);
                break;
            }
            for (Integer tier : fixed) {
                active[tier] = false;
                remaining -= result[tier];
            }
            if (remaining < 0) {
                return null;
            }
        }
        return sum(result) == targetCount && within(result, minima, maxima) ? counts(result) : null;
    }

    private static void allocateLargestRemainder(int[] result,
                                                 boolean[] active,
                                                 int[] weights,
                                                 int[] maxima,
                                                 int remaining,
                                                 long activeWeight) {
        long[] remainders = new long[TIER_COUNT];
        int assigned = 0;
        for (int tier = 0; tier < TIER_COUNT; tier++) {
            if (!active[tier]) {
                continue;
            }
            long product = (long) remaining * weights[tier];
            result[tier] = (int) (product / activeWeight);
            remainders[tier] = product % activeWeight;
            assigned += result[tier];
        }
        List<Integer> order = new ArrayList<Integer>(Arrays.asList(0, 1, 2));
        order.removeIf(tier -> !active[tier]);
        order.sort(Comparator.comparingLong((Integer tier) -> remainders[tier]).reversed()
                .thenComparingInt(Integer::intValue));
        int missing = remaining - assigned;
        for (Integer tier : order) {
            if (missing == 0) {
                break;
            }
            if (result[tier] < maxima[tier]) {
                result[tier]++;
                missing--;
            }
        }
    }

    private static void allocateWithoutHistoricalWeight(int[] result,
                                                        boolean[] active,
                                                        int[] minima,
                                                        int[] maxima,
                                                        int remaining) {
        for (int tier = 0; tier < TIER_COUNT; tier++) {
            if (active[tier]) {
                result[tier] = minima[tier];
                remaining -= result[tier];
            }
        }
        for (int tier = 0; tier < TIER_COUNT && remaining > 0; tier++) {
            if (!active[tier]) {
                continue;
            }
            int addition = Math.min(remaining, maxima[tier] - result[tier]);
            result[tier] += addition;
            remaining -= addition;
        }
    }

    private static int[] minima(TierAllocationConstraintDTO constraint) {
        return new int[]{minimum(constraint == null ? null : constraint.getSprint()),
                minimum(constraint == null ? null : constraint.getStable()),
                minimum(constraint == null ? null : constraint.getProtect())};
    }

    private static int[] maxima(TierAllocationConstraintDTO constraint, int targetCount) {
        return new int[]{maximum(constraint == null ? null : constraint.getSprint(), targetCount),
                maximum(constraint == null ? null : constraint.getStable(), targetCount),
                maximum(constraint == null ? null : constraint.getProtect(), targetCount)};
    }

    private static int minimum(TierCountRangeDTO bound) {
        return bound == null || bound.getMinCount() == null ? 0 : bound.getMinCount();
    }

    private static int maximum(TierCountRangeDTO bound, int targetCount) {
        return bound == null || bound.getMaxCount() == null ? targetCount : bound.getMaxCount();
    }

    private static int[] values(TierCountsDTO source) {
        return new int[]{value(source == null ? null : source.getSprintCount()),
                value(source == null ? null : source.getStableCount()),
                value(source == null ? null : source.getProtectCount())};
    }

    private static int value(Integer value) {
        return value == null ? 0 : Math.max(0, value);
    }

    private static boolean within(int[] values, int[] minima, int[] maxima) {
        for (int tier = 0; tier < TIER_COUNT; tier++) {
            if (values[tier] < minima[tier] || values[tier] > maxima[tier]) {
                return false;
            }
        }
        return true;
    }

    private static int activeCount(boolean[] active) {
        int result = 0;
        for (boolean value : active) {
            if (value) {
                result++;
            }
        }
        return result;
    }

    private static long activeWeight(int[] weights, boolean[] active) {
        long result = 0L;
        for (int tier = 0; tier < TIER_COUNT; tier++) {
            if (active[tier]) {
                result += weights[tier];
            }
        }
        return result;
    }

    private static int sum(int[] values) {
        return values[0] + values[1] + values[2];
    }

    private static TierCountsDTO counts(int[] values) {
        TierCountsDTO result = new TierCountsDTO();
        result.setSprintCount(values[0]);
        result.setStableCount(values[1]);
        result.setProtectCount(values[2]);
        return result;
    }
}
