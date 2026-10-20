package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class UnitMajorSelectorTest {

    @Test
    void selectsCapAndKeepsSafetyMajor() {
        CandidateItemDTO low = candidate("v1", 10D, 40D, false);
        CandidateItemDTO safety = candidate("v2", 80D, 60D, false);
        CandidateItemDTO high = candidate("v3", 90D, 40D, false);
        CandidateItemDTO other = candidate("v4", 70D, 40D, false);

        List<CandidateItemDTO> selected = UnitMajorSelector.select(
                Arrays.asList(low, safety, high, other), 2, 60D);

        assertEquals(2, selected.size());
        assertTrue(selected.stream().anyMatch(item -> "v2".equals(item.getVolunteerId())),
                "safety major 必须入选");
    }

    @Test
    void preferredMajorsWinBeforeUtility() {
        CandidateItemDTO preferred = candidate("v1", 10D, 40D, true);
        CandidateItemDTO high = candidate("v2", 99D, 40D, false);
        CandidateItemDTO other = candidate("v3", 90D, 40D, false);

        List<CandidateItemDTO> selected = UnitMajorSelector.select(
                Arrays.asList(preferred, high, other), 1, 60D);

        assertEquals(Arrays.asList("v1"), selected.stream()
                .map(CandidateItemDTO::getVolunteerId).collect(Collectors.toList()));
    }

    @Test
    void insufficientGroupKeepsAll() {
        List<CandidateItemDTO> input = Arrays.asList(
                candidate("v1", 10D, 40D, false),
                candidate("v2", 90D, 60D, false));

        assertEquals(input, UnitMajorSelector.select(input, 6, 60D));
    }

    @Test
    void selectionIsDeterministicAcrossRuns() {
        List<CandidateItemDTO> input = Arrays.asList(
                candidate("v1", 50D, 40D, true),
                candidate("v2", 80D, 60D, false),
                candidate("v3", 80D, 40D, false),
                candidate("v4", 80D, 40D, false));
        Set<String> expected = null;
        for (int run = 0; run < 10; run++) {
            Set<String> ids = new LinkedHashSet<String>();
            for (CandidateItemDTO item : UnitMajorSelector.select(input, 2, 60D)) {
                ids.add(item.getVolunteerId());
            }
            if (expected == null) {
                expected = ids;
            } else {
                assertEquals(expected, ids);
            }
        }
    }

    private CandidateItemDTO candidate(String id, Double intent, Double ratio, boolean preferred) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setIntentScore(intent);
        candidate.setFinalScore(intent);
        candidate.setFutureDevelopmentScore(intent);
        candidate.setAdmissionRatio(ratio);
        candidate.setSchoolEnrollRatio(60D);
        candidate.setTuitionPerYear(5000);
        candidate.setPreferred(preferred);
        return candidate;
    }
}
