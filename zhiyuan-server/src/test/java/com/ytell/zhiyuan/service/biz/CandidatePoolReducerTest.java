package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CandidatePoolReducerTest {

    @Test
    void keepsMandatoryAndDoesNotExceedCap() {
        CandidateSnapshotDTO snapshot = snapshot(620, "浙江");
        snapshot.getFacts().get(0).setCurrent(true);
        snapshot.getFacts().get(0).setLocked(true);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(true);

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(2), policy, 600);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.witnessAvailable);
        assertTrue(reduction.candidateCountSolved <= 600);
        assertTrue(reduction.facts.stream()
                .anyMatch(fact -> "f0".equals(fact.getEntityId())));
        assertTrue(reduction.droppedCount > 0);
        assertTrue(reduction.capLimited);
    }

    @Test
    void coreOverLimitIsReportedSeparatelyFromCandidateShortage() {
        CandidateSnapshotDTO snapshot = snapshot(605, "浙江");
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            fact.setLocked(true);
        }

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(2), new MutationPolicyDTO(), 600);

        assertTrue(reduction.coreOverLimit);
        assertEquals(605, reduction.mandatorySize);
        assertEquals(605, reduction.facts.size());
    }

    @Test
    void overlappingCoverageKeepsFeasibleWitnessWithinCap() {
        CandidateSnapshotDTO snapshot = snapshot(620, "江苏");
        snapshot.getFacts().get(0).setProvinceName("浙江");
        snapshot.getFacts().get(1).setProvinceName("浙江");
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("region");
        coverage.setKey("province");
        coverage.setValues(Arrays.asList("浙江"));
        coverage.setMinCount(2);
        objectives.setCoverageConstraints(new ArrayList<CoverageRequirementDTO>(
                Arrays.asList(coverage)));
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            CandidateItemDTO raw = new CandidateItemDTO();
            raw.setVolunteerId(fact.getEntityId());
            raw.setProvinceName(fact.getProvinceName());
            fact.setRawCandidates(new ArrayList<CandidateItemDTO>(Arrays.asList(raw)));
        }

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives, new MutationPolicyDTO(), 600);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.witnessAvailable);
        assertTrue(reduction.candidateCountSolved <= 600);
        assertTrue(reduction.facts.stream()
                .anyMatch(fact -> "f0".equals(fact.getEntityId())));
    }

    @Test
    void currentFactsStayVisibleWhenLockExistingIsFalse() {
        CandidateSnapshotDTO snapshot = snapshot(620, "浙江");
        snapshot.getFacts().get(300).setCurrent(true);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(2), policy, 600);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.facts.stream()
                .anyMatch(fact -> "f300".equals(fact.getEntityId())),
                "current 行被 reducer 丢掉会让 removeEntityIds 漏报，apply 后总数悄悄变多");
    }

    private CandidateSnapshotDTO snapshot(int count, String province) {
        CandidateSnapshotDTO snapshot = new CandidateSnapshotDTO();
        snapshot.setSourceProvince(province);
        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        for (int index = 0; index < count; index++) {
            CandidateFactDTO fact = new CandidateFactDTO();
            fact.setEntityId("f" + index);
            fact.setTier("stable");
            fact.setProvinceName(province);
            fact.setEligible(true);
            fact.setUtilityScore(100 - (index % 50));
            fact.setUtilityCoverage(100);
            fact.setStableOrder(index);
            fact.setCurrent(false);
            fact.setLocked(false);
            fact.setPinned(false);
            facts.add(fact);
        }
        snapshot.setFacts(facts);
        return snapshot;
    }

    @Test
    void priorityWitnessSurvivesTheSixHundredCandidateBoundary() {
        for (int count : Arrays.asList(600, 601)) {
            CandidateSnapshotDTO snapshot = snapshot(count, "浙江");
            CandidateFactDTO priority = snapshot.getFacts().get(count - 1);
            priority.setPriorityMatched(true);
            priority.setUtilityScore(0);
            MutationPolicyDTO policy = new MutationPolicyDTO();
            policy.setPrioritySelection(true);

            StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                    .solve(snapshot, objectives(1), policy);

            assertEquals("ready", result.solverResult.getStatus());
            assertEquals(Arrays.asList(priority.getEntityId()), result.solverResult.getSelectedEntityIds());
        }
    }

    @Test
    void witnessSolverRejectsAnOverCapModelInsteadOfBypassingTheLimit() {
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setInitialContentGuard(true);

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solveReductionWitness(snapshot(601, "浙江"), objectives(1), policy);

        assertEquals("blocked", result.solverResult.getStatus());
        assertEquals("solver_input_invalid", result.solverResult.getDiagnostics().get(0).getReasonCode());
    }

    @Test
    void initialPolicyKeepsPriorityMultiplicityAndSafeWitnessWithinCap() {
        CandidateSnapshotDTO snapshot = snapshot(1001, "浙江");
        for (int index = 0; index < snapshot.getFacts().size(); index++) {
            CandidateFactDTO fact = snapshot.getFacts().get(index);
            fact.setCompensationSafe(true);
            fact.setCurrent(index < 45);
            fact.setPriorityMatched(index >= 956);
            if (index >= 956) {
                fact.setUtilityScore(0);
            }
        }
        MutationPolicyDTO policy = initialPolicy();

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(45), policy, 600);
        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives(45), policy);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.witnessAvailable);
        assertEquals(45, reduction.witnessSize);
        assertEquals(600, reduction.candidateCountSolved);
        assertEquals(45, reduction.facts.stream()
                .filter(fact -> Boolean.TRUE.equals(fact.getPriorityMatched())).count());
        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertEquals(600, result.solverResult.getCandidateCount());
        assertEquals(45, result.solverResult.getSelectedEntityIds().size());
        assertTrue(result.solverResult.getSelectedEntityIds().stream()
                .allMatch(id -> Integer.parseInt(id.substring(1)) >= 956));
    }

    @Test
    void initialPolicyPreservesSafetyBeforePriorityAtTheBoundary() {
        CandidateSnapshotDTO snapshot = snapshot(601, "浙江");
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            fact.setCompensationSafe(true);
        }
        snapshot.getFacts().get(0).setCurrent(true);
        snapshot.getFacts().get(599).setTier("protect");
        snapshot.getFacts().get(599).setUtilityScore(0);
        snapshot.getFacts().get(600).setPriorityMatched(true);
        snapshot.getFacts().get(600).setUtilityScore(0);
        CanonicalPlanningObjectiveSetDTO objectives = objectives(1);
        StructureTargetDTO structure = new StructureTargetDTO();
        structure.setMinLocalProtect(1);
        objectives.setStructureTarget(structure);

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives, initialPolicy());

        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertEquals(Arrays.asList("f599"), result.solverResult.getSelectedEntityIds());
        assertTrue(result.solverResult.getCandidateCount() <= 600);
    }

    @Test
    void cappedWitnessKeepsForcedRemovalVisibleAndHonorsRequiredSafeAddition() {
        CandidateSnapshotDTO snapshot = snapshot(20, "浙江");
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            fact.setCompensationSafe(true);
        }
        snapshot.getFacts().get(0).setCurrent(true);
        snapshot.getFacts().get(1).setCurrent(true);
        snapshot.getFacts().get(1).setLocked(true);
        snapshot.getFacts().get(19).setPriorityMatched(true);
        MutationPolicyDTO policy = initialPolicy();
        policy.getForcedRemoveEntityIds().add("f0");
        policy.getForcedAddEntityIds().add("f19");

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(2), policy, 4);
        snapshot.setFacts(reduction.facts);
        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives(2), policy);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.witnessAvailable);
        assertTrue(reduction.candidateCountSolved <= 4);
        assertTrue(reduction.protectionBudgetTruncated);
        assertTrue(reduction.facts.stream().anyMatch(fact -> "f0".equals(fact.getEntityId())));
        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertEquals(Arrays.asList("f1", "f19"), result.solverResult.getSelectedEntityIds());
        assertEquals(Arrays.asList("f0"), result.solverResult.getRemoveEntityIds());
    }

    @Test
    void currentVisibilityCoreOverCapIsBlockedWithoutClaimingGlobalInfeasibility() {
        CandidateSnapshotDTO snapshot = snapshot(601, "浙江");
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            fact.setCurrent(true);
        }

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives(1), initialPolicy());

        assertEquals("blocked", result.solverResult.getStatus());
        assertEquals("candidate_cap_core_over_limit",
                result.solverResult.getDiagnostics().get(0).getReasonCode());
        assertTrue(result.solverResult.getSelectedEntityIds().isEmpty());
    }

    @Test
    void cappedInitialWitnessHonorsCoverageAndExactTierCountsTogether() {
        CandidateSnapshotDTO snapshot = snapshot(601, "浙江");
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            fact.setCompensationSafe(true);
        }
        snapshot.getFacts().get(0).setCurrent(true);
        CandidateFactDTO coverageFact = snapshot.getFacts().get(599);
        coverageFact.setTier("protect");
        coverageFact.setUtilityScore(0);
        CandidateItemDTO raw = new CandidateItemDTO();
        raw.setVolunteerId("f599");
        raw.setProvinceName("江苏");
        coverageFact.setRawCandidates(Arrays.asList(raw));
        snapshot.getFacts().get(600).setPriorityMatched(true);
        snapshot.getFacts().get(600).setUtilityScore(0);
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("region");
        coverage.setKey("province");
        coverage.setValues(Arrays.asList("江苏"));
        coverage.setMinCount(1);
        objectives.setCoverageConstraints(Arrays.asList(coverage));
        TierAllocationConstraintDTO tiers = new TierAllocationConstraintDTO();
        tiers.setType("exact_counts");
        tiers.setSprintCount(0);
        tiers.setStableCount(1);
        tiers.setProtectCount(1);
        objectives.setTierAllocationConstraint(tiers);

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives, initialPolicy());

        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertEquals(Arrays.asList("f599", "f600"), result.solverResult.getSelectedEntityIds());
        assertTrue(result.solverResult.getCandidateCount() <= 600);
        assertTrue(result.solverResult.getObjectiveResults().stream()
                .allMatch(objective -> Boolean.TRUE.equals(objective.getSatisfied())));
    }

    @Test
    void initialGuardInfeasibilityDoesNotCreateAFalseWitnessOrGlobalShortageClaim() {
        CandidateSnapshotDTO snapshot = snapshot(601, "浙江");
        snapshot.setCountMode("unit");
        snapshot.getFacts().get(0).setCurrent(true);
        for (int index = 0; index < snapshot.getFacts().size(); index++) {
            CandidateFactDTO fact = snapshot.getFacts().get(index);
            fact.setCompensationSafe(true);
            int majorCount = index == 0 ? 1 : 6;
            for (int majorIndex = 0; majorIndex < majorCount; majorIndex++) {
                CandidateItemDTO major = new CandidateItemDTO();
                major.setVolunteerId("f" + index + "-" + majorIndex);
                major.setPreferred(index == 0);
                fact.getPlannedCandidates().add(major);
            }
        }
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        objectives.setCountMode("unit");

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives, initialPolicy(), 600);
        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives, initialPolicy());

        assertFalse(reduction.witnessAvailable);
        assertTrue(reduction.candidateCountSolved <= 600);
        assertEquals("blocked", result.solverResult.getStatus());
        assertEquals("solver_infeasible_after_cap",
                result.solverResult.getDiagnostics().get(0).getReasonCode());
    }

    private MutationPolicyDTO initialPolicy() {
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("INITIAL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        policy.setInitialContentGuard(true);
        policy.setPrioritySelection(true);
        return policy;
    }

    @Test
    void initialGuardRetainsOnlySafeAdditionAcrossTheCapBoundary() {
        for (int count : Arrays.asList(600, 601)) {
            CandidateSnapshotDTO snapshot = snapshot(count, "浙江");
            snapshot.getFacts().get(0).setCurrent(true);
            CandidateFactDTO safeAddition = snapshot.getFacts().get(count - 1);
            safeAddition.setUtilityScore(0);
            for (int index = 1; index < count - 1; index++) {
                snapshot.getFacts().get(index).setRiskFlags(Arrays.asList("special_enrollment"));
            }
            MutationPolicyDTO policy = new MutationPolicyDTO();
            policy.setInitialContentGuard(true);

            StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                    .solve(snapshot, objectives(2), policy);

            assertEquals("ready", result.solverResult.getStatus(),
                    result.solverResult.getDiagnostics().toString());
            assertTrue(result.solverResult.getSelectedEntityIds().contains(safeAddition.getEntityId()));
        }
    }

    @Test
    void initialGuardWitnessHonorsItemCapAndPreferredFloorTogether() {
        CandidateSnapshotDTO snapshot = snapshot(601, "浙江");
        snapshot.setCountMode("unit");
        CandidateFactDTO current = snapshot.getFacts().get(0);
        current.setCurrent(true);
        current.setLocked(true);
        CandidateItemDTO preferred = new CandidateItemDTO();
        preferred.setVolunteerId("current-preferred");
        preferred.setPreferred(true);
        current.setPlannedCandidates(Arrays.asList(preferred));
        for (int index = 1; index < 600; index++) {
            List<CandidateItemDTO> oversized = new ArrayList<CandidateItemDTO>();
            for (int majorIndex = 0; majorIndex < 6; majorIndex++) {
                CandidateItemDTO major = new CandidateItemDTO();
                major.setVolunteerId("f" + index + "-" + majorIndex);
                oversized.add(major);
            }
            snapshot.getFacts().get(index).setPlannedCandidates(oversized);
        }
        CandidateFactDTO onlySmall = snapshot.getFacts().get(600);
        onlySmall.setUtilityScore(0);
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        objectives.setCountMode("unit");
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setInitialContentGuard(true);

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives, policy);

        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertTrue(result.solverResult.getSelectedEntityIds().contains(onlySmall.getEntityId()));
    }

    @Test
    void initialGuardWitnessRetainsOnlyReplacementSatisfyingPreferredFloor() {
        CandidateSnapshotDTO snapshot = snapshot(601, "浙江");
        snapshot.setCountMode("unit");
        for (int index : Arrays.asList(0, 1, 600)) {
            CandidateFactDTO fact = snapshot.getFacts().get(index);
            fact.setCurrent(index < 2);
            fact.setUtilityScore(0);
            int preferredCount = index == 600 ? 2 : 1;
            for (int majorIndex = 0; majorIndex < preferredCount; majorIndex++) {
                CandidateItemDTO preferred = new CandidateItemDTO();
                preferred.setVolunteerId("f" + index + "-" + majorIndex);
                preferred.setPreferred(true);
                fact.getPlannedCandidates().add(preferred);
            }
        }
        CanonicalPlanningObjectiveSetDTO objectives = objectives(1);
        objectives.setCountMode("unit");
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setInitialContentGuard(true);

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives, policy);

        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertEquals(Arrays.asList("f600"), result.solverResult.getSelectedEntityIds());
    }

    @Test
    void coverageWitnessUsesPlannedMajorsRatherThanUnselectedRawMajors() {
        CandidateSnapshotDTO snapshot = snapshot(601, "浙江");
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            CandidateItemDTO raw = new CandidateItemDTO();
            raw.setVolunteerId(fact.getEntityId() + "-raw");
            raw.setMajorName("法学");
            fact.getRawCandidates().add(raw);
            CandidateItemDTO planned = new CandidateItemDTO();
            planned.setVolunteerId(fact.getEntityId() + "-selected");
            planned.setMajorName("f600".equals(fact.getEntityId()) ? "法学" : "数学");
            fact.getPlannedCandidates().add(planned);
        }
        snapshot.getFacts().get(600).setUtilityScore(0);
        CoverageRequirementDTO requirement = new CoverageRequirementDTO();
        requirement.setDomain("major");
        requirement.setKey("major");
        requirement.setValues(Arrays.asList("法学"));
        requirement.setMinCount(1);
        CanonicalPlanningObjectiveSetDTO objectives = objectives(1);
        objectives.setCoverageConstraints(Arrays.asList(requirement));

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives, new MutationPolicyDTO());

        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertEquals(Arrays.asList("f600"), result.solverResult.getSelectedEntityIds());
    }

    private CanonicalPlanningObjectiveSetDTO objectives(int target) {
        CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
        objectives.setTargetCount(target);
        objectives.setCountMode("volunteer");
        objectives.setObjectiveDigest("reducer-" + target);
        return objectives;
    }
}
