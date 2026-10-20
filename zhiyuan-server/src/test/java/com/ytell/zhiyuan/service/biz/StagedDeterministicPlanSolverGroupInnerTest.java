package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class StagedDeterministicPlanSolverGroupInnerTest {

    private final StagedDeterministicPlanSolver solver = new StagedDeterministicPlanSolver();

    @AfterEach
    void clearFlag() {
        System.clearProperty(GroupInnerMajorOptimizationFlags.PROPERTY);
    }

    @Test
    void onModeWritesMajorPlanForSelectedUnits() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        MutationPolicyDTO policy = policy();
        policy.setRequiredMajorCount(2);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(unitFact("u1", 4), unitFact("u2", 4)), objectives(2), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertEquals(Arrays.asList("u1", "u2"), result.solverResult.getSelectedEntityIds());
        Map<String, List<String>> plan = result.solverResult.getSelectedMajorIdsByUnit();
        assertEquals(2, plan.size());
        assertEquals(Arrays.asList("u1-v3", "u1-v4"), plan.get("u1"));
        assertEquals(Arrays.asList("u2-v3", "u2-v4"), plan.get("u2"));
    }

    @Test
    void reusesStageOneMajorPlanWithoutReselecting() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        MutationPolicyDTO policy = policy();
        policy.setRequiredMajorCount(2);
        CandidateFactDTO fact = unitFact("u1", 4);
        fact.setPlannedCandidates(Arrays.asList(
                fact.getRawCandidates().get(3), fact.getRawCandidates().get(1)));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(fact), objectives(1), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertEquals(Arrays.asList("u1-v4", "u1-v2"),
                result.solverResult.getSelectedMajorIdsByUnit().get("u1"),
                "阶段二必须复用阶段一计划，不能重新选专业");
    }

    @Test
    void offModeLeavesSelectedMajorsEmpty() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "off");
        MutationPolicyDTO policy = policy();
        policy.setRequiredMajorCount(2);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(unitFact("u1", 4), unitFact("u2", 4)), objectives(2), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertTrue(result.solverResult.getSelectedMajorIdsByUnit().isEmpty());
    }

    @Test
    void keepsAllMajorsWhenGroupBelowRequiredCount() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        MutationPolicyDTO policy = policy();
        policy.setRequiredMajorCount(5);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(unitFact("u1", 3)), objectives(1), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertEquals(Arrays.asList("u1-v1", "u1-v2", "u1-v3"),
                result.solverResult.getSelectedMajorIdsByUnit().get("u1"));
    }

    @Test
    void shadowModeDoesNotWriteResult() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "shadow");
        MutationPolicyDTO policy = policy();
        policy.setRequiredMajorCount(2);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(unitFact("u1", 4), unitFact("u2", 4)), objectives(2), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertTrue(result.solverResult.getSelectedMajorIdsByUnit().isEmpty());
    }

    private CandidateSnapshotDTO snapshot(CandidateFactDTO... facts) {
        CandidateSnapshotDTO snapshot = new CandidateSnapshotDTO();
        snapshot.setCountMode("unit");
        snapshot.setSourceProvince("浙江");
        snapshot.setFacts(new ArrayList<CandidateFactDTO>(Arrays.asList(facts)));
        return snapshot;
    }

    private CanonicalPlanningObjectiveSetDTO objectives(int targetCount) {
        CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
        objectives.setTargetCount(targetCount);
        objectives.setCountMode("unit");
        objectives.setObjectiveDigest("objective-" + targetCount);
        return objectives;
    }

    private MutationPolicyDTO policy() {
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("GENERATE");
        return policy;
    }

    private CandidateFactDTO unitFact(String unitId, int majors) {
        CandidateFactDTO fact = new CandidateFactDTO();
        fact.setEntityId(unitId);
        fact.setTier("stable");
        fact.setProvinceName("浙江");
        fact.setCurrent(false);
        fact.setLocked(false);
        fact.setPinned(false);
        fact.setEligible(true);
        fact.setCompensationSafe(true);
        fact.setUnitAllSafe(true);
        fact.setUtilityScore(100);
        fact.setStableOrder(Integer.parseInt(unitId.substring(1)) - 1);
        for (int index = 1; index <= majors; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(unitId + "-v" + index);
            candidate.setPlanSchoolDataId(unitId);
            candidate.setSchoolEnrollRatio(60D);
            candidate.setAdmissionRatio(50D + index);
            candidate.setIntentScore(50D);
            candidate.setFinalScore(50D);
            fact.getRawCandidates().add(candidate);
        }
        return fact;
    }
}
