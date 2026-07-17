package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CoverageSelectionSolverTest {

    @Test
    void shouldChooseMinimumCoverageSetInsteadOfGreedyLocalMaximum() {
        List<String> requirements = Arrays.asList("1", "2", "3", "4", "5", "6");
        List<Set<String>> options = Arrays.asList(
                set("1", "2", "3", "4"),
                set("1", "2", "5"),
                set("3", "4", "6"));

        List<Set<String>> selected = CoverageSelectionSolver.selectMinimum(
                options, requirements, new int[requirements.size()],
                ignored -> 1, Set::contains);

        assertEquals(Arrays.asList(options.get(1), options.get(2)), selected);
    }

    @SafeVarargs
    private final <T> Set<T> set(T... values) {
        return new java.util.LinkedHashSet<T>(Arrays.asList(values));
    }
}
