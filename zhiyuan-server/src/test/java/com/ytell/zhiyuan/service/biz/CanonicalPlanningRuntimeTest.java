package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CanonicalPlanningRuntimeTest {

    @Test
    void shouldRestorePersistedSelectionTargetWithoutOtherObjectives() {
        PlanningStateDTO state = state("major", 48);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(2);
        CandidateItemDTO current = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO addition = candidate("v2", "u2", "法学", "保", "上海", 89D);
        state.getCandidatePoolState().setItems(Arrays.asList(current, addition));
        state.getWorkingPlanState().getItems().add(draft(current, false));

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceSelection(
                state, state.getCandidatePoolState().getItems());

        assertEquals("ready", result.getStatus());
        assertEquals(Arrays.asList("v1", "v2"), result.getSelectedEntityIds());
        assertEquals(new java.util.HashSet<String>(Arrays.asList("v1", "v2")), draftIds(state));
    }

    @Test
    void shouldSolveCoverageAndExactTierInOneSelection() {
        PlanningStateDTO state = state("major", 3);
        CandidateItemDTO sprintOne = candidate("v1", "u1", "数学", "冲", "北京", 90D);
        CandidateItemDTO sprintTwo = candidate("v2", "u2", "物理学", "sprint", "天津", 89D);
        CandidateItemDTO stable = candidate("v3", "u3", "金融学", "稳", "江苏", 88D);
        CandidateItemDTO protectLaw = candidate("v4", "u4", "法学", "保底", "上海", 87D);
        state.getCandidatePoolState().getItems().addAll(
                Arrays.asList(sprintOne, sprintTwo, stable, protectLaw));
        state.getWorkingPlanState().getItems().add(draft(sprintOne, false));
        state.getWorkingPlanState().getItems().add(draft(sprintTwo, false));
        state.getWorkingPlanState().getItems().add(draft(stable, false));
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements()
                .add(requirement("major", "major", "法学", 1));
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota(1, 1, 1));

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceSelection(
                state, state.getCandidatePoolState().getItems());

        assertEquals("ready", result.getStatus());
        assertEquals(Arrays.asList("v1", "v3", "v4"), result.getSelectedEntityIds());
        assertEquals(new java.util.HashSet<String>(Arrays.asList("v1", "v3", "v4")), draftIds(state));
        assertEquals(1, result.getObjectiveResults().stream()
                .filter(item -> "coverage".equals(item.getObjectiveType())).count());
        assertEquals(3, result.getObjectiveResults().stream()
                .filter(item -> "tier_exact".equals(item.getObjectiveType())).count());
    }

    @Test
    void shouldUseCanonicalTargetCountForPersistedRanges() {
        PlanningStateDTO state = state("major", 48);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(3);
        CandidateItemDTO sprint = candidate("v1", "u1", "数学", "冲", "北京", 90D);
        CandidateItemDTO stable = candidate("v2", "u2", "金融学", "稳", "江苏", 89D);
        CandidateItemDTO protect = candidate("v3", "u3", "法学", "保", "上海", 88D);
        state.getCandidatePoolState().setItems(Arrays.asList(sprint, stable, protect));
        state.getWorkingPlanState().getItems().add(draft(sprint, false));
        state.getWorkingPlanState().getItems().add(draft(stable, false));
        state.getWorkingPlanState().getItems().add(draft(protect, false));
        TierQuotaGoalDTO ranges = new TierQuotaGoalDTO();
        ranges.setType("count_ranges");
        ranges.setSprint(bound(0, 1));
        ranges.setStable(bound(0, 1));
        ranges.setProtect(bound(0, 1));
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(ranges);

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceSelection(
                state, state.getCandidatePoolState().getItems());

        assertEquals("no_change", result.getStatus());
        assertEquals(Integer.valueOf(1), result.getResolvedTierCounts().getSprintCount());
        assertEquals(3, result.getObjectiveResults().stream()
                .filter(item -> "tier_range".equals(item.getObjectiveType())).count());
    }

    @Test
    void shouldReplaceCompleteMajorGroupAsOneEntity() {
        PlanningStateDTO state = state("majorGroup", 1);
        CandidateItemDTO math = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO physics = candidate("v2", "u1", "物理学", "稳", "北京", 85D);
        CandidateItemDTO law = candidate("v3", "u2", "法学", "保", "上海", 95D);
        CandidateItemDTO politics = candidate("v4", "u2", "政治学", "保", "上海", 80D);
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(math, physics, law, politics));
        state.getWorkingPlanState().getItems().add(draft(math, false));
        state.getWorkingPlanState().getItems().add(draft(physics, false));
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements()
                .add(requirement("major", "major", "法学", 1));

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceSelection(
                state, state.getCandidatePoolState().getItems());

        assertEquals(Arrays.asList("u2"), result.getSelectedEntityIds());
        assertEquals(new java.util.HashSet<String>(Arrays.asList("v3", "v4")), draftIds(state));
        assertEquals(1, state.getWorkingPlanState().getUnits().size());
        assertEquals("u2", state.getWorkingPlanState().getUnits().get(0).getUnitId());
    }

    @Test
    void shouldApplyCanonicalPriorityOrderWithoutChangingSelection() {
        PlanningStateDTO state = state("major", 4);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO v2 = candidate("v2", "u2", "法学", "稳", "上海", 89D);
        CandidateItemDTO v3 = candidate("v3", "u3", "金融学", "稳", "天津", 88D);
        CandidateItemDTO v4 = candidate("v4", "u4", "会计学", "稳", "上海", 87D);
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v2, v3, v4);
        state.getCandidatePoolState().setItems(candidates);
        for (CandidateItemDTO candidate : candidates) {
            state.getOrderedPlanState().getItems().add(ordered(candidate));
        }
        PriorityRuleSupport.persist(state, Arrays.asList(priority("上海")));

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceOrdering(state, candidates);

        assertEquals(Arrays.asList("v2", "v4", "v1", "v3"), result.getOrderedEntityIds());
        assertEquals(result.getOrderedEntityIds(), state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));
        assertEquals("hard_priority_rank_before", state.getOrderedPlanState().getItems().get(0).getOrderReason());
    }

    @Test
    void shouldReturnTypedBusinessErrorWithoutPartialMutationOnPinnedConflict() {
        PlanningStateDTO state = state("major", 2);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO v2 = candidate("v2", "u2", "法学", "稳", "上海", 89D);
        state.getCandidatePoolState().setItems(Arrays.asList(v1, v2));
        OrderedItemDTO pinned = ordered(v1);
        pinned.setPinned(true);
        state.getOrderedPlanState().getItems().add(pinned);
        state.getOrderedPlanState().getItems().add(ordered(v2));
        PriorityRuleSupport.persist(state, Arrays.asList(priority("上海")));

        BusinessException error = assertThrows(BusinessException.class,
                () -> CanonicalPlanningRuntime.enforceOrdering(
                        state, state.getCandidatePoolState().getItems()));

        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("pinned_conflict"));
        assertEquals(Arrays.asList("v1", "v2"), state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));
    }

    @Test
    void shouldOrderCompleteMajorGroupWithoutChangingInnerMajorOrder() {
        PlanningStateDTO state = state("majorGroup", 2);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO v1b = candidate("v1b", "u1", "物理学", "稳", "北京", 89D);
        CandidateItemDTO v2 = candidate("v2", "u2", "法学", "稳", "上海", 88D);
        CandidateItemDTO v2b = candidate("v2b", "u2", "政治学", "稳", "上海", 87D);
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v1b, v2, v2b);
        state.getCandidatePoolState().setItems(candidates);
        state.getOrderedPlanState().getUnits().add(unit("u1", "北京", "v1", "v1b"));
        state.getOrderedPlanState().getUnits().add(unit("u2", "上海", "v2", "v2b"));
        state.getOrderedPlanState().getItems().addAll(candidates.stream()
                .map(this::ordered).collect(Collectors.toList()));
        PriorityRuleSupport.persist(state, Arrays.asList(priority("上海")));

        CanonicalPlanningRuntime.enforceOrdering(state, candidates);

        assertEquals(Arrays.asList("u2", "u1"), state.getOrderedPlanState().getUnits().stream()
                .map(OrderedUnitDTO::getUnitId).collect(Collectors.toList()));
        assertEquals(Arrays.asList("v2", "v2b", "v1", "v1b"),
                state.getOrderedPlanState().getItems().stream()
                        .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));
    }

    @Test
    void shouldBlockMajorGroupWithConflictingTierFacts() {
        PlanningStateDTO state = state("majorGroup", 1);
        CandidateItemDTO sprint = candidate("v1", "u1", "数学", "冲", "北京", 90D);
        CandidateItemDTO stable = candidate("v2", "u1", "物理学", "稳", "北京", 89D);
        state.getCandidatePoolState().setItems(Arrays.asList(sprint, stable));
        state.getWorkingPlanState().getItems().add(draft(sprint, false));
        state.getWorkingPlanState().getItems().add(draft(stable, false));
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota(1, 0, 0));

        BusinessException error = assertThrows(BusinessException.class,
                () -> CanonicalPlanningRuntime.enforceSelection(
                        state, state.getCandidatePoolState().getItems()));

        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("tier_fact_conflict"));
    }

    @Test
    void shouldRejectUnknownTierForPriorityExecution() {
        PlanningStateDTO state = state("major", 2);
        CandidateItemDTO unknown = candidate("v1", "u1", "数学", "超稳", "北京", 90D);
        CandidateItemDTO stable = candidate("v2", "u2", "法学", "稳", "上海", 89D);
        state.getCandidatePoolState().setItems(Arrays.asList(unknown, stable));
        state.getOrderedPlanState().getItems().add(ordered(unknown));
        state.getOrderedPlanState().getItems().add(ordered(stable));
        PriorityRuleSupport.persist(state, Arrays.asList(priority("上海")));

        BusinessException error = assertThrows(BusinessException.class,
                () -> CanonicalPlanningRuntime.enforceOrdering(
                        state, state.getCandidatePoolState().getItems()));

        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("priority_tier_unavailable"));
    }

    @Test
    void shouldAnalyzeMixedTierAliasesAsOnePriorityGroup() {
        PlanningStateDTO state = state("major", 2);
        CandidateItemDTO unmatched = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO matched = candidate("v2", "u2", "法学", "stable", "上海", 89D);
        state.getCandidatePoolState().setItems(Arrays.asList(unmatched, matched));
        state.getOrderedPlanState().getItems().add(ordered(unmatched));
        state.getOrderedPlanState().getItems().add(ordered(matched));
        PriorityRuleDTO priority = priority("上海");
        PriorityRuleSupport.persist(state, Arrays.asList(priority));

        PriorityRuleSupport.Analysis before = PriorityRuleSupport.analyze(
                state, state.getCandidatePoolState().getItems(), priority);

        assertEquals(1, before.getInversionCount());
        CanonicalPlanningRuntime.enforceOrdering(state, state.getCandidatePoolState().getItems());
        assertEquals(Arrays.asList("v2", "v1"), state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));
        assertEquals(0, PriorityRuleSupport.analyze(
                state, state.getCandidatePoolState().getItems(), priority).getInversionCount());
    }

    @Test
    void shouldDegradeToNoChangeWhenStoredPriorityMissesEveryPlanItemDuringRegeneration() {
        PlanningStateDTO state = state("major", 2);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO v2 = candidate("v2", "u2", "法学", "稳", "上海", 89D);
        state.getCandidatePoolState().setItems(Arrays.asList(v1, v2));
        state.getOrderedPlanState().getItems().add(ordered(v1));
        state.getOrderedPlanState().getItems().add(ordered(v2));
        PriorityRuleSupport.persist(state, Arrays.asList(priority("天津")));

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceOrdering(
                state, state.getCandidatePoolState().getItems(), false);

        assertEquals("no_change", result.getStatus());
        assertEquals(Arrays.asList("v1", "v2"), state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));

        BusinessException error = assertThrows(BusinessException.class,
                () -> CanonicalPlanningRuntime.enforceOrdering(
                        state, state.getCandidatePoolState().getItems()));
        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("priority_target_not_in_plan"));
    }

    @Test
    void shouldDegradeToNoChangeForEmptyOrderedPlanDuringRegeneration() {
        PlanningStateDTO state = state("major", 2);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        state.getCandidatePoolState().setItems(Arrays.asList(v1));
        PriorityRuleSupport.persist(state, Arrays.asList(priority("上海")));

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceOrdering(
                state, state.getCandidatePoolState().getItems(), false);

        assertEquals("no_change", result.getStatus());
        BusinessException error = assertThrows(BusinessException.class,
                () -> CanonicalPlanningRuntime.enforceOrdering(
                        state, state.getCandidatePoolState().getItems()));
        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("priority_target_not_in_plan: 当前没有正式方案"));
    }

    @Test
    void shouldApplyAndVerifyFrozenSelectionAndOrder() {
        PlanningStateDTO state = state("major", 2);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(2);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO v2 = candidate("v2", "u2", "法学", "稳", "北京", 89D);
        CandidateItemDTO v3 = candidate("v3", "u3", "金融学", "稳", "上海", 88D);
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v2, v3);
        state.getCandidatePoolState().setItems(candidates);
        state.getWorkingPlanState().getItems().add(draft(v1, false));
        state.getWorkingPlanState().getItems().add(draft(v2, false));
        PlanSolverResultDTO frozen = frozenResult(
                Arrays.asList("v1", "v3"), Arrays.asList("v3", "v1"),
                Arrays.asList("v2"), Arrays.asList("v3"));

        CanonicalPlanningRuntime.applyFrozenSelection(state, candidates, frozen);

        assertEquals(Arrays.asList("v1", "v3"), state.getWorkingPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId).collect(Collectors.toList()));
        state.getOrderedPlanState().getItems().add(ordered(v1));
        state.getOrderedPlanState().getItems().add(ordered(v3));
        CanonicalPlanningRuntime.applyFrozenOrdering(state, frozen);
        CanonicalPlanningRuntime.verifyFrozenState(state, frozen);
        assertEquals(Arrays.asList("v3", "v1"), state.getOrderedPlanState().getItems().stream()
                .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList()));
    }

    @Test
    void shouldApplyFrozenUnitSelectionWhenCurrentVolunteerUsesLegacyIdentity() {
        PlanningStateDTO state = state("majorGroup", 2);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(2);
        CandidateItemDTO currentFact = candidate(
                "u1_canonical-major-id", "u1", "数学", "稳", "北京", 90D);
        currentFact.setTuitionPerYear(32000);
        CandidateItemDTO addition = candidate(
                "u2_canonical-major-id", "u2", "法学", "保", "上海", 89D);
        List<CandidateItemDTO> candidates = Arrays.asList(currentFact, addition);
        state.getCandidatePoolState().setItems(candidates);
        DraftItemDTO legacyCurrent = draft(currentFact, false);
        legacyCurrent.setVolunteerId("u1_legacy-major-id");
        state.getWorkingPlanState().getItems().add(legacyCurrent);
        PlanSolverResultDTO frozen = frozenResult(
                Arrays.asList("u1", "u2"), Arrays.asList("u1", "u2"),
                Arrays.asList(), Arrays.asList("u2"));

        CanonicalPlanningRuntime.applyFrozenSelection(state, candidates, frozen);

        assertEquals(new java.util.HashSet<String>(Arrays.asList(
                        "u1_legacy-major-id", "u2_canonical-major-id")),
                draftIds(state));
        assertEquals(Arrays.asList("u1", "u2"), state.getWorkingPlanState().getUnits().stream()
                .map(unit -> unit.getUnitId()).collect(Collectors.toList()));
    }

    @Test
    void shouldApplyFrozenSelectionWhenWorkingOrderDiffersFromFrozenOrder() {
        PlanningStateDTO state = state("major", 3);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(3);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO v2 = candidate("v2", "u2", "法学", "稳", "北京", 89D);
        CandidateItemDTO v3 = candidate("v3", "u3", "金融学", "稳", "上海", 88D);
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v2, v3);
        state.getCandidatePoolState().setItems(candidates);
        state.getWorkingPlanState().getItems().add(draft(v1, false));
        state.getWorkingPlanState().getItems().add(draft(v2, false));
        PlanSolverResultDTO frozen = frozenResult(
                Arrays.asList("v2", "v1", "v3"), Arrays.asList("v2", "v1", "v3"),
                Arrays.asList(), Arrays.asList("v3"));

        CanonicalPlanningRuntime.applyFrozenSelection(state, candidates, frozen);
        CanonicalPlanningRuntime.verifyFrozenWorkingSelection(state, candidates, frozen);

        assertEquals(new java.util.HashSet<String>(Arrays.asList("v1", "v2", "v3")),
                draftIds(state));
    }

    @Test
    void shouldRejectFrozenResultWhoseSelectedCandidateIsMissing() {
        PlanningStateDTO state = state("major", 2);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(2);
        CandidateItemDTO v1 = candidate("v1", "u1", "数学", "稳", "北京", 90D);
        CandidateItemDTO v2 = candidate("v2", "u2", "法学", "稳", "北京", 89D);
        CandidateItemDTO v3 = candidate("v3", "u3", "金融学", "稳", "上海", 88D);
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v2, v3);
        state.getCandidatePoolState().setItems(candidates);
        state.getWorkingPlanState().getItems().add(draft(v1, false));
        state.getWorkingPlanState().getItems().add(draft(v2, false));
        PlanSolverResultDTO frozen = frozenResult(
                Arrays.asList("v1", "missing"), Arrays.asList("v1", "missing"),
                Arrays.asList("v2"), Arrays.asList("missing"));

        BusinessException error = assertThrows(BusinessException.class,
                () -> CanonicalPlanningRuntime.applyFrozenSelection(state, candidates, frozen));

        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("solver_frozen_candidate_missing"));
        assertEquals(Arrays.asList("v1", "v2"), state.getWorkingPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId).collect(Collectors.toList()));
    }

    private PlanningStateDTO state(String volunteerModel, int targetCount) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(12);
        state.getCandidatePoolState().setVolunteerModel(volunteerModel);
        state.getCandidatePoolState().setRequiredCount(targetCount);
        return state;
    }

    private CandidateItemDTO candidate(String volunteerId,
                                       String unitId,
                                       String major,
                                       String tier,
                                       String province,
                                       Double score) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setSchoolName("学校-" + unitId);
        candidate.setMajorName(major);
        candidate.setTier(tier);
        candidate.setProvinceName(province);
        candidate.setIntentScore(score);
        candidate.setFinalScore(score);
        return candidate;
    }

    private DraftItemDTO draft(CandidateItemDTO candidate, boolean locked) {
        return WorkingPlanMutationSupport.buildWorkingPlanItem(candidate, "test", locked);
    }

    private OrderedItemDTO ordered(CandidateItemDTO candidate) {
        OrderedItemDTO result = new OrderedItemDTO();
        result.setVolunteerId(candidate.getVolunteerId());
        result.setSchoolName(candidate.getSchoolName());
        result.setMajorName(candidate.getMajorName());
        result.setTier(candidate.getTier());
        result.setPinned(false);
        return result;
    }

    private CoverageRequirementDTO requirement(String domain,
                                               String key,
                                               String value,
                                               int minCount) {
        CoverageRequirementDTO result = new CoverageRequirementDTO();
        result.setDomain(domain);
        result.setKey(key);
        result.setValues(Arrays.asList(value));
        result.setMinCount(minCount);
        return result;
    }

    private TierQuotaGoalDTO quota(int sprint, int stable, int protect) {
        TierQuotaGoalDTO result = new TierQuotaGoalDTO();
        result.setType("exact_counts");
        result.setSprintCount(sprint);
        result.setStableCount(stable);
        result.setProtectCount(protect);
        return result;
    }

    private TierCountRangeDTO bound(int min, int max) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        result.setMinCount(min);
        result.setMaxCount(max);
        return result;
    }

    private PriorityRuleDTO priority(String province) {
        PriorityRuleDTO result = new PriorityRuleDTO();
        result.setDomain("region");
        result.setKey("province");
        result.setValues(Arrays.asList(province));
        result.setOrderingTarget("rank_before");
        result.setScope("within_tier");
        return result;
    }

    private PlanSolverResultDTO frozenResult(List<String> selected,
                                             List<String> ordered,
                                             List<String> removed,
                                             List<String> added) {
        PlanSolverResultDTO result = new PlanSolverResultDTO();
        result.setStatus("ready");
        result.setSelectedEntityIds(selected);
        result.setOrderedEntityIds(ordered);
        result.setRemoveEntityIds(removed);
        result.setAddEntityIds(added);
        result.setSolverVersion("ojalgo-48.4.2-m1");
        result.setInputDigest("input-digest");
        return result;
    }

    private OrderedUnitDTO unit(String id, String province, String... volunteerIds) {
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId(id);
        unit.setTier("稳");
        unit.setProvinceName(province);
        unit.setSchoolName(province + "学校");
        for (String volunteerId : volunteerIds) {
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(volunteerId);
            major.setMajorName("专业" + volunteerId);
            unit.getMajorItems().add(major);
        }
        return unit;
    }

    private Set<String> draftIds(PlanningStateDTO state) {
        return state.getWorkingPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
    }
}
