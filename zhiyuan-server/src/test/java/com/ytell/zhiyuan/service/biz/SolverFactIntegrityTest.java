package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SolverFactIntegrityTest {

    @AfterEach
    void clearFlag() {
        System.clearProperty(GroupInnerMajorOptimizationFlags.PROPERTY);
    }

    @Test
    void retainedLockedUnitCannotClaimCoverageFromUnselectedMajor() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        CandidateSnapshotDTO snapshot = workingSnapshot("数学", "法学");

        StagedDeterministicPlanSolver.Result result = solve(snapshot, "法学");

        assertFalse("ready".equals(result.solverResult.getStatus()));
        assertEquals(Collections.singletonList("u1_selected"),
                ids(snapshot.getFacts().get(0).getPlannedCandidates()));
    }

    @Test
    void retainedLockedUnitDoesNotLoseActualCoverageToReselection() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        CandidateSnapshotDTO snapshot = workingSnapshot("法学", "数学");

        StagedDeterministicPlanSolver.Result result = solve(snapshot, "法学");

        assertEquals("ready", result.solverResult.getStatus(),
                result.solverResult.getDiagnostics().toString());
        assertEquals(Collections.singletonList("u1_selected"),
                result.solverResult.getSelectedMajorIdsByUnit().get("u1"));
    }

    @Test
    void offModeCoverageAlsoUsesActualMajorsWithoutEnablingAPhaseTwoMap() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "off");

        assertFalse("ready".equals(solve(workingSnapshot("数学", "法学"), "法学")
                .solverResult.getStatus()));
        StagedDeterministicPlanSolver.Result covered = solve(workingSnapshot("法学", "数学"), "法学");

        assertEquals("ready", covered.solverResult.getStatus());
        assertTrue(covered.solverResult.getSelectedMajorIdsByUnit().isEmpty());
    }

    @Test
    void offModeBaselineUsesActualRiskItemsAndPreferredOnly() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "off");
        CandidateFactDTO fact = workingSnapshot("数学", "法学").getFacts().get(0);
        CandidateItemDTO unselected = fact.getRawCandidates().stream()
                .filter(candidate -> "u1_unselected".equals(candidate.getVolunteerId()))
                .findFirst().get();
        unselected.setRiskFlags(Arrays.asList("admission_limit"));
        unselected.setPreferred(true);

        assertEquals(0, InitialContentPolicySupport.riskCounts(Arrays.asList(fact))
                .getOrDefault("admission_limit", 0).intValue());
        assertEquals(1, InitialContentPolicySupport.itemCount(Arrays.asList(fact), true));
        assertEquals(0, InitialContentPolicySupport.preferredCount(Arrays.asList(fact)));
    }

    @Test
    void currentSourceSelectsWorkingOrderedOrUnionMajorsWithoutPoolExpansion() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "off");
        PlanningStateDTO state = state();
        CandidateItemDTO working = candidate("u1_working", "数学", 70D);
        CandidateItemDTO ordered = candidate("u1_ordered", "法学", 80D);
        CandidateItemDTO unselected = candidate("u1_unselected", "物理", 95D);
        state.getWorkingPlanState().getItems().add(draft(working));
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(ordered.getVolunteerId());
        unit.getMajorItems().add(major);
        state.getOrderedPlanState().getUnits().add(unit);
        List<CandidateItemDTO> pool = Arrays.asList(working, ordered, unselected);

        assertEquals(Collections.singletonList("u1_working"), ids(CandidateSnapshotBuilder.build(
                state, pool, CandidateSnapshotBuilder.CurrentSource.WORKING)
                .getFacts().get(0).getPlannedCandidates()));
        assertEquals(Collections.singletonList("u1_ordered"), ids(CandidateSnapshotBuilder.build(
                state, pool, CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST)
                .getFacts().get(0).getPlannedCandidates()));
        assertEquals(Arrays.asList("u1_working", "u1_ordered"), ids(CandidateSnapshotBuilder.build(
                state, pool, CandidateSnapshotBuilder.CurrentSource.UNION)
                .getFacts().get(0).getPlannedCandidates()));
    }

    @Test
    void missingCurrentMajorIsRetainedEvenWhenOtherGroupCandidatesExist() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        PlanningStateDTO state = state();
        state.getWorkingPlanState().getItems().add(draft(candidate("u1_missing", "法学", 70D)));

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(state,
                Arrays.asList(candidate("u1_unselected", "数学", 95D)),
                CandidateSnapshotBuilder.CurrentSource.WORKING);

        assertEquals(Collections.singletonList("u1_missing"),
                ids(snapshot.getFacts().get(0).getPlannedCandidates()));
        assertEquals("ready", solve(snapshot, "法学").solverResult.getStatus());
    }

    @Test
    void stageTwoUsesSnapshotPlanWhenPolicyRequiredCountIsMissing() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        PlanningStateDTO state = state();
        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(state, Arrays.asList(
                candidate("u1_first", "法学", 95D), candidate("u1_second", "数学", 80D)));

        StagedDeterministicPlanSolver.Result result = solve(snapshot, "法学");

        assertEquals("ready", result.solverResult.getStatus());
        assertEquals(ids(snapshot.getFacts().get(0).getPlannedCandidates()),
                result.solverResult.getSelectedMajorIdsByUnit().get("u1"));
        assertEquals(1, result.solverResult.getSelectedMajorIdsByUnit().get("u1").size());
    }

    @Test
    void workingFallbackPreservesKnownOrderedMajorContentWhenPoolLosesTheMajor() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "off");
        PlanningStateDTO state = state();
        state.getWorkingPlanState().getItems().add(draft(candidate("u1_missing", "法学", 70D)));
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setTier("稳");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId("u1_missing");
        major.setMajorName("法学");
        major.setTuitionPerYear(30000);
        major.setPreferred(true);
        unit.getMajorItems().add(major);
        state.getOrderedPlanState().getUnits().add(unit);

        CandidateFactDTO fact = CandidateSnapshotBuilder.build(state,
                Arrays.asList(candidate("u1_unselected", "数学", 95D)),
                CandidateSnapshotBuilder.CurrentSource.WORKING).getFacts().get(0);

        assertEquals(1, InitialContentPolicySupport.riskCounts(Arrays.asList(fact))
                .getOrDefault("high_tuition", 0).intValue());
        assertEquals(1, InitialContentPolicySupport.preferredCount(Arrays.asList(fact)));
    }

    @Test
    void retainedUnitKeepsEveryActualMajorEvenAboveTheNewUnitCap() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        PlanningStateDTO state = state();
        CandidateItemDTO first = candidate("u1_first", "法学", 70D);
        CandidateItemDTO second = candidate("u1_second", "数学", 80D);
        state.getWorkingPlanState().getItems().add(draft(first));
        state.getWorkingPlanState().getItems().add(draft(second));

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(state, Arrays.asList(first, second),
                CandidateSnapshotBuilder.CurrentSource.WORKING);

        assertEquals(Arrays.asList("u1_first", "u1_second"),
                solve(snapshot, "法学").solverResult.getSelectedMajorIdsByUnit().get("u1"));
        assertEquals(2, InitialContentPolicySupport.itemCount(snapshot.getFacts(), true));
    }

    @Test
    void compiledInitialPolicyKeepsActualCurrentMajorsAndExactNewUnitPlanAcrossCap() {
        System.setProperty(GroupInnerMajorOptimizationFlags.PROPERTY, "on");
        PlanningStateDTO state = state();
        state.getCandidatePoolState().setRequiredCount(2);
        state.getCandidatePoolState().setSourceProvinceName("北京");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(2);
        PriorityRuleDTO priority = new PriorityRuleDTO();
        priority.setDomain("region");
        priority.setKey("province");
        priority.setValues(Arrays.asList("上海"));
        priority.setScope("within_tier");
        priority.setOrderingTarget("rank_before");
        state.getConstraintState().getHardPlanningObjectives().setPriorityRules(Arrays.asList(priority));
        List<CandidateItemDTO> pool = new ArrayList<CandidateItemDTO>();
        CandidateItemDTO current = candidate("u1_selected", "数学", 70D);
        current.setPreferred(true);
        current.setProvinceName("北京");
        state.getWorkingPlanState().getItems().add(draft(current));
        pool.add(current);
        CandidateItemDTO unselected = candidate("u1_unselected", "数学", 99D);
        unselected.setRiskFlags(Arrays.asList("admission_limit"));
        pool.add(unselected);
        for (int index = 2; index <= 601; index++) {
            CandidateItemDTO addition = candidate("u" + index + "_selected", "法学", 90D);
            addition.setPlanSchoolDataId("u" + index);
            addition.setProvinceName(index == 601 ? "上海" : "北京");
            addition.setIntentScore(index == 601 ? 1D : 99D);
            if (index < 601) {
                addition.setRiskFlags(Arrays.asList("admission_limit"));
            }
            pool.add(addition);
        }
        state.getCandidatePoolState().setItems(pool);
        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                state, pool, CandidateSnapshotBuilder.CurrentSource.WORKING);
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("INITIAL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        policy.setInitialContentGuard(true);
        policy.setPrioritySelection(true);
        policy.setRequiredMajorCount(1);
        PlanningObjectiveCompiler.enrichV2(state, objectives, policy);

        StagedDeterministicPlanSolver.Result result = new StagedDeterministicPlanSolver()
                .solve(snapshot, objectives, policy);

        assertEquals("ready", result.solverResult.getStatus(), result.solverResult.getDiagnostics().toString());
        assertTrue(result.solverResult.getCandidateCount() <= 600);
        assertEquals(Arrays.asList("u1_selected"), result.solverResult.getSelectedMajorIdsByUnit().get("u1"));
        assertEquals(Arrays.asList("u601_selected"), result.solverResult.getSelectedMajorIdsByUnit().get("u601"));
        assertEquals(2, result.solverResult.getSelectedMajorIdsByUnit().size());
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            if (result.solverResult.getSelectedEntityIds().contains(fact.getEntityId())) {
                assertEquals(ids(fact.getPlannedCandidates()),
                        result.solverResult.getSelectedMajorIdsByUnit().get(fact.getEntityId()));
            }
        }
    }

    private CandidateSnapshotDTO workingSnapshot(String selectedMajor, String otherMajor) {
        PlanningStateDTO state = state();
        CandidateItemDTO selected = candidate("u1_selected", selectedMajor, 70D);
        state.getWorkingPlanState().getItems().add(draft(selected));
        return CandidateSnapshotBuilder.build(state, Arrays.asList(selected,
                candidate("u1_unselected", otherMajor, 95D)),
                CandidateSnapshotBuilder.CurrentSource.WORKING);
    }

    private PlanningStateDTO state() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredMajorCount(1);
        return state;
    }

    private DraftItemDTO draft(CandidateItemDTO candidate) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(candidate.getVolunteerId());
        item.setMajorName(candidate.getMajorName());
        item.setSchoolName(candidate.getSchoolName());
        item.setTier(candidate.getTier());
        item.setLocked(true);
        return item;
    }

    private CandidateItemDTO candidate(String volunteerId, String major, Double ratio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId("u1");
        candidate.setSchoolName("学校");
        candidate.setMajorName(major);
        candidate.setTier("稳");
        candidate.setSchoolEnrollRatio(60D);
        candidate.setAdmissionRatio(ratio);
        candidate.setIntentScore(50D);
        candidate.setFinalScore(50D);
        candidate.setTuitionPerYear(5000);
        return candidate;
    }

    private StagedDeterministicPlanSolver.Result solve(CandidateSnapshotDTO snapshot, String major) {
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("major");
        coverage.setKey("major");
        coverage.setValues(Arrays.asList(major));
        coverage.setMinCount(1);
        CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
        objectives.setTargetCount(1);
        objectives.setCountMode("unit");
        objectives.setCoverageConstraints(Arrays.asList(coverage));
        return new StagedDeterministicPlanSolver().solve(snapshot, objectives, new MutationPolicyDTO());
    }

    private List<String> ids(List<CandidateItemDTO> candidates) {
        return candidates.stream().map(CandidateItemDTO::getVolunteerId).collect(Collectors.toList());
    }
}
