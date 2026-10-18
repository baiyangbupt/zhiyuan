package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PlanningObjectiveCompilerTest {

    @Test
    void shouldProduceStableDigestForEquivalentRequirementOrder() {
        PlanningStateDTO state = state("major", 12, 45);
        UserGoalFixProposalReq first = fillRequest(45);
        first.getRequirements().add(requirement("include", "region", "province", 2, " 上海 ", "江苏"));
        first.getRequirements().add(requirement("exclude", "school", "school_nature", 1, "民办"));

        UserGoalFixProposalReq second = fillRequest(45);
        second.getRequirements().add(requirement("exclude", "SCHOOL", " SCHOOL_NATURE ", 1, " 民办 "));
        second.getRequirements().add(requirement("INCLUDE", "REGION", "PROVINCE", 2, "江苏", "上海"));

        CanonicalPlanningObjectiveSetDTO left = PlanningObjectiveCompiler.compile(state, first);
        CanonicalPlanningObjectiveSetDTO right = PlanningObjectiveCompiler.compile(state, second);

        assertEquals("4.1.0-m2", left.getSchemaVersion());
        assertEquals("volunteer", left.getCountMode());
        assertEquals(45, left.getTargetCount());
        assertEquals(left.getObjectiveDigest(), right.getObjectiveDigest());
        assertTrue(left.getObjectiveDigest().matches("[0-9a-f]{64}"));
        assertEquals(left.getEligibilityConstraints(), right.getEligibilityConstraints());
        assertEquals(left.getCoverageConstraints(), right.getCoverageConstraints());
    }

    @Test
    void shouldKeepExactTierAllocationSeparateFromCoverage() {
        PlanningStateDTO state = state("majorGroup", 21, 3);
        UserGoalFixProposalReq request = fillRequest(3);
        request.setTierQuotaGoal(quotaRequest(1, 1, 1));

        CanonicalPlanningObjectiveSetDTO result = PlanningObjectiveCompiler.compile(state, request);

        assertEquals("unit", result.getCountMode());
        assertTrue(result.getCoverageConstraints().isEmpty());
        assertNotNull(result.getTierAllocationConstraint());
        assertEquals("exact_counts", result.getTierAllocationConstraint().getType());
        assertEquals(1, result.getTierAllocationConstraint().getSprintCount());
        assertEquals(1, result.getTierAllocationConstraint().getStableCount());
        assertEquals(1, result.getTierAllocationConstraint().getProtectCount());
    }

    @Test
    void shouldCompilePersistedFourZeroObjectivesWithoutRequest() {
        PlanningStateDTO state = state("major", 7, 4);
        HardConstraintsDTO hard = state.getConstraintState().getHardConstraints();
        hard.getMustExcludeRegions().add("上海");
        hard.getMustIncludeMajors().add("专业类:计算机类");

        HardPlanningObjectivesDTO objectives = state.getConstraintState().getHardPlanningObjectives();
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("region");
        coverage.setKey("province");
        coverage.setValues(Arrays.asList("江苏"));
        coverage.setMinCount(2);
        objectives.getCoverageRequirements().add(coverage);
        objectives.setTierQuotaGoal(quota(1, 2, 1));
        objectives.getPriorityRules().add(priority("region", "province", "江苏"));

        CanonicalPlanningObjectiveSetDTO result = PlanningObjectiveCompiler.compileConfirmed(state);

        assertEquals(7, result.getSourceVersion());
        assertEquals(4, result.getTargetCount());
        assertEquals(Arrays.asList("上海"), result.getEligibilityConstraints().getMustExcludeRegions());
        assertEquals(Arrays.asList("专业类:计算机类"), result.getEligibilityConstraints().getMustIncludeMajors());
        assertEquals(1, result.getCoverageConstraints().size());
        assertEquals(2, result.getCoverageConstraints().get(0).getMinCount());
        assertEquals(1, result.getOrderingConstraints().size());
        assertEquals("江苏", result.getOrderingConstraints().get(0).getValues().get(0));
        assertEquals("exact_counts", result.getTierAllocationGoal().getType());
        assertEquals(Integer.valueOf(1), result.getTierAllocationConstraint().getSprintCount());
    }

    @Test
    void shouldPreserveSinglePriorityOrderAndDropRawTextFromDigest() {
        PlanningStateDTO state = state("major", 3, 2);
        UserGoalFixProposalReq first = new UserGoalFixProposalReq();
        first.setGoalType("prioritize_within_tier");
        first.setSourceVersionGuard(3);
        PriorityRuleDTO firstRule = priority("region", "province", "上海");
        firstRule.setRawText("上海的放前面");
        first.getPriorityRules().add(firstRule);

        UserGoalFixProposalReq second = new UserGoalFixProposalReq();
        second.setGoalType("PRIORITIZE_WITHIN_TIER");
        second.setSourceVersionGuard(3);
        PriorityRuleDTO secondRule = priority("REGION", "PROVINCE", " 上海 ");
        secondRule.setRawText("换一种说法也不应影响 canonical digest");
        second.getPriorityRules().add(secondRule);

        CanonicalPlanningObjectiveSetDTO left = PlanningObjectiveCompiler.compile(state, first);
        CanonicalPlanningObjectiveSetDTO right = PlanningObjectiveCompiler.compile(state, second);

        assertEquals(left.getObjectiveDigest(), right.getObjectiveDigest());
        assertEquals(1, left.getOrderingConstraints().size());
        assertEquals("rank_before", left.getOrderingConstraints().get(0).getOrderingTarget());
        assertEquals("within_tier", left.getOrderingConstraints().get(0).getScope());
        assertEquals(null, left.getOrderingConstraints().get(0).getRawText());
    }

    @Test
    void shouldKeepConfirmedSelectionTargetForPriorityOnlyObjective() {
        PlanningStateDTO state = state("major", 3, 50);
        OrderedItemDTO first = new OrderedItemDTO();
        first.setVolunteerId("v1");
        OrderedItemDTO second = new OrderedItemDTO();
        second.setVolunteerId("v2");
        state.getOrderedPlanState().getItems().add(first);
        state.getOrderedPlanState().getItems().add(second);
        UserGoalFixProposalReq request = new UserGoalFixProposalReq();
        request.setGoalType("prioritize_within_tier");
        request.setSourceVersionGuard(3);
        request.getPriorityRules().add(priority("region", "province", "上海"));

        CanonicalPlanningObjectiveSetDTO result = PlanningObjectiveCompiler.compile(state, request);

        assertEquals(50, result.getTargetCount());
    }

    @Test
    void shouldKeepDigestStableAfterPersistingPriorityOnlyObjective() {
        PlanningStateDTO state = state("major", 3, 50);
        UserGoalFixProposalReq request = new UserGoalFixProposalReq();
        request.setGoalType("prioritize_within_tier");
        request.setSourceVersionGuard(3);
        request.getPriorityRules().add(priority("region", "province", "广东"));

        CanonicalPlanningObjectiveSetDTO preview = PlanningObjectiveCompiler.compile(state, request);
        PriorityRuleSupport.persist(state, request.getPriorityRules());

        CanonicalPlanningObjectiveSetDTO persisted = PlanningObjectiveCompiler.compileConfirmed(state);

        assertEquals(preview.getObjectiveDigest(), persisted.getObjectiveDigest());
    }

    @Test
    void shouldKeepDigestStableAfterPersistingContextOnlyTarget() {
        PlanningStateDTO state = state("majorGroup", 12, 48);
        UserGoalFixProposalReq request = fillRequest(45);
        request.setPersistTargetCount(false);
        request.getRequirements().add(requirement(
                "include", "region", "province", 3, "山东"));
        request.getPriorityRules().add(priority("region", "province", "山东"));

        CanonicalPlanningObjectiveSetDTO preview = PlanningObjectiveCompiler.compile(state, request);
        ProjectedHardRequirementSupport.persist(state, request.getRequirements());
        PriorityRuleSupport.persist(state, request.getPriorityRules());
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(45);

        CanonicalPlanningObjectiveSetDTO persisted = PlanningObjectiveCompiler.compileConfirmed(state);

        assertEquals(preview.getObjectiveDigest(), persisted.getObjectiveDigest());
    }

    @Test
    void shouldFailClosedForTierQuotaCompositeBeforeM3() {
        PlanningStateDTO state = state("major", 9, 3);
        UserGoalFixProposalReq request = fillRequest(3);
        request.setTierQuotaGoal(quotaRequest(1, 1, 1));
        request.getRequirements().add(requirement("include", "region", "province", 1, "上海"));

        PlanningObjectiveCompiler.CompilationException error = assertThrows(
                PlanningObjectiveCompiler.CompilationException.class,
                () -> PlanningObjectiveCompiler.compile(state, request));

        assertEquals("tier_quota_composite_not_supported", error.getReasonCode());
    }

    @Test
    void shouldCanonicalizeEquivalentRatioWeightsToOneDigest() {
        PlanningStateDTO state = state("major", 12, 45);
        UserGoalFixProposalReq first = fillRequest(45);
        first.setTierQuotaGoal(ratio(3, 4, 3));
        UserGoalFixProposalReq second = fillRequest(45);
        second.setTierQuotaGoal(ratio(30, 40, 30));

        CanonicalPlanningObjectiveSetDTO left = PlanningObjectiveCompiler.compile(state, first);
        CanonicalPlanningObjectiveSetDTO right = PlanningObjectiveCompiler.compile(state, second);

        assertEquals(left.getObjectiveDigest(), right.getObjectiveDigest());
        assertEquals(Integer.valueOf(14), left.getTierAllocationResolution()
                .getResolvedCounts().getSprintCount());
        assertEquals(Integer.valueOf(18), left.getTierAllocationResolution()
                .getResolvedCounts().getStableCount());
        assertEquals(Integer.valueOf(13), left.getTierAllocationResolution()
                .getResolvedCounts().getProtectCount());
    }

    @Test
    void shouldBlockNewTierGoalWhenConfirmedCoverageExistsBeforeM3() {
        PlanningStateDTO state = state("major", 12, 45);
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements().add(
                coverage("region", "province", 2, "上海"));
        UserGoalFixProposalReq request = fillRequest(45);
        request.setTierQuotaGoal(ratio(3, 4, 3));

        PlanningObjectiveCompiler.CompilationException error = assertThrows(
                PlanningObjectiveCompiler.CompilationException.class,
                () -> PlanningObjectiveCompiler.compile(state, request));

        assertEquals("tier_quota_composite_not_supported", error.getReasonCode());
    }

    @Test
    void shouldBlockNewRequirementWhenConfirmedTierGoalExistsBeforeM3() {
        PlanningStateDTO state = state("major", 12, 45);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota(9, 17, 19));
        UserGoalFixProposalReq request = fillRequest(45);
        request.getRequirements().add(requirement("include", "region", "province", 2, "上海"));

        PlanningObjectiveCompiler.CompilationException error = assertThrows(
                PlanningObjectiveCompiler.CompilationException.class,
                () -> PlanningObjectiveCompiler.compile(state, request));

        assertEquals("tier_quota_composite_not_supported", error.getReasonCode());
    }

    @Test
    void shouldBlockNewPriorityWhenConfirmedTierGoalExistsBeforeM3() {
        PlanningStateDTO state = state("major", 12, 45);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota(9, 17, 19));
        UserGoalFixProposalReq request = new UserGoalFixProposalReq();
        request.setGoalType("prioritize_within_tier");
        request.getPriorityRules().add(priority("region", "province", "上海"));

        PlanningObjectiveCompiler.CompilationException error = assertThrows(
                PlanningObjectiveCompiler.CompilationException.class,
                () -> PlanningObjectiveCompiler.compile(state, request));

        assertEquals("tier_quota_composite_not_supported", error.getReasonCode());
    }

    @Test
    void shouldMapTierAllocationContractErrorsWithoutChangingReasonCode() {
        PlanningStateDTO state = state("major", 12, 45);
        UserGoalFixProposalReq request = fillRequest(45);
        request.setTierQuotaGoal(quotaRequest(9, 17, 18));

        PlanningObjectiveCompiler.CompilationException error = assertThrows(
                PlanningObjectiveCompiler.CompilationException.class,
                () -> PlanningObjectiveCompiler.compile(state, request));

        assertEquals("tier_exact_total_mismatch", error.getReasonCode());
    }

    @Test
    void enrichV2AddsStructureAndMutationPolicyWithoutTouchingLegacyDigest() {
        PlanningStateDTO state = state("major", 12, 45);
        state.getCandidatePoolState().setUserScore(550);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        String legacyDigest = objectives.getObjectiveDigest();
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);

        PlanningObjectiveCompiler.enrichV2(state, objectives, policy);

        assertEquals("4.2.0-j53", objectives.getSchemaVersion());
        assertEquals(2, objectives.getStructureTarget().getMinLocalProtect());
        assertEquals("FILL", objectives.getMutationPolicy().getAction());
        assertEquals(StagedDeterministicPlanSolver.HARD_OBJECTIVE_VERSION,
                objectives.getHardObjectiveVersion());
        assertEquals(64, objectives.getObjectiveDigest().length());
        assertTrue(!legacyDigest.equals(objectives.getObjectiveDigest()));
    }

    @Test
    void enrichV2AddsSoftDiversityPolicyOnlyWhenEnabled() {
        String previous = System.getProperty("solver.v2.diversity");
        try {
            PlanningStateDTO state = state("major", 12, 45);
            state.getCandidatePoolState().setUserScore(550);
            state.getCandidatePoolState().setSourceProvinceName("浙江");
            MutationPolicyDTO policy = new MutationPolicyDTO();
            policy.setAction("FILL");
            policy.setLockExisting(false);
            policy.setCountAsChurn(true);

            System.setProperty("solver.v2.diversity", "false");
            CanonicalPlanningObjectiveSetDTO off = PlanningObjectiveCompiler.compileConfirmed(state);
            PlanningObjectiveCompiler.enrichV2(state, off, policy);
            assertNull(off.getDiversityPolicy());

            System.setProperty("solver.v2.diversity", "true");
            CanonicalPlanningObjectiveSetDTO on = PlanningObjectiveCompiler.compileConfirmed(state);
            PlanningObjectiveCompiler.enrichV2(state, on, policy);

            assertNotNull(on.getDiversityPolicy());
            assertEquals("soft", on.getDiversityPolicy().getMode());
            assertEquals(0.4D, on.getDiversityPolicy().getRegionShare(), 0.0001D);
            assertEquals(0.4D, on.getDiversityPolicy().getMajorCategoryShare(), 0.0001D);
            assertEquals(0.6D, on.getDiversityPolicy().getSchoolLevelShare(), 0.0001D);
            assertEquals(Integer.valueOf(32), on.getDiversityPolicy().getMaxGroups());
            // diversityPolicy 不在 digest 白名单内：开关不改变冻结值。
            assertEquals(off.getObjectiveDigest(), on.getObjectiveDigest());
        } finally {
            if (previous == null) {
                System.clearProperty("solver.v2.diversity");
            } else {
                System.setProperty("solver.v2.diversity", previous);
            }
        }
    }

    private PlanningStateDTO state(String volunteerModel, int version, int requiredCount) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(version);
        state.setConstraintState(new ConstraintStateDTO());
        CandidatePoolStateDTO candidatePool = new CandidatePoolStateDTO();
        candidatePool.setVolunteerModel(volunteerModel);
        candidatePool.setRequiredCount(requiredCount);
        state.setCandidatePoolState(candidatePool);
        return state;
    }

    private UserGoalFixProposalReq fillRequest(int targetCount) {
        UserGoalFixProposalReq request = new UserGoalFixProposalReq();
        request.setGoalType("fill_to_count");
        request.setTargetCount(targetCount);
        request.setSourceVersionGuard(12);
        return request;
    }

    private UserGoalFixProposalReq.RequirementDTO requirement(String kind,
                                                              String domain,
                                                              String key,
                                                              int minCount,
                                                              String... values) {
        UserGoalFixProposalReq.RequirementDTO result = new UserGoalFixProposalReq.RequirementDTO();
        result.setKind(kind);
        result.setDomain(domain);
        result.setKey(key);
        result.setMinCount(minCount);
        result.setValues(Arrays.asList(values));
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

    private TierQuotaGoalRequestDTO quotaRequest(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        result.setType("exact_counts");
        result.setSprintCount(sprint);
        result.setStableCount(stable);
        result.setProtectCount(protect);
        return result;
    }

    private TierQuotaGoalRequestDTO ratio(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        result.setType("ratios");
        result.setUpdateMode("replace");
        result.setSprintWeight(sprint);
        result.setStableWeight(stable);
        result.setProtectWeight(protect);
        return result;
    }

    private CoverageRequirementDTO coverage(String domain,
                                            String key,
                                            int minCount,
                                            String... values) {
        CoverageRequirementDTO result = new CoverageRequirementDTO();
        result.setDomain(domain);
        result.setKey(key);
        result.setMinCount(minCount);
        result.setValues(Arrays.asList(values));
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
}
