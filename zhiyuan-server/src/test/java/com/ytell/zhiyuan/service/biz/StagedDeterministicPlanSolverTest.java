package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.DiversityPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
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
