package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.BiPredicate;
import java.util.function.ToIntFunction;

final class CoverageSelectionSolver {

    private static final int MAX_STATES = 20000;

    private CoverageSelectionSolver() {
    }

    static <O, R> List<O> selectMinimum(List<O> options,
                                        List<R> requirements,
                                        int[] currentCounts,
                                        ToIntFunction<R> minCount,
                                        BiPredicate<O, R> matcher) {
        int[] initialRemaining = new int[requirements.size()];
        for (int index = 0; index < requirements.size(); index++) {
            int current = currentCounts == null || index >= currentCounts.length ? 0 : currentCounts[index];
            initialRemaining[index] = Math.max(0, minCount.applyAsInt(requirements.get(index)) - current);
        }
        CoverageState goal = new CoverageState(new int[requirements.size()]);
        CoverageState initial = new CoverageState(initialRemaining);
        if (initial.equals(goal)) {
            return Lists.newArrayList();
        }

        Map<CoverageState, List<O>> states = new LinkedHashMap<CoverageState, List<O>>();
        states.put(initial, Lists.newArrayList());
        for (O option : options) {
            List<Map.Entry<CoverageState, List<O>>> snapshot = Lists.newArrayList(states.entrySet());
            for (Map.Entry<CoverageState, List<O>> entry : snapshot) {
                int[] nextRemaining = Arrays.copyOf(entry.getKey().remaining, entry.getKey().remaining.length);
                boolean changed = false;
                for (int index = 0; index < requirements.size(); index++) {
                    if (nextRemaining[index] > 0 && matcher.test(option, requirements.get(index))) {
                        nextRemaining[index]--;
                        changed = true;
                    }
                }
                if (!changed) {
                    continue;
                }
                CoverageState nextState = new CoverageState(nextRemaining);
                List<O> candidateSelection = Lists.newArrayList(entry.getValue());
                candidateSelection.add(option);
                List<O> existing = states.get(nextState);
                if (existing == null || candidateSelection.size() < existing.size()) {
                    states.put(nextState, candidateSelection);
                }
            }
            if (states.size() > MAX_STATES) {
                return null;
            }
        }
        return states.get(goal);
    }

    private static final class CoverageState {
        private final int[] remaining;

        private CoverageState(int[] remaining) {
            this.remaining = Arrays.copyOf(remaining, remaining.length);
        }

        @Override
        public boolean equals(Object other) {
            return other instanceof CoverageState
                    && Arrays.equals(remaining, ((CoverageState) other).remaining);
        }

        @Override
        public int hashCode() {
            return Arrays.hashCode(remaining);
        }
    }
}
