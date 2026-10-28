package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DiversityPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureQualityPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class StagedDeterministicPlanSolverTest {

    private final StagedDeterministicPlanSolver solver = new StagedDeterministicPlanSolver();

    @Test
    void stableOrderNeverOverridesOnePointOfUtility() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("high-utility", "stable", "浙江", false, false, 10, 1_000_000),
                fact("low-utility", "stable", "浙江", false, false, 9, 0));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(1);
        // Keep both candidates in the MIP to exercise the separate objective phases.
        DiversityPolicyDTO disabledDiversity = new DiversityPolicyDTO();
        disabledDiversity.setMode("off");
        objectives.setDiversityPolicy(disabledDiversity);

        PlanSolverResultDTO result = solver.solve(snapshot, objectives, policy("FILL", false)).solverResult;

        assertEquals("ready", result.getStatus(), "diagnostics=" + result.getDiagnostics());
        assertEquals(Arrays.asList("high-utility"), result.getSelectedEntityIds());
    }

    @Test
    void utilitySumAboveIntegerRangeRemainsExactInFrozenStageAndTieBreaker() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("first", "stable", "浙江", false, false, 1_500_000_000, 0),
                fact("second", "stable", "浙江", false, false, 1_500_000_000, 1),
                fact("lower", "stable", "浙江", false, false, 1_499_999_999, 2));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        DiversityPolicyDTO disabledDiversity = new DiversityPolicyDTO();
        disabledDiversity.setMode("off");
        objectives.setDiversityPolicy(disabledDiversity);

        StagedDeterministicPlanSolver.Result solved = solver.solve(
                snapshot, objectives, policy("FILL", false));

        assertEquals("ready", solved.solverResult.getStatus(),
                "diagnostics=" + solved.solverResult.getDiagnostics());
        assertEquals(Arrays.asList("first", "second"), solved.solverResult.getSelectedEntityIds());
        assertEquals(3_000_000_000L, level(solved, "utility"));
        assertEquals(3_000_000_000L, solved.solverResult.getStageResults().stream()
                .filter(stage -> "utility".equals(stage.getObjectiveId()))
                .findFirst().get().getValue().longValue());
    }

    @Test
    void exactExchangeReductionMatchesExhaustiveLexicographicOptimum() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a", "sprint", "浙江", false, false, 9, 0),
                fact("b", "sprint", "江苏", false, false, 10, 1),
                fact("c", "sprint", "江苏", false, false, 10, 2),
                fact("d", "stable", "浙江", false, false, 8, 3),
                fact("e", "stable", "浙江", false, false, 8, 4),
                fact("f", "protect", "浙江", false, false, 7, 5),
                fact("g", "protect", "江苏", false, false, 9, 6),
                fact("h", "protect", "浙江", false, false, 6, 7));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(3);
        TierAllocationConstraintDTO tiers = new TierAllocationConstraintDTO();
        tiers.setType("exact_counts");
        TierCountRangeDTO one = new TierCountRangeDTO();
        one.setMinCount(1);
        one.setMaxCount(1);
        tiers.setSprint(one);
        tiers.setStable(one);
        tiers.setProtect(one);
        objectives.setTierAllocationConstraint(tiers);
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("region");
        coverage.setKey("province");
        coverage.setValues(Arrays.asList("浙江"));
        coverage.setMinCount(1);
        objectives.setCoverageConstraints(Arrays.asList(coverage));
        StructureTargetDTO structure = new StructureTargetDTO();
        structure.setMinLocalProtect(1);
        objectives.setStructureTarget(structure);

        PlanSolverResultDTO actual = solver.solve(snapshot, objectives, policy("FILL", false)).solverResult;
        assertEquals("ready", actual.getStatus(), "diagnostics=" + actual.getDiagnostics());
        assertEquals(exhaustiveBestForThreeTiers(snapshot.getFacts()), actual.getSelectedEntityIds());
        assertEquals(Arrays.asList("b", "d", "f"), actual.getSelectedEntityIds());
        assertTrue(org.ojalgo.optimisation.Optimisation.State
                .valueOf(actual.getSolverState()).isOptimal());
    }

    private List<String> exhaustiveBestForThreeTiers(List<CandidateFactDTO> facts) {
        int bestDeficit = Integer.MAX_VALUE;
        int bestUtility = Integer.MIN_VALUE;
        int bestStable = Integer.MAX_VALUE;
        List<String> best = null;
        for (int mask = 0; mask < (1 << facts.size()); mask++) {
            if (Integer.bitCount(mask) != 3) {
                continue;
            }
            int sprint = 0, stable = 0, protect = 0, localProtect = 0, covered = 0;
            int utility = 0, stableOrder = 0;
            List<String> ids = new ArrayList<String>();
            for (int index = 0; index < facts.size(); index++) {
                if ((mask & (1 << index)) == 0) {
                    continue;
                }
                CandidateFactDTO fact = facts.get(index);
                ids.add(fact.getEntityId());
                sprint += "sprint".equals(fact.getTier()) ? 1 : 0;
                stable += "stable".equals(fact.getTier()) ? 1 : 0;
                protect += "protect".equals(fact.getTier()) ? 1 : 0;
                covered += "浙江".equals(fact.getProvinceName()) ? 1 : 0;
                localProtect += "protect".equals(fact.getTier())
                        && "浙江".equals(fact.getProvinceName()) ? 1 : 0;
                utility += fact.getUtilityScore();
                stableOrder += fact.getStableOrder();
            }
            if (sprint != 1 || stable != 1 || protect != 1 || covered < 1) {
                continue;
            }
            int deficit = Math.max(0, 1 - localProtect);
            if (deficit < bestDeficit || deficit == bestDeficit && (utility > bestUtility
                    || utility == bestUtility && stableOrder < bestStable)) {
                bestDeficit = deficit;
                bestUtility = utility;
                bestStable = stableOrder;
                best = ids;
            }
        }
        return best;
    }

    @Test
    void auditDigestReflectsPatchedObjectivesRatherThanStaleCompilerMetadata() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("protect", "protect", "浙江", true, false, 90, 0),
                fact("stable", "stable", "浙江", true, false, 80, 1));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        objectives.setObjectiveDigest("stale-pre-patch-objectives");
        StructureTargetDTO structure = new StructureTargetDTO();
        structure.setMinLocalProtect(0);
        objectives.setStructureTarget(structure);
        PlanSolverResultDTO before = solver.solve(snapshot, objectives, policy("FILL", false)).solverResult;
        structure.setMinLocalProtect(1);
        PlanSolverResultDTO after = solver.solve(snapshot, objectives, policy("FILL", false)).solverResult;

        String beforeDigest = com.alibaba.fastjson.JSON.parseObject(
                com.alibaba.fastjson.JSON.toJSONString(before)).getString("solverObjectiveDigest");
        String afterDigest = com.alibaba.fastjson.JSON.parseObject(
                com.alibaba.fastjson.JSON.toJSONString(after)).getString("solverObjectiveDigest");
        assertEquals("ready", before.getStatus());
        assertEquals("ready", after.getStatus());
        assertNotNull(beforeDigest);
        assertNotNull(afterDigest);
        assertFalse(beforeDigest.equals("stale-pre-patch-objectives"));
        assertFalse(beforeDigest.equals(afterDigest));
        assertEquals(before.getSelectedEntityIds(), after.getSelectedEntityIds());
    }

    @Test
    void initialTierOrderIsSprintStableProtectEvenWhenStableOrderStartsWithStable() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("stable", "stable", "浙江", false, false, 90, 0),
                fact("protect", "protect", "浙江", false, false, 90, 1),
                fact("sprint", "sprint", "浙江", false, false, 90, 2));
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setOrderingPolicyVersion(StagedDeterministicPlanSolver.ORDERING_INITIAL_TIER);

        PlanSolverResultDTO result = solver.solve(snapshot, objectives(3), policy).solverResult;

        assertEquals("ready", result.getStatus());
        assertEquals(Arrays.asList("sprint", "stable", "protect"), result.getOrderedEntityIds());
    }

    @Test
    void structureQualityCapsUnknownRatioBucketWithoutChangingHardStructure() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("unknown-1", "sprint", "浙江", false, false, 100, 0),
                fact("unknown-2", "sprint", "浙江", false, false, 100, 1),
                fact("unknown-3", "sprint", "浙江", false, false, 100, 2),
                fact("unknown-4", "sprint", "浙江", false, false, 100, 3),
                fact("unknown-5", "sprint", "浙江", false, false, 100, 4),
                fact("known-1", "sprint", "浙江", false, false, 10, 5),
                fact("known-2", "sprint", "浙江", false, false, 10, 6),
                fact("known-3", "sprint", "浙江", false, false, 10, 7));
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            if (fact.getEntityId().startsWith("unknown")) {
                fact.setRatioBucket("unknown");
            } else {
                fact.setRatioBucket("known-3".equals(fact.getEntityId())
                        ? "sprint_15_30" : "sprint_5_15");
            }
        }
        CanonicalPlanningObjectiveSetDTO objectives = objectives(5);
        StructureQualityPolicyDTO structure = new StructureQualityPolicyDTO();
        structure.setMode("soft");
        structure.setMaxUnknownBucketShare(0.4D);
        structure.setMaxUtilityLossRatio(0D);
        objectives.setStructureQualityPolicy(structure);

        PlanSolverResultDTO result = solver.solve(snapshot, objectives, policy("FILL", false)).solverResult;

        assertEquals("ready", result.getStatus());
        assertEquals(5, result.getSelectedEntityIds().size());
        long unknownSelected = result.getSelectedEntityIds().stream()
                .filter(id -> id.startsWith("unknown")).count();
        assertEquals(2, unknownSelected);
    }

    @Test
    void structureQualityFallsBackWhenUtilityFloorWouldBlock() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("unknown-1", "sprint", "浙江", false, false, 100, 0),
                fact("unknown-2", "sprint", "浙江", false, false, 100, 1),
                fact("unknown-3", "sprint", "浙江", false, false, 100, 2),
                fact("unknown-4", "sprint", "浙江", false, false, 100, 3),
                fact("unknown-5", "sprint", "浙江", false, false, 100, 4),
                fact("known-1", "sprint", "浙江", false, false, 10, 5),
                fact("known-2", "sprint", "浙江", false, false, 10, 6),
                fact("known-3", "sprint", "浙江", false, false, 10, 7));
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            fact.setRatioBucket(fact.getEntityId().startsWith("unknown")
                    ? "unknown" : "sprint_5_15");
        }
        CanonicalPlanningObjectiveSetDTO objectives = objectives(5);
        StructureQualityPolicyDTO structure = new StructureQualityPolicyDTO();
        structure.setMode("soft");
        structure.setMaxUnknownBucketShare(0.4D);
        objectives.setStructureQualityPolicy(structure);

        PlanSolverResultDTO result = solver.solve(snapshot, objectives, policy("FILL", false)).solverResult;

        assertEquals("ready", result.getStatus());
        assertEquals(5, result.getSelectedEntityIds().size());
        assertTrue(result.getDiagnostics().stream()
                .anyMatch(item -> "structure_quality_unavailable".equals(item.getReasonCode())));
    }

    @Test
    void initialStrictOrderDoesNotPutExistingItemsBeforeHigherQualityAdds() {
        CandidateFactDTO current = fact("current", "sprint", "浙江", true, false, 90, 0);
        current.setFinalScore(80D);
        CandidateFactDTO added = fact("added", "sprint", "浙江", false, false, 90, 1);
        added.setFinalScore(95D);
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setOrderingPolicyVersion(StagedDeterministicPlanSolver.ORDERING_INITIAL_TIER_STRICT);

        PlanSolverResultDTO result = solver.solve(
                snapshot(current, added), objectives(2), policy).solverResult;

        assertEquals("ready", result.getStatus());
        assertEquals(Arrays.asList("added", "current"), result.getOrderedEntityIds());
    }

    @Test
    void initialTierOrderUsesVisibleQualityRatherThanLegacyStableOrder() {
        CandidateFactDTO lower = fact("lower", "sprint", "浙江", false, false, 90, 0);
        lower.setFinalScore(80D);
        CandidateFactDTO higher = fact("higher", "sprint", "浙江", false, false, 90, 1);
        higher.setFinalScore(90D);

        MutationPolicyDTO policy = policy("FILL", false);
        policy.setOrderingPolicyVersion(StagedDeterministicPlanSolver.ORDERING_INITIAL_TIER);

        PlanSolverResultDTO result = solver.solve(
                snapshot(lower, higher), objectives(2), policy).solverResult;

        assertEquals("ready", result.getStatus());
        assertEquals(Arrays.asList("higher", "lower"), result.getOrderedEntityIds());
    }

    @Test
    void preserveCurrentKeepsExistingRelativeOrderAndAppendsNewItems() {
        CandidateFactDTO protect = fact("protect", "protect", "浙江", true, false, 90, 0);
        protect.setCurrentPosition(1);
        CandidateFactDTO sprint = fact("sprint", "sprint", "浙江", true, false, 90, 1);
        sprint.setCurrentPosition(2);
        CandidateFactDTO stable = fact("stable", "stable", "浙江", true, false, 90, 2);
        stable.setCurrentPosition(3);
        CandidateFactDTO added = fact("added", "sprint", "浙江", false, false, 90, 3);
        CandidateSnapshotDTO snapshot = snapshot(protect, sprint, stable, added);
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setOrderingPolicyVersion(StagedDeterministicPlanSolver.ORDERING_PRESERVE_CURRENT);

        PlanSolverResultDTO result = solver.solve(snapshot, objectives(4), policy).solverResult;

        assertEquals("ready", result.getStatus());
        assertEquals(Arrays.asList("protect", "sprint", "stable", "added"),
                result.getOrderedEntityIds());
    }

    @Test
    void knownSpecialPlanConflictIsNotSelectableForNewSelection() {
        CandidateFactDTO conflict = fact("conflict", "sprint", "浙江", false, false, 100, 0);
        conflict.setSpecialPlanConflict(true);
        CandidateFactDTO clean = fact("clean", "stable", "浙江", false, false, 10, 1);
        MutationPolicyDTO policy = policy("FILL", false);

        PlanSolverResultDTO result = solver.solve(snapshot(conflict, clean), objectives(1), policy).solverResult;

        assertEquals("ready", result.getStatus());
        assertFalse(result.getSelectedEntityIds().contains("conflict"));
        assertTrue(result.getSelectedEntityIds().contains("clean"));
    }

    @Test
    void nonRemoveActionCannotKeepSpecialPlanConflictByEnablingExemption() {
        for (String action : Arrays.asList("INITIAL", "FILL", "ADD", "REPLACE", "REFILL")) {
            CandidateFactDTO conflict = fact("conflict", "stable", "浙江", true, false, 100, 0);
            conflict.setSpecialPlanConflict(true);
            MutationPolicyDTO policy = policy(action, true);
            policy.setAllowExistingSpecialPlanConflicts(true);

            PlanSolverResultDTO result = solver.solve(snapshot(conflict), objectives(1), policy).solverResult;

            assertEquals("blocked", result.getStatus(), action);
        }
    }

    @Test
    void pureRemoveCannotAddNewItemsToMeetTarget() {
        CandidateFactDTO current = fact("current", "stable", "浙江", true, false, 10, 0);
        CandidateFactDTO added = fact("added", "protect", "浙江", false, false, 100, 1);
        MutationPolicyDTO policy = policy("REMOVE", true);
        policy.setAllowAdd(false);
        policy.setAllowExistingSpecialPlanConflicts(true);

        PlanSolverResultDTO result = solver.solve(snapshot(current, added), objectives(2), policy).solverResult;

        assertEquals("blocked", result.getStatus());
    }

    @Test
    void unknownSpecialPlanRequirementIsNotSelectableForNewSelection() {
        CandidateFactDTO unknown = fact("unknown", "sprint", "浙江", false, false, 100, 0);
        unknown.setSpecialPlanUnknown(true);
        CandidateFactDTO clean = fact("clean", "stable", "浙江", false, false, 10, 1);
        MutationPolicyDTO policy = policy("FILL", false);

        PlanSolverResultDTO result = solver.solve(snapshot(unknown, clean), objectives(1), policy).solverResult;

        assertEquals("ready", result.getStatus());
        assertFalse(result.getSelectedEntityIds().contains("unknown"));
        assertTrue(result.getSelectedEntityIds().contains("clean"));
    }

    @Test
    void pureRemoveMayKeepExistingSpecialPlanConflict() {
        CandidateFactDTO conflict = fact("conflict", "protect", "浙江", true, false, 100, 0);
        conflict.setSpecialPlanConflict(true);
        CandidateFactDTO clean = fact("clean", "stable", "浙江", true, false, 10, 1);
        MutationPolicyDTO policy = policy("REMOVE", false);
        policy.setAllowAdd(false);
        policy.setLockExisting(true);
        policy.setAllowExistingSpecialPlanConflicts(true);

        PlanSolverResultDTO result = solver.solve(snapshot(conflict, clean), objectives(2), policy).solverResult;

        assertEquals("ready", result.getStatus());
        assertTrue(result.getSelectedEntityIds().contains("conflict"));
        assertTrue(result.getSelectedEntityIds().contains("clean"));
    }

    @Test
    void safetyDeficitWinsOverZeroChurn() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a-current-protect", "protect", "江苏", true, false, 90, 0),
                fact("b-current-stable", "stable", "浙江", true, false, 90, 1),
                fact("c-local-protect", "protect", "浙江", false, false, 10, 2),
                fact("d-stable", "stable", "浙江", false, false, 10, 3));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        StructureTargetDTO target = new StructureTargetDTO();
        target.setMinLocalProtect(1);
        objectives.setStructureTarget(target);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives, policy("FILL", false));

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertTrue(result.solverResult.getSelectedEntityIds().contains("c-local-protect"));
        assertEquals(0L, level(result, "safety"));
        assertEquals(1, result.solverResult.getRemoveEntityIds().size());
        assertEquals(result.levels.size(), result.solverResult.getStageResults().size());
        PlanSolverResultDTO.StageResultDTO safetyStage = result.solverResult.getStageResults().stream()
                .filter(stage -> "safety".equals(stage.getObjectiveId())).findFirst().orElse(null);
        assertNotNull(safetyStage);
        assertEquals(0L, safetyStage.getValue());
        assertEquals("deficit_points", safetyStage.getUnit());
        assertNotNull(safetyStage.getDurationMs());
        assertTrue(safetyStage.getDurationMs() >= 0L);
        assertTrue(result.solverResult.getStageResults().stream()
                .anyMatch(stage -> "utility".equals(stage.getObjectiveId())));
    }

    @Test
    void churnWinsOverTierAnchor() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a-sprint", "sprint", "浙江", true, false, 90, 0),
                fact("b-stable", "stable", "浙江", true, false, 90, 1),
                fact("c-sprint", "sprint", "浙江", false, false, 90, 2),
                fact("d-stable", "stable", "浙江", false, false, 90, 3));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        TierCountsDTO anchor = new TierCountsDTO();
        anchor.setSprintCount(2);
        anchor.setStableCount(0);
        anchor.setProtectCount(0);
        StructureTargetDTO target = new StructureTargetDTO();
        target.setTierAnchor(anchor);
        objectives.setStructureTarget(target);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives, policy("FILL", false));

        assertEquals(Arrays.asList("a-sprint", "b-stable"), result.solverResult.getSelectedEntityIds());
        assertEquals(0L, level(result, "churn"));
        assertEquals(2L, level(result, "tier_anchor"));
    }

    @Test
    void utilitySelectsBestCandidatesWhenNoCurrentPlan() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a", "stable", "浙江", false, false, 30, 0),
                fact("b", "stable", "浙江", false, false, 90, 1),
                fact("c", "stable", "浙江", false, false, 60, 2));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives(2), policy("GENERATE", true));

        assertEquals(Arrays.asList("b", "c"), result.solverResult.getSelectedEntityIds());
        assertEquals(150L, level(result, "utility"));
    }

    @Test
    void addPolicyKeepsExistingAndRequiresFrozenTarget() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a", "stable", "浙江", true, true, 30, 0),
                fact("b", "stable", "浙江", false, false, 90, 1));
        MutationPolicyDTO policy = policy("ADD", true);
        policy.setFrozenRequiredEntityIds(new LinkedHashSet<String>(Arrays.asList("b")));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);

        StagedDeterministicPlanSolver.Result result = solver.solve(snapshot, objectives, policy);

        assertEquals(Arrays.asList("a", "b"), result.solverResult.getSelectedEntityIds());
        assertTrue(result.solverResult.getRemoveEntityIds().isEmpty());
    }

    @Test
    void forcedRemoveCannotOverrideLockedItem() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a", "stable", "浙江", true, true, 30, 0),
                fact("b", "stable", "浙江", false, false, 90, 1));
        MutationPolicyDTO policy = policy("REPLACE", true);
        policy.setForcedRemoveEntityIds(new LinkedHashSet<String>(Arrays.asList("a")));
        policy.setForcedAddEntityIds(new LinkedHashSet<String>(Arrays.asList("b")));

        StagedDeterministicPlanSolver.Result result = solver.solve(snapshot, objectives(2), policy);

        assertEquals("blocked", result.solverResult.getStatus());
        assertEquals("mutation_policy_conflict",
                result.solverResult.getDiagnostics().get(0).getReasonCode());
        assertTrue(result.solverResult.getStageResults().isEmpty());
    }

    @Test
    void countModeMismatchIsRejectedBeforeSolving() {
        CandidateSnapshotDTO snapshot = snapshot(fact("a", "stable", "浙江", false, false, 50, 0));
        snapshot.setCountMode("unit");
        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives(1), policy("GENERATE", true));
        assertEquals("blocked", result.solverResult.getStatus());
        assertEquals("solver_input_invalid",
                result.solverResult.getDiagnostics().get(0).getReasonCode());
    }

    @Test
    void fillPolicyExcludesCompensationUnsafeCandidates() {
        CandidateFactDTO unsafe = fact("unsafe", "stable", "浙江", false, false, 100, 0);
        unsafe.setCompensationSafe(false);
        CandidateFactDTO safe = fact("safe", "stable", "浙江", false, false, 10, 1);
        CandidateSnapshotDTO snapshot = snapshot(unsafe, safe);
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setRequireCompensationSafe(true);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives(1), policy);

        assertEquals("ready", result.solverResult.getStatus());
        assertEquals(Arrays.asList("safe"), result.solverResult.getSelectedEntityIds());
    }

    @Test
    void compensationSafeGateOnlyAppliesToNewAdditions() {
        CandidateFactDTO current = fact("current", "stable", "浙江", true, false, 10, 0);
        current.setCompensationSafe(false);
        CandidateFactDTO unsafeAdd = fact("unsafe-add", "stable", "浙江", false, false, 100, 1);
        unsafeAdd.setCompensationSafe(false);
        CandidateFactDTO safeAdd = fact("safe-add", "stable", "浙江", false, false, 50, 2);
        MutationPolicyDTO policy = policy("ADD", true);
        policy.setRequireCompensationSafe(true);
        policy.setFrozenRequiredEntityIds(new LinkedHashSet<String>(Arrays.asList("safe-add")));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(current, unsafeAdd, safeAdd), objectives(2), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertEquals(new LinkedHashSet<String>(Arrays.asList("current", "safe-add")),
                new LinkedHashSet<String>(result.solverResult.getSelectedEntityIds()));
    }

    @Test
    void largePoolUsesReducerInsteadOfComplexityBlock() {
        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        for (int index = 0; index < 620; index++) {
            facts.add(fact("f" + index, "stable", "浙江", false, false, 100 - index % 50, index));
        }
        CandidateSnapshotDTO snapshot = snapshot(facts.toArray(new CandidateFactDTO[0]));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives(2), policy("GENERATE", true));

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertTrue(result.solverResult.getCandidateCount() <= 600);
        assertTrue(result.solverResult.getDiagnostics().stream()
                .anyMatch(item -> "candidate_cap_applied".equals(item.getReasonCode())));
    }

    @Test
    void reducedPoolStillReportsRemovalOfCurrentFact() {
        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        for (int index = 0; index < 620; index++) {
            facts.add(fact("f" + index, "stable", "浙江", false, false, 100 - index % 50, index));
        }
        CandidateFactDTO current = fact("f619", "stable", "浙江", true, false, 0, 619);
        facts.set(619, current);
        CandidateSnapshotDTO snapshot = snapshot(facts.toArray(new CandidateFactDTO[0]));
        // 不启用 churn 优化，确保这条 current 不会被“少改动”阶段保下来，
        // 从而验证 reducer 降维后仍能报告它的移出。
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setCountAsChurn(false);

        StagedDeterministicPlanSolver.Result result = solver.solve(snapshot, objectives(2), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertTrue(result.solverResult.getRemoveEntityIds().contains("f619"),
                "remove=" + result.solverResult.getRemoveEntityIds()
                        + " selected=" + result.solverResult.getSelectedEntityIds()
                        + " levels=" + result.levels.stream()
                        .map(level -> level.level + ":" + level.value)
                        .collect(Collectors.joining(","))
                        + " candidateCount=" + result.solverResult.getCandidateCount()
                        + " diagnostics=" + result.solverResult.getDiagnostics());
    }

    @Test
    void exactTierAllocationReportsTierExactObjectiveType() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a", "sprint", "浙江", false, false, 90, 0),
                fact("b", "stable", "浙江", false, false, 90, 1));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO constraint =
                new com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO();
        constraint.setType("exact_counts");
        constraint.setSourceType("exact_counts");
        constraint.setSprintCount(1);
        constraint.setStableCount(1);
        constraint.setProtectCount(0);
        objectives.setTierAllocationConstraint(constraint);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives, policy("FILL", false));

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertTrue(result.solverResult.getObjectiveResults().stream()
                        .anyMatch(item -> "tier:sprint".equals(item.getObjectiveId())
                                && "tier_exact".equals(item.getObjectiveType())),
                "精确配额必须报 tier_exact，后置校验按同口径比对");
    }

    @Test
    void sameInputProducesSameSelectionAcrossRuns() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a", "stable", "浙江", false, false, 50, 0),
                fact("b", "stable", "浙江", false, false, 50, 1),
                fact("c", "stable", "浙江", false, false, 50, 2));
        List<String> first = null;
        for (int run = 0; run < 5; run++) {
            StagedDeterministicPlanSolver.Result result = solver.solve(
                    snapshot, objectives(2), policy("GENERATE", true));
            String selected = result.solverResult.getSelectedEntityIds().stream()
                    .collect(Collectors.joining(","));
            if (first == null) {
                first = new ArrayList<String>(result.solverResult.getSelectedEntityIds());
            } else {
                assertEquals(first.stream().collect(Collectors.joining(",")), selected);
            }
        }
        assertFalse(first.isEmpty());
    }

    @Test
    void softDiversityPrefersSpreadWhenUtilityEqual() {
        CandidateSnapshotDTO snapshot = snapshot(
                withUniqueDimensions(fact("a", "stable", "浙江", false, false, 50, 0)),
                withUniqueDimensions(fact("b", "stable", "浙江", false, false, 50, 1)),
                withUniqueDimensions(fact("c", "stable", "江苏", false, false, 50, 2)),
                withUniqueDimensions(fact("d", "stable", "江苏", false, false, 50, 3)));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        objectives.setDiversityPolicy(diversity("soft", 32));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives, policy("GENERATE", true));

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        // utility 同值：旧稳定序会选集中的 a,b；多样性必须换成跨省的 a,c。
        assertEquals(Arrays.asList("a", "c"), result.solverResult.getSelectedEntityIds());
        assertEquals(0L, level(result, "diversity"));
        assertEquals(100L, level(result, "utility"));
    }

    @Test
    void diversityOffKeepsLegacyStableSelection() {
        CandidateSnapshotDTO snapshot = snapshot(
                withUniqueDimensions(fact("a", "stable", "浙江", false, false, 50, 0)),
                withUniqueDimensions(fact("b", "stable", "浙江", false, false, 50, 1)),
                withUniqueDimensions(fact("c", "stable", "江苏", false, false, 50, 2)),
                withUniqueDimensions(fact("d", "stable", "江苏", false, false, 50, 3)));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        objectives.setDiversityPolicy(diversity("off", 32));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives, policy("GENERATE", true));

        assertEquals(Arrays.asList("a", "b"), result.solverResult.getSelectedEntityIds());
        assertTrue(result.levels.stream().noneMatch(item -> "diversity".equals(item.level)));

        // 默认 null 与显式 off 行为一致。
        objectives.setDiversityPolicy(null);
        StagedDeterministicPlanSolver.Result defaultOff = solver.solve(
                snapshot, objectives, policy("GENERATE", true));
        assertEquals(Arrays.asList("a", "b"), defaultOff.solverResult.getSelectedEntityIds());
        assertTrue(defaultOff.levels.stream().noneMatch(item -> "diversity".equals(item.level)));
    }

    @Test
    void diversityTruncatesGroupsAndEmitsDiagnostic() {
        CandidateSnapshotDTO snapshot = snapshot(
                withUniqueDimensions(fact("a", "stable", "浙江", false, false, 50, 0)),
                withUniqueDimensions(fact("b", "stable", "江苏", false, false, 50, 1)),
                withUniqueDimensions(fact("c", "stable", "安徽", false, false, 50, 2)),
                withUniqueDimensions(fact("d", "stable", "上海", false, false, 50, 3)));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(1);
        objectives.setDiversityPolicy(diversity("soft", 2));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives, policy("GENERATE", true));

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        PlanSolverResultDTO.DiagnosticDTO truncated = result.solverResult.getDiagnostics().stream()
                .filter(item -> "diversity_group_truncated".equals(item.getReasonCode()))
                .findFirst().orElse(null);
        assertTrue(truncated != null, "缺少 diversity_group_truncated 诊断");
        assertTrue(truncated.getMessage().contains("retained=2"), truncated.getMessage());
    }

    @Test
    void softDiversityIsDeterministicAcrossRuns() {
        CandidateSnapshotDTO snapshot = snapshot(
                withUniqueDimensions(fact("a", "stable", "浙江", false, false, 50, 0)),
                withUniqueDimensions(fact("b", "stable", "浙江", false, false, 50, 1)),
                withUniqueDimensions(fact("c", "stable", "江苏", false, false, 50, 2)),
                withUniqueDimensions(fact("d", "stable", "江苏", false, false, 50, 3)));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        objectives.setDiversityPolicy(diversity("soft", 32));

        StagedDeterministicPlanSolver.Result first = solver.solve(
                snapshot, objectives, policy("GENERATE", true));
        StagedDeterministicPlanSolver.Result second = solver.solve(
                snapshot, objectives, policy("GENERATE", true));

        assertEquals(first.solverResult.getSelectedEntityIds(),
                second.solverResult.getSelectedEntityIds());
        assertEquals(level(first, "diversity"), level(second, "diversity"));
    }

    @Test
    void softDiversityRecordsStageValue() {
        CandidateSnapshotDTO snapshot = snapshot(
                withUniqueDimensions(fact("a", "stable", "浙江", false, false, 50, 0)),
                withUniqueDimensions(fact("b", "stable", "浙江", false, false, 50, 1)),
                withUniqueDimensions(fact("c", "stable", "浙江", false, false, 50, 2)));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        objectives.setDiversityPolicy(diversity("soft", 32));

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot, objectives, policy("GENERATE", true));

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        // 全部同省，cap=ceil(0.4*2)=1；任选 2 条都至少超出 1。
        assertEquals(1L, level(result, "diversity"));
    }

    @Test
    void repeatedRunsProduceIdenticalSelectionOrderAndStageValues() {
        CandidateSnapshotDTO snapshot = snapshot(
                fact("a", "protect", "浙江", true, false, 90, 0),
                fact("b", "protect", "浙江", false, false, 90, 1),
                fact("c", "stable", "浙江", true, false, 80, 2),
                fact("d", "stable", "江苏", false, false, 80, 3),
                fact("e", "sprint", "浙江", true, false, 70, 4),
                fact("f", "sprint", "江苏", false, false, 70, 5),
                fact("g", "stable", "浙江", false, false, 60, 6),
                fact("h", "protect", "江苏", false, false, 60, 7));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(6);
        StructureTargetDTO target = new StructureTargetDTO();
        target.setMinLocalProtect(2);
        objectives.setStructureTarget(target);
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setCountAsChurn(true);

        String expected = solverSignature(solver.solve(snapshot, objectives, policy));
        for (int run = 0; run < 15; run++) {
            assertEquals(expected, solverSignature(solver.solve(snapshot, objectives, policy)),
                    "第 " + run + " 次重复求解必须逐字一致");
        }
    }

    @Test
    void candidateOrderPermutationDoesNotChangeSelection() {
        CandidateFactDTO[] facts = new CandidateFactDTO[]{
                fact("a", "protect", "浙江", true, false, 90, 0),
                fact("b", "stable", "浙江", true, false, 80, 1),
                fact("c", "stable", "江苏", false, false, 80, 2),
                fact("d", "sprint", "浙江", false, false, 70, 3),
                fact("e", "protect", "江苏", false, false, 60, 4)};
        CanonicalPlanningObjectiveSetDTO objectives = objectives(3);
        MutationPolicyDTO policy = policy("FILL", false);
        String expected = solverSignature(solver.solve(snapshot(facts), objectives, policy));

        List<CandidateFactDTO> shuffled = new ArrayList<CandidateFactDTO>(Arrays.asList(facts));
        java.util.Collections.shuffle(shuffled, new java.util.Random(42));
        String actual = solverSignature(solver.solve(
                snapshot(shuffled.toArray(new CandidateFactDTO[0])), objectives, policy));

        assertEquals(expected, actual, "候选输入顺序不能改变 stableOrder 语义");
    }

    @Test
    void candidateCapRepeatedRunsKeepSameSelection() {
        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        for (int index = 0; index < 620; index++) {
            facts.add(fact("f" + index, "stable", "浙江", index % 7 == 0, false,
                    100 - index % 50, index));
        }
        CandidateSnapshotDTO snapshot = snapshot(facts.toArray(new CandidateFactDTO[0]));
        CanonicalPlanningObjectiveSetDTO objectives = objectives(10);
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setCountAsChurn(true);

        String expected = solverSignature(solver.solve(snapshot, objectives, policy));
        for (int run = 0; run < 5; run++) {
            assertEquals(expected, solverSignature(solver.solve(snapshot, objectives, policy)),
                    "候选帽场景第 " + run + " 次求解必须逐字一致");
        }
    }

    private String solverSignature(StagedDeterministicPlanSolver.Result result) {
        return result.solverResult.getStatus() + "|"
                + result.solverResult.getSelectedEntityIds() + "|"
                + result.solverResult.getOrderedEntityIds() + "|"
                + result.solverResult.getStageResults().stream()
                .map(stage -> stage.getObjectiveId() + "=" + stage.getValue()
                        + "@" + stage.getUnit())
                .collect(Collectors.joining(","));
    }

    @Test
    void prioritySelectionStagePrefersMatchedEntity() {
        CandidateFactDTO current = fact("current", "stable", "浙江", true, false, 90, 0);
        CandidateFactDTO preferred = fact("preferred", "stable", "浙江", false, false, 10, 1);
        preferred.setPriorityMatched(true);
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setPrioritySelection(true);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(current, preferred), objectives(1), policy);

        assertEquals("ready", result.solverResult.getStatus(),
                "diagnostics=" + result.solverResult.getDiagnostics());
        assertEquals(Arrays.asList("preferred"), result.solverResult.getSelectedEntityIds());
        assertEquals(1L, level(result, "priority"));
    }

    @Test
    void prioritySelectionOffKeepsChurnBehavior() {
        CandidateFactDTO current = fact("current", "stable", "浙江", true, false, 90, 0);
        CandidateFactDTO preferred = fact("preferred", "stable", "浙江", false, false, 10, 1);
        preferred.setPriorityMatched(true);
        MutationPolicyDTO policy = policy("FILL", false);
        policy.setPrioritySelection(false);

        StagedDeterministicPlanSolver.Result result = solver.solve(
                snapshot(current, preferred), objectives(1), policy);

        assertEquals("ready", result.solverResult.getStatus());
        assertEquals(Arrays.asList("current"), result.solverResult.getSelectedEntityIds());
        assertTrue(result.levels.stream().noneMatch(item -> "priority".equals(item.level)));
    }

    private CandidateFactDTO withUniqueDimensions(CandidateFactDTO fact) {
        fact.setMajorCategoryId("major-" + fact.getEntityId());
        fact.setSchoolLevel("level-" + fact.getEntityId());
        return fact;
    }

    private DiversityPolicyDTO diversity(String mode, int maxGroups) {
        DiversityPolicyDTO policy = new DiversityPolicyDTO();
        policy.setMode(mode);
        policy.setMaxGroups(maxGroups);
        return policy;
    }

    private long level(StagedDeterministicPlanSolver.Result result, String name) {
        for (StagedDeterministicPlanSolver.ObjectiveLevel level : result.levels) {
            if (name.equals(level.level)) {
                return level.value;
            }
        }
        throw new AssertionError("missing level " + name);
    }

    private CandidateSnapshotDTO snapshot(CandidateFactDTO... facts) {
        CandidateSnapshotDTO snapshot = new CandidateSnapshotDTO();
        snapshot.setCountMode("volunteer");
        snapshot.setSourceProvince("浙江");
        snapshot.setFacts(new ArrayList<CandidateFactDTO>(Arrays.asList(facts)));
        return snapshot;
    }

    private CanonicalPlanningObjectiveSetDTO objectives(int targetCount) {
        CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
        objectives.setTargetCount(targetCount);
        objectives.setCountMode("volunteer");
        objectives.setObjectiveDigest("objective-" + targetCount);
        return objectives;
    }

    private MutationPolicyDTO policy(String action, boolean lockExisting) {
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction(action);
        policy.setLockExisting(lockExisting);
        return policy;
    }

    private CandidateFactDTO fact(String id,
                                  String tier,
                                  String province,
                                  boolean current,
                                  boolean locked,
                                  int utility,
                                  int stableOrder) {
        CandidateFactDTO fact = new CandidateFactDTO();
        fact.setEntityId(id);
        fact.setTier(tier);
        fact.setProvinceName(province);
        fact.setCurrent(current);
        fact.setLocked(locked);
        fact.setPinned(false);
        fact.setEligible(true);
        fact.setCompensationSafe(true);
        fact.setUnitAllSafe(true);
        fact.setUtilityScore(utility);
        fact.setUtilityCoverage(100);
        fact.setStableOrder(stableOrder);
        CandidateItemDTO raw = new CandidateItemDTO();
        raw.setVolunteerId(id);
        raw.setTier(tier);
        raw.setProvinceName(province);
        fact.setRawCandidates(new ArrayList<CandidateItemDTO>(Arrays.asList(raw)));
        return fact;
    }
}
