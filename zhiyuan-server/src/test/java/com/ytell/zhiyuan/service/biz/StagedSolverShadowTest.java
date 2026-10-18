package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverInputDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * S0a 影子对照：同一份候选事实分别喂给旧 solver 与新分阶段 solver，
 * 只断言共同硬不变量，不要求两边选出同一集合。
 */
class StagedSolverShadowTest {

    private final DeterministicPlanSolver legacy = new OjalgoDeterministicPlanSolver();
    private final StagedDeterministicPlanSolver staged = new StagedDeterministicPlanSolver();

    @Test
    void bothSolversKeepTargetCountAndLockedItems() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("a", "浙江", 90D, 6000),
                candidate("b", "江苏", 80D, 8000),
                candidate("c", "浙江", 70D, 5000),
                candidate("d", "浙江", 60D, 9000)));
        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                state, state.getCandidatePoolState().getItems());
        snapshot.getFacts().get(0).setLocked(true);

        CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
        objectives.setTargetCount(2);
        objectives.setCountMode("volunteer");
        objectives.setObjectiveDigest("shadow-objective");

        PlanSolverResultDTO legacyResult = legacy.solve(legacyInput(snapshot, objectives));
        StagedDeterministicPlanSolver.Result stagedResult = staged.solve(
                snapshot, objectives, new MutationPolicyDTO());

        assertEquals(2, legacyResult.getSelectedEntityIds().size());
        assertEquals(2, stagedResult.solverResult.getSelectedEntityIds().size());
        assertTrue(stagedResult.solverResult.getSelectedEntityIds()
                .contains(snapshot.getFacts().get(0).getEntityId()));
        assertTrue(stagedResult.solverResult.getSelectedEntityIds().stream()
                .allMatch(id -> eligible(snapshot, id)));
    }

    private PlanSolverInputDTO legacyInput(CandidateSnapshotDTO snapshot,
                                           CanonicalPlanningObjectiveSetDTO objectives) {
        PlanSolverInputDTO input = new PlanSolverInputDTO();
        input.setObjectiveSet(objectives);
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            PlanSolverInputDTO.CandidateDTO candidate = new PlanSolverInputDTO.CandidateDTO();
            candidate.setEntityId(fact.getEntityId());
            candidate.setVolunteerIds(Lists.newArrayList(fact.getVolunteerIds()));
            candidate.setStableOrder(fact.getStableOrder());
            candidate.setCurrent(fact.getCurrent());
            candidate.setLocked(fact.getLocked());
            candidate.setPinned(fact.getPinned());
            candidate.setEligible(fact.getEligible());
            candidate.setTier(fact.getTier());
            input.getCandidates().add(candidate);
        }
        return input;
    }

    private boolean eligible(CandidateSnapshotDTO snapshot, String id) {
        return snapshot.getFacts().stream()
                .filter(fact -> id.equals(fact.getEntityId()))
                .anyMatch(fact -> Boolean.TRUE.equals(fact.getEligible()));
    }

    private CandidateItemDTO candidate(String id, String province, Double score, Integer tuition) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setPlanSchoolDataId("unit-" + id);
        candidate.setSchoolName("学校" + id);
        candidate.setProvinceName(province);
        candidate.setMajorName("专业" + id);
        candidate.setTier("stable");
        candidate.setIntentScore(score);
        candidate.setFinalScore(score);
        candidate.setFutureDevelopmentScore(score);
        candidate.setAdmissionRatio(score / 100D);
        candidate.setTuitionPerYear(tuition);
        return candidate;
    }
}
