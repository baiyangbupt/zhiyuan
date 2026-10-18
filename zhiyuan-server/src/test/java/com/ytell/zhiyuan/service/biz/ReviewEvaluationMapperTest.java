package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReviewEvaluationMapperTest {

    private final ReviewEvaluationMapper mapper = new ReviewEvaluationMapper();

    @Test
    void mapsAllChecksIntoFifteenFindingsAndDerivesHardFeasibility() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());

        PlanEvaluationDTO evaluation = mapper.map(review, context(45));

        assertEquals("completed", evaluation.getStatus());
        assertEquals(15, evaluation.getProbesRun());
        assertEquals(15, evaluation.getFindings().size());
        assertTrue(evaluation.getHardFeasible());
        assertNotNull(evaluation.getEvaluationVersion());
        assertNotNull(evaluation.getObjectiveModelVersion());
        assertNotNull(evaluation.getObjectiveDigest());
        for (EvaluationFindingDTO finding : evaluation.getFindings()) {
            if ("pass".equals(finding.getResultStatus())) {
                assertEquals("info", finding.getDisplaySeverity(), finding.getCode());
                assertNull(finding.getObjectiveDelta(), finding.getCode());
                assertNull(finding.getSuggestedCommand(), finding.getCode());
            }
        }
    }

    @Test
    void mapsCoverageRequirementsIntoSeparateFindings() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());
        EvaluationContextDTO context = context(45);
        com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO region =
                new com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO();
        region.setDomain("region");
        region.setKey("province");
        region.setValues(Lists.newArrayList("广东"));
        region.setMinCount(1);
        com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO major =
                new com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO();
        major.setDomain("major");
        major.setKey("major");
        major.setValues(Lists.newArrayList("计算机"));
        major.setMinCount(2);
        context.getCoverageRequirements().add(region);
        context.getCoverageRequirements().add(major);
        context.getEntries().get(0).setMatchedCoverageIds(
                Lists.newArrayList("coverage:0", "coverage:1"));
        context.getEntries().get(1).setMatchedCoverageIds(Lists.newArrayList("coverage:0"));

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        assertEquals(17, evaluation.getProbesRun());
        EvaluationFindingDTO regionFinding = evaluation.getFindings().stream()
                .filter(item -> "coverage:0".equals(item.getCode())).findFirst().orElse(null);
        EvaluationFindingDTO majorFinding = evaluation.getFindings().stream()
                .filter(item -> "coverage:1".equals(item.getCode())).findFirst().orElse(null);
        assertNotNull(regionFinding);
        assertEquals("pass", regionFinding.getResultStatus());
        assertEquals("info", regionFinding.getDisplaySeverity());
        assertNotNull(majorFinding);
        assertEquals("fail", majorFinding.getResultStatus());
        assertEquals("action", majorFinding.getDisplaySeverity());
        assertEquals("coverage_shortfall", majorFinding.getReasonCode());
    }

    @Test
    void hardFailuresMakeHardFeasibilityFalse() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("safety_guard", false, "risk", "block", null, "本省保底不足"));
        replace(checks, check("admission_limit", false, "risk", "block", null, "限报条件"));
        replace(checks, check("group_inner_safety_guard", false, "risk", "block", null, "组内安全垫不足"));
        replace(checks, check("count_validation", false, "risk", "block", "count_missing", "数量不足"));
        review.setChecks(checks);

        PlanEvaluationDTO evaluation = mapper.map(review, context(45));

        assertFalse(evaluation.getHardFeasible());
        assertTrue(evaluation.getFindings().stream()
                .filter(item -> "hard".equals(item.getRuleStrength()))
                .filter(item -> !"pass".equals(item.getResultStatus()))
                .allMatch(item -> "block".equals(item.getDisplaySeverity())));
        EvaluationFindingDTO hard = find(evaluation, "count_validation_hard");
        assertEquals("fail", hard.getResultStatus());
        assertEquals("block", hard.getDisplaySeverity());
    }

    @Test
    void missingProvinceIsExplicitUnknownAndBlocks() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("safety_guard", false, "risk", "block", null,
                "旧检查的本省保底失败"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);
        context.setSafetyFloorMode("unknown");
        context.setSafetyMinLocalProtect(0);
        context.setSafetyReasonCode("province_missing");
        context.setSourceProvince(null);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO safety = find(evaluation, "safety_guard");
        assertEquals("unknown", safety.getResultStatus());
        assertEquals("block", safety.getDisplaySeverity());
        assertEquals("safety_unknown", safety.getReasonCode());
        assertTrue(safety.getSummary().contains("无法完成本省保底校验"));
        assertFalse(evaluation.getHardFeasible());
    }

    @Test
    void derivedSafetyPassesWhenProvinceExcludedEvenWithZeroProtect() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("safety_guard", false, "risk", "block", null,
                "旧检查的本省保底失败"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);
        context.setSafetyFloorMode("not_applicable");
        context.setSafetyMinLocalProtect(0);
        context.setSafetyReasonCode("province_excluded");
        context.getEntries().clear();
        context.getEntries().add(entry("unit", "u1", 1, "冲", 45D, null));
        context.getEntries().add(entry("unit", "u2", 2, "稳", 65D, null));

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO safety = find(evaluation, "safety_guard");
        assertEquals("pass", safety.getResultStatus());
        assertEquals("info", safety.getDisplaySeverity());
        assertNull(safety.getReasonCode());
        assertTrue(safety.getSummary().contains("不适用"));
        assertTrue(evaluation.getHardFeasible());
    }

    @Test
    void derivedSafetyFailsHardWhenApplicableFloorNotMet() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);
        context.setSafetyFloorMode("applicable");
        context.setSafetyMinLocalProtect(2);
        context.setSafetyReasonCode("local_protect_floor");
        context.getEntries().clear();
        context.getEntries().add(entry("unit", "u1", 1, "冲", 45D, null));
        // 外省保底不计入本省保底。
        EvaluationEntryRefDTO otherProvince = entry("unit", "u2", 2, "保", 75D, null);
        otherProvince.setProvinceName("湖南");
        context.getEntries().add(otherProvince);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO safety = find(evaluation, "safety_guard");
        assertEquals("fail", safety.getResultStatus());
        assertEquals("block", safety.getDisplaySeverity());
        assertEquals("safety_shortfall", safety.getReasonCode());
        assertTrue(safety.getAffectedEntryRefs().isEmpty());
        assertEquals(0, safety.getThreshold().get("actual"));
        assertEquals(2, safety.getThreshold().get("required"));
        assertFalse(evaluation.getHardFeasible());
    }

    @Test
    void derivedRatioPassesExplicitTenSprintDespiteSoftBand() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("ratio_distribution", false, "risk", "action",
                "protect_tier_missing", "旧检查认为冲区占比过高且保区过低"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(10);
        context.setTierConstraint(tierConstraint(10, 0, 0));
        context.getEntries().clear();
        for (int index = 1; index <= 10; index++) {
            context.getEntries().add(entry("unit", "u" + index, index, "冲", 30D, null));
        }

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO ratio = find(evaluation, "ratio_distribution");
        assertEquals("pass", ratio.getResultStatus());
        assertEquals("info", ratio.getDisplaySeverity());
        assertNull(ratio.getReasonCode());
        assertEquals(10, ratio.getThreshold().get("sprintActual"));
        assertEquals(0, ratio.getThreshold().get("protectActual"));
        assertEquals(15, evaluation.getProbesRun());
        assertEquals(15, evaluation.getFindings().size());
        assertTrue(evaluation.getHardFeasible());
    }

    @Test
    void derivedRatioFailsWithDirectionalReasonCode() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());
        EvaluationContextDTO context = context(10);
        context.setTierConstraint(tierConstraint(5, 5, 0));
        context.getEntries().clear();
        for (int index = 1; index <= 10; index++) {
            context.getEntries().add(entry("unit", "u" + index, index, "冲", 30D, null));
        }

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO ratio = find(evaluation, "ratio_distribution");
        assertEquals("fail", ratio.getResultStatus());
        assertEquals("action", ratio.getDisplaySeverity());
        assertEquals("sprint_tier_over_limit", ratio.getReasonCode());
        assertEquals(10, ratio.getThreshold().get("sprintActual"));
        assertEquals(5, ratio.getThreshold().get("sprintMax"));
        assertEquals(10, ratio.getAffectedEntryRefs().size());
    }

    @Test
    void countBelowTargetFailsOnlyTargetProbe() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("count_validation", false, "warn", "action",
                "count_below_target", "当前志愿数量少于方案目标"));
        review.setChecks(checks);

        PlanEvaluationDTO evaluation = mapper.map(review, context(50));

        assertEquals("pass", find(evaluation, "count_validation_hard").getResultStatus());
        assertEquals("fail", find(evaluation, "count_target").getResultStatus());
        assertEquals("action", find(evaluation, "count_target").getDisplaySeverity());
        assertTrue(evaluation.getHardFeasible());
    }

    @Test
    void policyNoticesStayInfoAndNonFixable() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        review.setChecks(checks);

        PlanEvaluationDTO evaluation = mapper.map(review, context(45));

        EvaluationFindingDTO notice = find(evaluation, "adjustment_notice");
        assertEquals("pass", notice.getResultStatus());
        assertEquals("info", notice.getDisplaySeverity());
        assertEquals("policy", notice.getRuleStrength());
        assertEquals("none", notice.getFixability());
    }


    @Test
    void failingFindingsCarryObjectiveDeltaAndCompiledAction() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        ReviewCheckDTO highTuition = check("high_tuition", false, "warn", "action",
                null, "高收费");
        highTuition.getAffectedUnitIds().add("u1");
        replace(checks, highTuition);
        review.setChecks(checks);

        PlanEvaluationDTO evaluation = mapper.map(review, context(45));

        EvaluationFindingDTO finding = find(evaluation, "high_tuition");
        assertEquals("replace_risk_items", finding.getObjectiveDelta().getStrategy());
        assertEquals("u1", finding.getObjectiveDelta().getRemoveTargets().get(0).getId());
        com.ytell.zhiyuan.model.dto.planning.CompiledActionDTO compiled =
                (com.ytell.zhiyuan.model.dto.planning.CompiledActionDTO) finding.getSuggestedCommand();
        assertNotNull(compiled);
        assertEquals("replace_risk_items", compiled.getStrategy());
        assertFalse(compiled.getExecutable());
        EvaluationFindingDTO passed = find(evaluation, "ratio_distribution");
        assertNull(passed.getObjectiveDelta());
        assertNull(passed.getSuggestedCommand());
    }

    @Test
    void countOverLimitCompilesToTrimNotFill() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("count_validation", false, "warn", "action",
                "count_over_limit", "数量多于官方要求"));
        review.setChecks(checks);

        PlanEvaluationDTO evaluation = mapper.map(review, context(45));

        EvaluationFindingDTO hard = find(evaluation, "count_validation_hard");
        assertEquals("remove_risk_items", hard.getObjectiveDelta().getStrategy());
    }

    @Test
    void derivedHighTuitionFailsWhenEntryExceedsThreshold() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());
        EvaluationContextDTO context = context(45);
        context.getEntries().get(0)
                .setTuitionPerYear(TuitionThresholds.HIGH_TUITION_RISK_PER_YEAR + 1);
        // 恰好等于阈值不算高收费。
        context.getEntries().get(1)
                .setTuitionPerYear(TuitionThresholds.HIGH_TUITION_RISK_PER_YEAR);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "high_tuition");
        assertEquals("fail", finding.getResultStatus());
        assertEquals("action", finding.getDisplaySeverity());
        assertEquals("high_tuition", finding.getReasonCode());
        assertEquals(1, finding.getAffectedEntryRefs().size());
        assertEquals("u1", finding.getAffectedEntryRefs().get(0).getId());
        assertNull(finding.getObjectiveDelta());
        assertTrue(evaluation.getHardFeasible());
    }

    @Test
    void derivedHighTuitionPassesBelowThresholdEvenIfLegacyCheckFails() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("high_tuition", false, "warn", "action", null,
                "旧检查认为存在高收费"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);
        context.getEntries().get(0).setTuitionPerYear(12000);
        context.getEntries().get(1)
                .setTuitionPerYear(TuitionThresholds.HIGH_TUITION_RISK_PER_YEAR);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "high_tuition");
        assertEquals("pass", finding.getResultStatus());
        assertEquals("info", finding.getDisplaySeverity());
        assertNull(finding.getReasonCode());
        assertTrue(finding.getAffectedEntryRefs().isEmpty());
    }

    @Test
    void derivedCooperativeProgramFailsOnRiskFlag() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());
        EvaluationContextDTO context = context(45);
        context.getEntries().get(1).setRiskFlags(Lists.newArrayList("cooperative_program"));

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "cooperative_program");
        assertEquals("fail", finding.getResultStatus());
        assertEquals("action", finding.getDisplaySeverity());
        assertEquals("cooperative_program", finding.getReasonCode());
        assertEquals(1, finding.getAffectedEntryRefs().size());
        assertEquals("u2", finding.getAffectedEntryRefs().get(0).getId());
        assertTrue(evaluation.getHardFeasible());
    }

    @Test
    void derivedCooperativeProgramPassesWithoutFlagEvenIfLegacyCheckFails() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("cooperative_program", false, "warn", "action", null,
                "旧检查认为存在中外合作"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "cooperative_program");
        assertEquals("pass", finding.getResultStatus());
        assertEquals("info", finding.getDisplaySeverity());
        assertNull(finding.getReasonCode());
        assertTrue(finding.getAffectedEntryRefs().isEmpty());
    }

    @Test
    void derivedSpecialEnrollmentFailsOnRiskFlag() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());
        EvaluationContextDTO context = context(45);
        context.getEntries().get(0).setRiskFlags(Lists.newArrayList("special_enrollment"));

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "special_enrollment");
        assertEquals("fail", finding.getResultStatus());
        assertEquals("action", finding.getDisplaySeverity());
        assertEquals("special_enrollment", finding.getReasonCode());
        assertEquals(1, finding.getAffectedEntryRefs().size());
        assertEquals("u1", finding.getAffectedEntryRefs().get(0).getId());
    }

    @Test
    void derivedSpecialEnrollmentPassesWithoutFlagEvenIfLegacyCheckFails() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("special_enrollment", false, "warn", "action", null,
                "旧检查认为存在特殊类型"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "special_enrollment");
        assertEquals("pass", finding.getResultStatus());
        assertEquals("info", finding.getDisplaySeverity());
        assertNull(finding.getReasonCode());
        assertTrue(finding.getAffectedEntryRefs().isEmpty());
    }

    @Test
    void derivedAdmissionLimitFailsAsHardBlock() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());
        EvaluationContextDTO context = context(45);
        context.getEntries().get(1).setRiskFlags(Lists.newArrayList("admission_limit"));

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "admission_limit");
        assertEquals("fail", finding.getResultStatus());
        assertEquals("block", finding.getDisplaySeverity());
        assertEquals("hard", finding.getRuleStrength());
        assertEquals("admission_limit", finding.getReasonCode());
        assertEquals(1, finding.getAffectedEntryRefs().size());
        assertEquals("u2", finding.getAffectedEntryRefs().get(0).getId());
        assertFalse(evaluation.getHardFeasible());
    }

    @Test
    void derivedAdmissionLimitPassesWithoutFlagEvenIfLegacyCheckFails() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("admission_limit", false, "risk", "block", null,
                "旧检查认为存在限报"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "admission_limit");
        assertEquals("pass", finding.getResultStatus());
        assertEquals("info", finding.getDisplaySeverity());
        assertNull(finding.getReasonCode());
        assertTrue(finding.getAffectedEntryRefs().isEmpty());
        assertTrue(evaluation.getHardFeasible());
    }

    @Test
    void derivedProbabilityInversionPassesForIncreasingRatiosEvenIfLegacyCheckFails() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("probability_inversion", false, "warn", "notice", null,
                "旧检查认为存在倒挂"));
        review.setChecks(checks);
        EvaluationContextDTO context = context(45);
        // majorRatio 优先；schoolRatio 的反向值不参与判定。
        context.getEntries().get(0).setMajorRatio(45D);
        context.getEntries().get(0).setSchoolRatio(90D);
        context.getEntries().get(1).setMajorRatio(75D);
        context.getEntries().get(1).setSchoolRatio(10D);

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "probability_inversion");
        assertEquals("pass", finding.getResultStatus());
        assertEquals("info", finding.getDisplaySeverity());
        assertNull(finding.getReasonCode());
        assertTrue(finding.getAffectedEntryRefs().isEmpty());
        assertEquals(0, finding.getThreshold().get("inversionCount"));
    }

    @Test
    void derivedProbabilityInversionFailsForDecreasingRatiosByPosition() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setChecks(defaultChecks());
        EvaluationContextDTO context = context(45);
        context.getEntries().clear();
        // 列表顺序与 position 相反；无 majorRatio 时回退 schoolRatio。
        context.getEntries().add(entry("unit", "u2", 2, "保", 40D, null));
        context.getEntries().add(entry("unit", "u1", 1, "冲", 80D, null));

        PlanEvaluationDTO evaluation = mapper.map(review, context);

        EvaluationFindingDTO finding = find(evaluation, "probability_inversion");
        assertEquals("fail", finding.getResultStatus());
        assertEquals("notice", finding.getDisplaySeverity());
        assertEquals("probability_inversion", finding.getReasonCode());
        assertEquals(1, finding.getThreshold().get("inversionCount"));
        assertEquals(2, finding.getAffectedEntryRefs().size());
        assertEquals("u1", finding.getAffectedEntryRefs().get(0).getId());
        assertEquals("u2", finding.getAffectedEntryRefs().get(1).getId());
        assertTrue(evaluation.getHardFeasible());
    }

    private List<ReviewCheckDTO> defaultChecks() {
        return Lists.newArrayList(
                check("ratio_distribution", true, "info", "action", null, "配比正常"),
                check("safety_guard", true, "info", "block", null, "保底安全"),
                check("probability_inversion", true, "info", "notice", null, "未发现倒挂"),
                check("probability_gap", true, "info", "action", null, "梯度正常"),
                check("count_validation", true, "info", "info", null, "数量符合"),
                check("high_tuition", true, "info", "action", null, "未发现高收费"),
                check("admission_limit", true, "info", "block", null, "无限报"),
                check("special_enrollment", true, "info", "action", null, "无特殊类型"),
                check("edge_score", true, "info", "notice", null, "分数安全"),
                check("cooperative_program", true, "info", "action", null, "无中外合作"),
                check("group_inner_safety_guard", true, "info", "block", null, "组内安全"),
                check("major_group_safety_intent_alignment", true, "info", "action", null, "托底符合意向"),
                check("plan_update_notice", true, "info", "info", null, "招生计划可能更新"),
                check("adjustment_notice", true, "info", "info", null, "调剂风险提示"));
    }

    private TierAllocationConstraintDTO tierConstraint(int sprint, int stable, int protect) {
        TierAllocationConstraintDTO constraint = new TierAllocationConstraintDTO();
        constraint.setType("exact_counts");
        constraint.setSourceType("exact_counts");
        constraint.setSprintCount(sprint);
        constraint.setStableCount(stable);
        constraint.setProtectCount(protect);
        constraint.setSprint(range(sprint));
        constraint.setStable(range(stable));
        constraint.setProtect(range(protect));
        return constraint;
    }

    private TierCountRangeDTO range(int value) {
        TierCountRangeDTO range = new TierCountRangeDTO();
        range.setMinCount(value);
        range.setMaxCount(value);
        return range;
    }

    private EvaluationContextDTO context(int selectionTargetCount) {
        EvaluationEntryRefDTO first = entry("unit", "u1", 1, "冲", 45D, null);
        EvaluationEntryRefDTO second = entry("unit", "u2", 2, "保", 75D, null);
        EvaluationContextDTO context = new EvaluationContextDTO();
        context.setEntries(Lists.newArrayList(first, second));
        context.setSelectionTargetCount(selectionTargetCount);
        context.setRequiredCount(45);
        context.setAdmissionMode("major_group");
        context.setSourceProvince("广东");
        context.setUserScore(600);
        context.setCandidateSourceVersion(7);
        context.setEvaluatedStateVersion(11);
        context.setPlanContentDigest("digest-plan");
        context.setDataVersion("data-v1");
        context.getRequiredTierCounts().put("冲", 15);
        context.getRequiredTierCounts().put("稳", 15);
        context.getRequiredTierCounts().put("保", 15);
        return context;
    }

    private EvaluationEntryRefDTO entry(String level, String id, int position, String tier,
                                        Double schoolRatio, Double majorRatio) {
        EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
        entry.setLevel(level);
        entry.setId(id);
        entry.setPosition(position);
        entry.setPathTier(tier);
        entry.setSchoolRatio(schoolRatio);
        entry.setMajorRatio(majorRatio);
        entry.setProvinceName("广东");
        return entry;
    }

    private ReviewCheckDTO check(String code, boolean passed, String level, String severity,
                                 String reasonCode, String summary) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode(code);
        check.setPassed(passed);
        check.setLevel(level);
        check.setSeverity(severity);
        check.setReasonCode(reasonCode);
        check.setSummary(summary);
        return check;
    }

    private void replace(List<ReviewCheckDTO> checks, ReviewCheckDTO replacement) {
        for (int index = 0; index < checks.size(); index++) {
            if (checks.get(index).getCode().equals(replacement.getCode())) {
                checks.set(index, replacement);
                return;
            }
        }
        checks.add(replacement);
    }

    private EvaluationFindingDTO find(PlanEvaluationDTO evaluation, String code) {
        return evaluation.getFindings().stream()
                .filter(item -> code.equals(item.getCode()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("missing finding " + code));
    }
}
