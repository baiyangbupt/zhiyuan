package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;

class SolverShadowSupportTest {

    @Test
    void shadowRunsWithoutChangingLegacyResult() {
        String previous = System.getProperty("solver.v2.shadow");
        System.setProperty("solver.v2.shadow", "true");
        try {
            PlanningStateDTO state = new PlanningStateDTO();
            state.getCandidatePoolState().setVolunteerModel("major");
            state.getCandidatePoolState().setSourceProvinceName("浙江");
            state.getCandidatePoolState().setUserScore(600);
            List<CandidateItemDTO> candidates = Arrays.asList(
                    candidate("a"), candidate("b"));
            state.getCandidatePoolState().setItems(candidates);
            CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
            objectives.setTargetCount(2);
            objectives.setCountMode("volunteer");
            objectives.setObjectiveDigest("shadow-test");
            PlanSolverResultDTO legacy = new PlanSolverResultDTO();
            legacy.setStatus("ready");
            legacy.setSelectedEntityIds(Lists.newArrayList("a", "b"));
            legacy.setInputDigest("legacy");

            assertDoesNotThrow(() -> SolverShadowSupport.shadowSelection(
                    state, candidates, objectives, legacy));
            assertEquals(Arrays.asList("a", "b"), legacy.getSelectedEntityIds());
        } finally {
            if (previous == null) {
                System.clearProperty("solver.v2.shadow");
            } else {
                System.setProperty("solver.v2.shadow", previous);
            }
        }
    }

    private CandidateItemDTO candidate(String id) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setSchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setProvinceName("浙江");
        candidate.setTier("稳");
        candidate.setIntentScore(80D);
        candidate.setFinalScore(80D);
        candidate.setAdmissionRatio(0.6D);
        return candidate;
    }
}
