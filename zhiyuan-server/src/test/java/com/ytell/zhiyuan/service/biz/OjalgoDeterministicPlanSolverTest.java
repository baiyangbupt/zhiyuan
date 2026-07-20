package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverInputDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OjalgoDeterministicPlanSolverTest {

    private final DeterministicPlanSolver solver = new OjalgoDeterministicPlanSolver();

    @Test
    void shouldMinimizeChurnWhileMeetingSharedCoverage() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 2);
        objectives.getCoverageConstraints().add(coverage("region", "province", 2, "上海"));
        objectives.setObjectiveDigest("objective-coverage");
        PlanSolverInputDTO input = input(objectives,
                candidate("a", 0, true, "sprint", true, "coverage:0"),
                candidate("b", 1, true, "stable", false),
                candidate("c", 2, false, "protect", true, "coverage:0"),
                candidate("d", 3, false, "protect", true, "coverage:0"));

        PlanSolverResultDTO result = solver.solve(input);

        assertEquals("ready", result.getStatus(),
                "solverState=" + result.getSolverState() + " diagnostics=" + result.getDiagnostics());
        assertEquals(Arrays.asList("a", "c"), result.getSelectedEntityIds());
        assertEquals(Arrays.asList("b"), result.getRemoveEntityIds());
        assertEquals(Arrays.asList("c"), result.getAddEntityIds());
        assertTrue(result.getObjectiveResults().stream().allMatch(item -> Boolean.TRUE.equals(item.getSatisfied())));
    }

    @Test
    void shouldSolveExactTierCountsWithoutSyntheticCoverage() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 3);
        objectives.setTierAllocationConstraint(quota(1, 1, 1));
        objectives.setObjectiveDigest("objective-tier");
        PlanSolverInputDTO input = input(objectives,
                candidate("sprint-current", 0, true, "sprint", true),
                candidate("stable-current", 1, true, "stable", true),
                candidate("stable-extra", 2, true, "stable", true),
                candidate("protect-first", 3, false, "protect", true),
                candidate("protect-second", 4, false, "protect", true));

        PlanSolverResultDTO result = solver.solve(input);

        assertEquals("ready", result.getStatus(),
                "solverState=" + result.getSolverState() + " diagnostics=" + result.getDiagnostics());
        assertEquals(Arrays.asList("sprint-current", "stable-current", "protect-first"),
                result.getSelectedEntityIds());
        assertEquals("ojalgo-48.4.2-m2", result.getSolverVersion());
        assertTrue(result.getInputDigest().matches("[0-9a-f]{64}"));
    }

    @Test
    void shouldKeepCurrentCountsWhenTheyAlreadySatisfyMaxOnly() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 4);
        objectives.setTierAllocationConstraint(bounds(0, 2, 0, 4, 0, 4));

        PlanSolverResultDTO result = solver.solve(input(objectives,
                candidate("s1", 0, true, "sprint", true),
                candidate("t1", 1, true, "stable", true),
                candidate("t2", 2, true, "stable", true),
                candidate("p1", 3, true, "protect", true)));

        assertEquals("no_change", result.getStatus());
        assertEquals(Integer.valueOf(1), result.getResolvedTierCounts().getSprintCount());
        assertEquals(counts(1, 2, 1), result.getHistoricalTierAnchor());
        assertTrue(result.getObjectiveResults().stream()
                .filter(item -> "tier_range".equals(item.getObjectiveType()))
                .allMatch(item -> Boolean.TRUE.equals(item.getSatisfied())));
    }

    @Test
    void shouldMeetMinimumByReplacingTheFewestCurrentCandidates() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 4);
        objectives.setTierAllocationConstraint(bounds(1, 4, 0, 4, 0, 4));

        PlanSolverResultDTO result = solver.solve(input(objectives,
                candidate("t1", 0, true, "stable", true),
                candidate("t2", 1, true, "stable", true),
                candidate("t3", 2, true, "stable", true),
                candidate("p1", 3, true, "protect", true),
                candidate("s1", 4, false, "sprint", true)));

        assertEquals("ready", result.getStatus());
        assertEquals(Arrays.asList("t3"), result.getRemoveEntityIds());
        assertEquals(Arrays.asList("s1"), result.getAddEntityIds());
        assertEquals(Integer.valueOf(1), result.getResolvedTierCounts().getSprintCount());
    }

    @Test
    void shouldReturnTypedTierCapacityDiagnosticsForRanges() {
        CanonicalPlanningObjectiveSetDTO capacityObjectives = objectives("volunteer", 4);
        capacityObjectives.setTierAllocationConstraint(bounds(0, 1, 0, 4, 0, 4));
        PlanSolverResultDTO capacity = solver.solve(input(capacityObjectives,
                candidate("s1", 0, true, "sprint", true),
                candidate("s2", 1, true, "sprint", true),
                candidate("s3", 2, true, "sprint", true),
                candidate("t1", 3, true, "stable", true)));

        assertEquals("blocked", capacity.getStatus());
        assertEquals("tier_max_infeasible", capacity.getDiagnostics().get(0).getReasonCode());

        CanonicalPlanningObjectiveSetDTO minimumObjectives = objectives("volunteer", 3);
        minimumObjectives.setTierAllocationConstraint(bounds(2, 3, 0, 3, 0, 3));
        PlanSolverResultDTO minimum = solver.solve(input(minimumObjectives,
                candidate("s1", 0, true, "sprint", true),
                candidate("t1", 1, true, "stable", true),
                candidate("p1", 2, true, "protect", true)));

        assertEquals("tier_min_infeasible", minimum.getDiagnostics().get(0).getReasonCode());
    }

    @Test
    void shouldBlockWhenLockedCountExceedsTierMaximum() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 2);
        objectives.setTierAllocationConstraint(bounds(0, 1, 0, 2, 0, 2));
        PlanSolverInputDTO.CandidateDTO first = candidate("s1", 0, true, "sprint", true);
        first.setLocked(true);
        PlanSolverInputDTO.CandidateDTO second = candidate("s2", 1, true, "sprint", true);
        second.setLocked(true);

        PlanSolverResultDTO result = solver.solve(input(objectives, first, second,
                candidate("t1", 2, false, "stable", true)));

        assertEquals("blocked", result.getStatus());
        assertEquals("locked_conflict", result.getDiagnostics().get(0).getReasonCode());
        assertEquals("tier:sprint", result.getDiagnostics().get(0).getObjectiveId());
    }

    @Test
    void shouldSolveRatioResolutionAsExactBounds() {
        TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                null, ratioRequest(3, 4, 3), 10);
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 10);
        objectives.setTierAllocationConstraint(compiled.getConstraint());
        List<PlanSolverInputDTO.CandidateDTO> candidates = IntStream.range(0, 12)
                .mapToObj(index -> candidate("candidate-" + index, index, index < 10,
                        tier(index), true))
                .collect(Collectors.toList());

        PlanSolverResultDTO result = solver.solve(input(
                objectives, candidates.toArray(new PlanSolverInputDTO.CandidateDTO[0])));

        assertEquals("ready", result.getStatus());
        assertEquals(counts(3, 4, 3), result.getResolvedTierCounts());
        assertEquals(3, result.getObjectiveResults().stream()
                .filter(item -> "tier_exact".equals(item.getObjectiveType())).count());
    }

    @Test
    void shouldUseHardRangesWhenHistoricalAnchorIsUnreachable() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 4);
        objectives.setTierAllocationConstraint(bounds(0, 2, 0, 2, 0, 4));

        PlanSolverResultDTO result = solver.solve(input(objectives,
                candidate("s1", 0, true, "sprint", true),
                candidate("s2", 1, true, "sprint", true),
                candidate("t-ineligible", 2, true, "stable", false),
                candidate("t1", 3, true, "stable", true),
                candidate("p1", 4, false, "protect", true),
                candidate("p2", 5, false, "protect", true)));

        assertEquals("ready", result.getStatus(), String.valueOf(result.getDiagnostics()));
        assertEquals(counts(2, 1, 1), result.getResolvedTierCounts());
        assertEquals(counts(2, 2, 0), result.getHistoricalTierAnchor());
    }

    @Test
    void shouldTreatMajorGroupCandidateAsOneSelectionEntity() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("unit", 2);
        objectives.setObjectiveDigest("objective-unit");
        PlanSolverInputDTO.CandidateDTO current = candidate("unit-a", 0, true, "stable", true);
        current.setVolunteerIds(Arrays.asList("a-1", "a-2"));
        PlanSolverInputDTO.CandidateDTO addition = candidate("unit-b", 1, false, "protect", true);
        addition.setVolunteerIds(Arrays.asList("b-1", "b-2", "b-3"));

        PlanSolverResultDTO result = solver.solve(input(objectives, current, addition));

        assertEquals(Arrays.asList("unit-a", "unit-b"), result.getSelectedEntityIds());
        assertEquals(2, result.getSelectedEntityIds().size());
        assertEquals(1, result.getAddEntityIds().size());
    }

    @Test
    void shouldApplySinglePriorityAsStablePartitionWithinTier() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 4);
        objectives.getOrderingConstraints().add(priority("region", "province", "上海"));
        objectives.setObjectiveDigest("objective-priority");
        PlanSolverInputDTO.CandidateDTO target = candidate(
                "stable-target", 1, true, "stable", true);
        target.setPriorityMatched(true);
        PlanSolverInputDTO input = input(objectives,
                candidate("stable-other-1", 0, true, "stable", true),
                target,
                candidate("protect-other", 2, true, "protect", true),
                candidate("stable-other-2", 3, true, "stable", true));

        PlanSolverResultDTO result = solver.solve(input);

        assertEquals("ready", result.getStatus(),
                "solverState=" + result.getSolverState() + " diagnostics=" + result.getDiagnostics());
        assertEquals(Arrays.asList("stable-target", "stable-other-1", "protect-other", "stable-other-2"),
                result.getOrderedEntityIds());
        assertTrue(result.getAddEntityIds().isEmpty());
        assertTrue(result.getRemoveEntityIds().isEmpty());
    }

    @Test
    void shouldReturnTypedBlockedResultsForLockedConflictAndCandidateShortage() {
        CanonicalPlanningObjectiveSetDTO lockedObjectives = objectives("volunteer", 1);
        lockedObjectives.setTierAllocationConstraint(quota(0, 0, 1));
        lockedObjectives.setObjectiveDigest("objective-locked");
        PlanSolverInputDTO.CandidateDTO locked = candidate("locked-sprint", 0, true, "sprint", true);
        locked.setLocked(true);

        PlanSolverResultDTO lockedResult = solver.solve(input(lockedObjectives, locked,
                candidate("protect", 1, false, "protect", true)));

        assertEquals("blocked", lockedResult.getStatus());
        assertEquals("locked_conflict", lockedResult.getDiagnostics().get(0).getReasonCode());

        CanonicalPlanningObjectiveSetDTO shortageObjectives = objectives("volunteer", 3);
        shortageObjectives.setObjectiveDigest("objective-shortage");
        PlanSolverResultDTO shortage = solver.solve(input(shortageObjectives,
                candidate("a", 0, true, "stable", true),
                candidate("b", 1, false, "protect", false)));

        assertEquals("blocked", shortage.getStatus());
        assertEquals("candidate_shortage", shortage.getDiagnostics().get(0).getReasonCode());
    }

    @Test
    void shouldAttributeCoverageConflictToLockedSlot() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 1);
        objectives.getCoverageConstraints().add(coverage("major", "major", 1, "法学"));
        objectives.setObjectiveDigest("objective-locked-coverage");
        PlanSolverInputDTO.CandidateDTO locked = candidate(
                "locked-non-match", 0, true, "stable", true);
        locked.setLocked(true);

        PlanSolverResultDTO result = solver.solve(input(objectives, locked,
                candidate("available-match", 1, false, "stable", true, "coverage:0")));

        assertEquals("blocked", result.getStatus());
        assertEquals("locked_conflict", result.getDiagnostics().get(0).getReasonCode());
        assertEquals("coverage:0", result.getDiagnostics().get(0).getObjectiveId());
    }

    @Test
    void shouldReturnComplexityLimitBeforeBuildingUnboundedModel() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 48);
        objectives.setObjectiveDigest("objective-complexity");
        List<PlanSolverInputDTO.CandidateDTO> candidates = IntStream.range(0, 601)
                .mapToObj(index -> candidate("candidate-" + index, index, index < 48, tier(index), true))
                .collect(Collectors.toList());
        PlanSolverInputDTO input = new PlanSolverInputDTO();
        input.setObjectiveSet(objectives);
        input.setCandidates(candidates);

        PlanSolverResultDTO result = solver.solve(input);

        assertEquals("blocked", result.getStatus());
        assertEquals("solver_complexity_limit", result.getDiagnostics().get(0).getReasonCode());
        assertEquals(601, result.getCandidateCount());
    }

    @Test
    void shouldBlockInvalidCandidateFactsInsteadOfThrowingDuringCanonicalSort() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 1);
        objectives.setObjectiveDigest("objective-invalid-fact");
        PlanSolverInputDTO input = new PlanSolverInputDTO();
        input.setObjectiveSet(objectives);
        input.setCandidates(Arrays.asList(
                candidate("duplicate", 0, true, "stable", true),
                null,
                candidate("duplicate", 1, false, "protect", true)));

        PlanSolverResultDTO result = solver.solve(input);

        assertEquals("blocked", result.getStatus());
        assertEquals("candidate_fact_invalid", result.getDiagnostics().get(0).getReasonCode());
    }

    @Test
    void shouldBlockUnknownTierWhenPriorityRequiresCanonicalTierFacts() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 1);
        objectives.getOrderingConstraints().add(priority("region", "province", "上海"));
        objectives.setObjectiveDigest("objective-unknown-tier");

        PlanSolverResultDTO result = solver.solve(input(objectives,
                candidate("unknown", 0, true, "超稳", true)));

        assertEquals("blocked", result.getStatus());
        assertEquals("candidate_tier_invalid", result.getDiagnostics().get(0).getReasonCode());
    }

    @Test
    void shouldBeDeterministicWhenTransportCandidateOrderChanges() {
        CanonicalPlanningObjectiveSetDTO objectives = objectives("volunteer", 2);
        objectives.setTierAllocationConstraint(bounds(0, 1, 0, 2, 0, 2));
        objectives.setObjectiveDigest("objective-deterministic");
        List<PlanSolverInputDTO.CandidateDTO> candidates = new ArrayList<PlanSolverInputDTO.CandidateDTO>(Arrays.asList(
                candidate("a", 0, true, "stable", true),
                candidate("b", 1, false, "protect", true),
                candidate("c", 2, false, "protect", true)));
        PlanSolverResultDTO first = solver.solve(input(objectives,
                candidates.toArray(new PlanSolverInputDTO.CandidateDTO[0])));
        Collections.reverse(candidates);
        PlanSolverResultDTO second = solver.solve(input(objectives,
                candidates.toArray(new PlanSolverInputDTO.CandidateDTO[0])));

        assertEquals(first.getSelectedEntityIds(), second.getSelectedEntityIds());
        assertEquals(first.getOrderedEntityIds(), second.getOrderedEntityIds());
        assertEquals(first.getResolvedTierCounts(), second.getResolvedTierCounts());
        assertEquals(first.getHistoricalTierAnchor(), second.getHistoricalTierAnchor());
        assertEquals(first.getInputDigest(), second.getInputDigest());
    }

    private CanonicalPlanningObjectiveSetDTO objectives(String countMode, int targetCount) {
        CanonicalPlanningObjectiveSetDTO result = new CanonicalPlanningObjectiveSetDTO();
        result.setCountMode(countMode);
        result.setTargetCount(targetCount);
        return result;
    }

    private PlanSolverInputDTO input(CanonicalPlanningObjectiveSetDTO objectives,
                                     PlanSolverInputDTO.CandidateDTO... candidates) {
        PlanSolverInputDTO result = new PlanSolverInputDTO();
        result.setObjectiveSet(objectives);
        result.setCandidates(Arrays.asList(candidates));
        return result;
    }

    private PlanSolverInputDTO.CandidateDTO candidate(String id,
                                                      int stableOrder,
                                                      boolean current,
                                                      String tier,
                                                      boolean eligible,
                                                      String... matches) {
        PlanSolverInputDTO.CandidateDTO result = new PlanSolverInputDTO.CandidateDTO();
        result.setEntityId(id);
        result.setVolunteerIds(Arrays.asList(id));
        result.setStableOrder(stableOrder);
        result.setCurrent(current);
        result.setEligible(eligible);
        result.setTier(tier);
        result.setCoverageObjectiveIds(Arrays.asList(matches));
        result.setPriorityMatched(matches.length == 0 ? false : Arrays.asList(matches).contains("priority"));
        return result;
    }

    private CoverageRequirementDTO coverage(String domain, String key, int minCount, String... values) {
        CoverageRequirementDTO result = new CoverageRequirementDTO();
        result.setDomain(domain);
        result.setKey(key);
        result.setValues(Arrays.asList(values));
        result.setMinCount(minCount);
        return result;
    }

    private TierAllocationConstraintDTO quota(int sprint, int stable, int protect) {
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType("exact_counts");
        result.setSprintCount(sprint);
        result.setStableCount(stable);
        result.setProtectCount(protect);
        return result;
    }

    private TierAllocationConstraintDTO bounds(int sprintMin,
                                               int sprintMax,
                                               int stableMin,
                                               int stableMax,
                                               int protectMin,
                                               int protectMax) {
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType("count_ranges");
        result.setSourceType("count_ranges");
        result.setSprint(bound(sprintMin, sprintMax));
        result.setStable(bound(stableMin, stableMax));
        result.setProtect(bound(protectMin, protectMax));
        return result;
    }

    private TierCountRangeDTO bound(int min, int max) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        result.setMinCount(min);
        result.setMaxCount(max);
        return result;
    }

    private TierCountsDTO counts(int sprint, int stable, int protect) {
        TierCountsDTO result = new TierCountsDTO();
        result.setSprintCount(sprint);
        result.setStableCount(stable);
        result.setProtectCount(protect);
        return result;
    }

    private com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO ratioRequest(
            int sprint,
            int stable,
            int protect) {
        com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO result =
                new com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO();
        result.setType("ratios");
        result.setUpdateMode("replace");
        result.setSprintWeight(sprint);
        result.setStableWeight(stable);
        result.setProtectWeight(protect);
        return result;
    }

    private PriorityRuleDTO priority(String domain, String key, String value) {
        PriorityRuleDTO result = new PriorityRuleDTO();
        result.setDomain(domain);
        result.setKey(key);
        result.setValues(Arrays.asList(value));
        result.setOrderingTarget("rank_before");
        result.setScope("within_tier");
        return result;
    }

    private String tier(int index) {
        return Arrays.asList("sprint", "stable", "protect").get(index % 3);
    }
}
