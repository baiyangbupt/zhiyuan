package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class ReviewCommandCompilationTest {
    private final ReviewEvaluationMapper mapper = new ReviewEvaluationMapper();

    @Test
    void compilesAbsoluteCountTargetAndDisplayDeltaAfterFinalStatusIsKnown() {
        EvaluationContextDTO context = context(42);
        context.setSelectionTargetCount(45);
        EvaluationFindingDTO finding = finding("count_target", context, "count_validation", "count_below_target");

        assertNotNull(finding.getObjectiveDelta());
        assertEquals(3, finding.getObjectiveDelta().getTargetCountDelta());
        JSONObject command = command(finding);
        assertEquals(45, command.getInteger("targetCount"));
        assertEquals("fill_missing_count", command.getString("strategy"));
        assertEquals("apply_plan_change_proposal", command.getString("commandType"));
        assertFalse(command.getBooleanValue("executable"));
        assertTrue(command.getBooleanValue("requiresConfirmation"));
        assertNotNull(command.getString("evaluationVersion"));
        assertNotNull(command.getString("commandDigest"));
    }

    @Test
    void missingOfficialCountDoesNotProduceCommandButKnownShortfallDoes() {
        EvaluationContextDTO context = context(2);
        EvaluationFindingDTO unknown = finding("count_validation_hard", context, "count_validation", null);
        assertEquals("unknown", unknown.getResultStatus());
        assertNull(unknown.getObjectiveDelta());
        assertNull(unknown.getSuggestedCommand());

        context.setRequiredCount(5);
        EvaluationFindingDTO shortfall = finding("count_validation_hard", context, "count_validation", "count_missing");
        assertEquals(5, command(shortfall).getInteger("targetCount"));
    }

    @Test
    void derivedSafetyProducesEffectiveAbsoluteFloorWithoutRemovingMatchedProtects() {
        EvaluationContextDTO context = context(3);
        context.setSourceProvince("浙江");
        context.setSafetyFloorMode("applicable");
        context.setSafetyMinLocalProtect(2);
        context.getEntries().get(0).setPathTier("protect");
        context.getEntries().get(0).setProvinceName("浙江");

        JSONObject command = command(finding("safety_guard", context, "count_validation", "count_missing"));
        assertEquals(2, command.getInteger("safetyMinLocalProtect"));
        assertTrue(command.getJSONArray("forcedRemoveTargets").isEmpty());
        assertNull(command.getJSONObject("constraintPatch"));
        assertEquals(2, context.getSafetyMinLocalProtect());
    }

    @Test
    void ratioRepairPreservesConfirmedRangesRatherThanInventingExactQuotas() {
        EvaluationContextDTO context = context(5);
        TierAllocationConstraintDTO constraint = new TierAllocationConstraintDTO();
        constraint.setType("range");
        constraint.setSprint(range(0, 1));
        constraint.setStable(range(2, 4));
        constraint.setProtect(range(1, 3));
        context.setTierConstraint(constraint);

        JSONObject command = command(finding("ratio_distribution", context, "count_validation", "count_missing"));
        assertEquals(2, command.getJSONObject("tierConstraint").getJSONObject("stable").getInteger("minCount"));
        assertTrue(command.getJSONObject("tierTargetCounts").isEmpty());
        assertEquals("range", context.getTierConstraint().getType());
        assertNull(context.getTierConstraint().getStableCount());
    }

    @Test
    void coverageCanonicalizationMergesEquivalentRequirementsAndIgnoresValueOrder() {
        EvaluationContextDTO context = context(3);
        CoverageRequirementDTO first = coverage(1, "浙江", "江苏");
        CoverageRequirementDTO second = coverage(2, "江苏", "浙江");
        context.setCoverageRequirements(Lists.newArrayList(first, second));
        EvaluationFindingDTO finding = finding("coverage:0", context, "count_validation", "count_missing");
        JSONObject command = command(finding);
        assertEquals(1, command.getJSONArray("coverageRequirements").size());
        assertEquals(2, command.getJSONArray("coverageRequirements").getJSONObject(0).getInteger("minCount"));
        String digest = command.getString("commandDigest");

        context.setCoverageRequirements(Lists.newArrayList(second, first));
        assertEquals(digest, command(finding("coverage:0", context, "count_validation", "count_missing")).getString("commandDigest"));
        assertEquals(Lists.newArrayList("浙江", "江苏"), first.getValues());
        assertEquals(1, first.getMinCount());
    }

    @Test
    void digestChangesWhenAbsoluteGoalChangesAndIsStableForIdenticalInputs() {
        EvaluationContextDTO context = context(2);
        context.setSelectionTargetCount(4);
        String first = command(finding("count_target", context, "count_validation", "count_below_target")).getString("commandDigest");
        assertEquals(first, command(finding("count_target", context, "count_validation", "count_below_target")).getString("commandDigest"));
        context.setSelectionTargetCount(5);
        assertNotEquals(first, command(finding("count_target", context, "count_validation", "count_below_target")).getString("commandDigest"));
    }

    @Test
    void unsupportedGroupRepairAndPolicyNeverInventUnitReplacementCommands() {
        EvaluationContextDTO context = context(3);
        context.setAdmissionMode("major_group");
        assertNull(finding("group_inner_safety_guard", context, "group_inner_safety_guard", "group_inner_safety_missing").getSuggestedCommand());
        assertNull(finding("adjustment_notice", context, "adjustment_notice", "adjustment_notice").getSuggestedCommand());
    }

    @Test
    void unsupportedGapAndUnconfirmedRatioKeepFindingsWithoutCommands() {
        EvaluationContextDTO context = context(3);
        EvaluationFindingDTO gap = finding("probability_gap", context, "probability_gap", "probability_gap");
        EvaluationFindingDTO ratio = finding("ratio_distribution", context, "ratio_distribution", "protect_tier_missing");
        assertEquals("fail", gap.getResultStatus());
        assertEquals("fail", ratio.getResultStatus());
        assertNull(gap.getSuggestedCommand());
        assertNull(ratio.getSuggestedCommand());
    }

    @Test
    void knownCountFailureWithoutAbsoluteCountDoesNotInventAnIncompleteCommand() {
        EvaluationContextDTO context = context(3);
        assertNull(finding("count_validation_hard", context, "count_validation", "count_missing").getSuggestedCommand());
        assertNull(finding("count_validation_hard", context, "count_validation", "count_over_limit").getSuggestedCommand());
    }

    @Test
    void ratioRepairUsesAuthoritativeTargetWhenCurrentPlanExceedsIt() {
        EvaluationContextDTO context = context(12);
        context.setRequiredCount(10);
        TierAllocationConstraintDTO constraint = new TierAllocationConstraintDTO();
        constraint.setType("exact_counts");
        constraint.setSprint(range(5, 5));
        constraint.setStable(range(3, 3));
        constraint.setProtect(range(2, 2));
        context.setTierConstraint(constraint);

        JSONObject command = command(finding("ratio_distribution", context, "count_validation", "count_over_limit"));
        assertEquals(10, command.getInteger("targetCount"));
        assertEquals(5, command.getJSONObject("tierConstraint").getJSONObject("sprint").getInteger("minCount"));
    }

    private JSONObject command(EvaluationFindingDTO finding) {
        assertNotNull(finding.getSuggestedCommand(), finding.getCode());
        return (JSONObject) JSON.toJSON(finding.getSuggestedCommand());
    }

    private EvaluationFindingDTO finding(String code, EvaluationContextDTO context, String checkCode, String reason) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode(checkCode);
        check.setPassed(reason == null);
        check.setLevel("warn");
        check.setSeverity("action");
        check.setReasonCode(reason);
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(Lists.newArrayList(check));
        return mapper.map(review, context).getFindings().stream()
                .filter(item -> code.equals(item.getCode())).findFirst().get();
    }

    private EvaluationContextDTO context(int count) {
        EvaluationContextDTO context = new EvaluationContextDTO();
        context.setEvaluatedStateVersion(7);
        context.setPlanContentDigest("plan-content");
        context.setSafetyFloorMode("not_applicable");
        for (int index = 0; index < count; index++) {
            EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
            entry.setLevel("unit");
            entry.setId("unit-" + index);
            entry.setPathTier("sprint");
            context.getEntries().add(entry);
        }
        return context;
    }

    private CoverageRequirementDTO coverage(int minimum, String... values) {
        CoverageRequirementDTO requirement = new CoverageRequirementDTO();
        requirement.setDomain("region");
        requirement.setKey("province");
        requirement.setValues(Lists.newArrayList(values));
        requirement.setMinCount(minimum);
        return requirement;
    }

    private TierCountRangeDTO range(int minimum, int maximum) {
        TierCountRangeDTO range = new TierCountRangeDTO();
        range.setMinCount(minimum);
        range.setMaxCount(maximum);
        return range;
    }
}
