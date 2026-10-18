package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
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
    void missingProvinceIsUnknownNotPass() {
        ReviewStateDTO review = new ReviewStateDTO();
        List<ReviewCheckDTO> checks = defaultChecks();
        replace(checks, check("safety_guard", true, "warn", "block", null,
                "缺少生源省份信息，无法完成本省保底校验"));
        review.setChecks(checks);

        PlanEvaluationDTO evaluation = mapper.map(review, context(45));

        EvaluationFindingDTO safety = find(evaluation, "safety_guard");
        assertEquals("unknown", safety.getResultStatus());
        assertEquals("block", safety.getDisplaySeverity());
        assertFalse(evaluation.getHardFeasible());
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
