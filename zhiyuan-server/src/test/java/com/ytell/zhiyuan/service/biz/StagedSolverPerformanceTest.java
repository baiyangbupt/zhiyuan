package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 600 候选 / 80 目标 / coverage + tier + safety 的本地性能门禁。
 * 只做上界断言，具体耗时打印出来供切流前对比。
 */
class StagedSolverPerformanceTest {

    private final StagedDeterministicPlanSolver solver = new StagedDeterministicPlanSolver();

    @Test
    void solvesSixHundredCandidatesWithinBudget() {
        CandidateSnapshotDTO snapshot = snapshot(600);
        CanonicalPlanningObjectiveSetDTO objectives = objectives();
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);

        long started = System.nanoTime();
        StagedDeterministicPlanSolver.Result result = solver.solve(snapshot, objectives, policy);
        long durationMs = (System.nanoTime() - started) / 1_000_000L;
        System.out.println("STAGED_SOLVER_PERF candidates=600 target=80 durationMs=" + durationMs
                + " state=" + result.solverResult.getSolverState()
                + " selected=" + result.solverResult.getSelectedEntityIds().size());

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertEquals(80, result.solverResult.getSelectedEntityIds().size());
        assertTrue(durationMs < 5_000L, "durationMs=" + durationMs);
    }

    private CandidateSnapshotDTO snapshot(int count) {
        CandidateSnapshotDTO snapshot = new CandidateSnapshotDTO();
        snapshot.setCountMode("volunteer");
        snapshot.setSourceProvince("浙江");
        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        for (int index = 0; index < count; index++) {
            String tier = index % 3 == 0 ? "sprint" : index % 3 == 1 ? "stable" : "protect";
            CandidateFactDTO fact = new CandidateFactDTO();
            fact.setEntityId("f" + index);
            fact.setTier(tier);
            fact.setProvinceName(index % 2 == 0 ? "浙江" : "江苏");
            fact.setEligible(true);
            fact.setUtilityScore(100 - (index % 100));
            fact.setUtilityCoverage(100);
            fact.setStableOrder(index);
            CandidateItemDTO raw = new CandidateItemDTO();
            raw.setVolunteerId("f" + index);
            raw.setTier(tier);
            raw.setProvinceName(fact.getProvinceName());
            fact.setRawCandidates(new ArrayList<CandidateItemDTO>(Arrays.asList(raw)));
            facts.add(fact);
        }
        snapshot.setFacts(facts);
        return snapshot;
    }

    private CanonicalPlanningObjectiveSetDTO objectives() {
        CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
        objectives.setTargetCount(80);
        objectives.setCountMode("volunteer");
        objectives.setObjectiveDigest("perf-600");
        objectives.setTierAllocationConstraint(tierBounds(27, 27, 26));
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("region");
        coverage.setKey("province");
        coverage.setValues(Arrays.asList("浙江"));
        coverage.setMinCount(3);
        objectives.setCoverageConstraints(new ArrayList<CoverageRequirementDTO>(Arrays.asList(coverage)));
        StructureTargetDTO target = new StructureTargetDTO();
        target.setMinLocalProtect(2);
        objectives.setStructureTarget(target);
        return objectives;
    }

    private TierAllocationConstraintDTO tierBounds(int sprint, int stable, int protect) {
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType("exact_counts");
        result.setSourceType("exact_counts");
        result.setSprint(range(sprint));
        result.setStable(range(stable));
        result.setProtect(range(protect));
        return result;
    }

    private TierCountRangeDTO range(int count) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        result.setMinCount(count);
        result.setMaxCount(count);
        return result;
    }
}
