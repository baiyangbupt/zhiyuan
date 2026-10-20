package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;

class GroupInnerMajorPlannerTest {

    @AfterEach
    void clearFlag() {
        System.clearProperty(GroupInnerMajorOptimizationFlags.PROPERTY);
        System.clearProperty(GroupInnerMajorCapFlags.PROPERTY);
    }

    @Test
    void offModeUsesDeterministicSelector() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "off");

        List<CandidateItemDTO> planned = GroupInnerMajorPlanner.plan(input(), 2, 60D);

        assertEquals(Arrays.asList("a", "b"), ids(planned),
                "off 模式必须保持原有启发式排序口径");
    }

    @Test
    void onModeUsesGroupInnerMilp() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");

        List<CandidateItemDTO> planned = GroupInnerMajorPlanner.plan(input(), 2, 60D);

        assertEquals(Arrays.asList("b", "c"), ids(planned),
                "on 模式按 intent/quality/future 效用选择，而不是未来发展的单键排序");
    }

    @Test
    void capOffKeepsAllMajorsEvenWhenOptimizationOn() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        System.setProperty(GroupInnerMajorCapFlags.PROPERTY, "false");

        assertEquals(Arrays.asList("a", "b", "c"),
                ids(GroupInnerMajorPlanner.plan(input(), 2, 60D)));
    }

    @Test
    void shadowModeKeepsLegacySelectorForProductionPaths() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "shadow");

        assertEquals(Arrays.asList("a", "b"), ids(GroupInnerMajorPlanner.plan(input(), 2, 60D)));
    }

    /**
     * a: future 高、intent 低 -> 启发式第一；
     * b/c: intent 高 -> MILP 效用前二。
     */
    private List<CandidateItemDTO> input() {
        return Arrays.asList(
                candidate("a", 10D, 90D, 0D),
                candidate("b", 100D, 20D, 0D),
                candidate("c", 80D, 10D, 0D));
    }

    private CandidateItemDTO candidate(String id, Double intent, Double future, Double finalScore) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setIntentScore(intent);
        candidate.setFinalScore(finalScore);
        candidate.setFutureDevelopmentScore(future);
        candidate.setAdmissionRatio(50D);
        candidate.setSchoolEnrollRatio(60D);
        candidate.setPreferred(false);
        return candidate;
    }

    private List<String> ids(List<CandidateItemDTO> candidates) {
        return candidates.stream().map(CandidateItemDTO::getVolunteerId).collect(Collectors.toList());
    }
}
