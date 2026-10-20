package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class GroupInnerMajorSelectorTest {

    @Test
    void capsMajorsAndKeepsSafetyMajor() {
        CandidateItemDTO preferred = candidate("v1", 50D, 40D);
        preferred.setPreferred(true);
        CandidateItemDTO safety = candidate("v2", 80D, 60D);
        CandidateItemDTO ordinary = candidate("v3", 55D, 40D);
        CandidateItemDTO other = candidate("v4", 45D, 40D);

        List<CandidateItemDTO> selected = GroupInnerMajorSelector.select(
                Arrays.asList(preferred, safety, ordinary, other), 2, 60D);

        assertEquals(2, selected.size());
        assertTrue(selected.stream().anyMatch(item -> "v2".equals(item.getVolunteerId())),
                "必须保留 safety major");
        assertEquals(Arrays.asList("v1", "v2"), selected.stream()
                .map(CandidateItemDTO::getVolunteerId).collect(Collectors.toList()),
                "返回顺序保持原始候选顺序");
    }

    @Test
    void noCapKeepsOriginalList() {
        CandidateItemDTO v1 = candidate("v1", 50D, 40D);
        CandidateItemDTO v2 = candidate("v2", 80D, 60D);
        List<CandidateItemDTO> input = Arrays.asList(v1, v2);

        assertEquals(input, GroupInnerMajorSelector.select(input, null, 60D));
        assertEquals(input, GroupInnerMajorSelector.select(input, 0, 60D));
        assertEquals(input, GroupInnerMajorSelector.select(input, 5, 60D));
    }

    private CandidateItemDTO candidate(String id, Double ratio, Double enrollRatio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setAdmissionRatio(ratio);
        candidate.setSchoolEnrollRatio(enrollRatio);
        candidate.setIntentScore(ratio);
        candidate.setFinalScore(ratio);
        return candidate;
    }
}
