package com.ytell.zhiyuan.service.volunteer;

import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class VolunteerIntervalServiceTest {
    private final VolunteerIntervalService service = new VolunteerIntervalService();

    @Test
    void invalidOrMissingProbabilitiesAreUnknownInsteadOfSafetyCandidates() {
        Double[] invalid = {null, Double.NaN, Double.POSITIVE_INFINITY,
                Double.NEGATIVE_INFINITY, -0.1D, 100.1D};
        for (boolean nineIntervals : new boolean[]{true, false}) {
            for (Double ratio : invalid) {
                Map<String, List<VolunteerSchoolGroup>> result = classify(ratio, nineIntervals);
                assertTrue(result.containsKey("未知"), "unknown probability must be explicitly represented");
                assertEquals(1, result.get("未知").size(), "ratio=" + ratio);
                assertEquals(0, result.entrySet().stream()
                        .filter(entry -> !"未知".equals(entry.getKey()))
                        .mapToInt(entry -> entry.getValue().size()).sum());
            }
        }
    }

    @Test
    void fractionalProbabilitiesHaveContinuousNineIntervalBoundaries() {
        double[] ratios = {0D, 0.5D, 10D, 10.5D, 34D, 34.5D, 50D, 50.5D,
                56D, 56.5D, 62D, 62.5D, 70D, 70.5D, 86D, 86.5D, 98D, 98.5D, 100D};
        String[] expected = {"冲1", "冲1", "冲1", "冲2", "冲2", "冲3", "冲3", "稳1",
                "稳1", "稳2", "稳2", "稳3", "稳3", "保1", "保1", "保2", "保2", "保3", "保3"};
        for (int index = 0; index < ratios.length; index++) {
            assertEquals(1, classify(ratios[index], true).get(expected[index]).size(),
                    "ratio=" + ratios[index]);
        }
    }

    @Test
    void fractionalProbabilitiesHaveContinuousThreeIntervalBoundaries() {
        double[] ratios = {0D, 50D, 50.5D, 70D, 70.5D, 100D};
        String[] expected = {"冲", "冲", "稳", "稳", "保", "保"};
        for (int index = 0; index < ratios.length; index++) {
            assertEquals(1, classify(ratios[index], false).get(expected[index]).size(),
                    "ratio=" + ratios[index]);
        }
    }

    private Map<String, List<VolunteerSchoolGroup>> classify(Double ratio, boolean nineIntervals) {
        VolunteerSchoolGroup group = new VolunteerSchoolGroup();
        group.setSchoolEnrollRatio(ratio);
        return service.divideVolunteers(new ArrayList<>(Collections.singletonList(group)), nineIntervals);
    }
}
