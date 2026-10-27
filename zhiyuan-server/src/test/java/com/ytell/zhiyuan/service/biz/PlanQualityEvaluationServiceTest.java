package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PlanQualityEvaluationServiceTest {

    private final PlanQualityEvaluationService service = new PlanQualityEvaluationService();

    @Test
    void emptyPlanIsUnknownNotPass() {
        PlanEvaluationDTO evaluation = service.evaluate(new PlanningStateDTO(), Lists.newArrayList());

        assertEquals("no_plan", evaluation.getStatus());
        assertNull(evaluation.getHardFeasible());
        assertTrue(evaluation.getFindings().stream()
                .anyMatch(f -> "plan_empty".equals(f.getCode())));
        assertEquals(PlanQualityEvaluationService.QUALITY_POLICY_VERSION,
                evaluation.getQualityPolicyVersion());
    }

    @Test
    void noConfirmedPreferenceIsNotReportedAsNonIntent() {
        PlanningStateDTO state = planState(false, "计算机");
        PlanEvaluationDTO evaluation = service.evaluate(state, Lists.newArrayList(
                state.getCandidatePoolState().getItems().get(0)));

        EvaluationFindingDTO preference = finding(evaluation, "preference_no_confirmed_source");
        assertEquals("unknown", preference.getResultStatus());
        assertTrue(preference.getSummary().contains("未确认"));
        assertFalse(evaluation.getFindings().stream()
                .anyMatch(f -> "preference_not_matched".equals(f.getCode())));
    }

    @Test
    void specialPlanConflictIsEligibilityFailureAndUnknownIsNotPass() {
        PlanningStateDTO state = planState(true, "计算机（国家专项）");
        PlanEvaluationDTO evaluation = service.evaluate(state, state.getCandidatePoolState().getItems());
        EvaluationFindingDTO conflict = finding(evaluation, "special_plan_conflict");
        assertEquals("fail", conflict.getResultStatus());
        assertEquals(Boolean.FALSE, evaluation.getHardFeasible());

        PlanningStateDTO unknown = planState(false, "计算机（国家专项）");
        unknown.getCandidatePoolState().setSpecialPlan(null);
        PlanEvaluationDTO unknownEvaluation = service.evaluate(
                unknown, unknown.getCandidatePoolState().getItems());
        EvaluationFindingDTO finding = finding(unknownEvaluation, "special_plan_unknown");
        assertEquals("unknown", finding.getResultStatus());
        assertNull(unknownEvaluation.getHardFeasible());
    }

    @Test
    void ambiguousSpecialPlanIsUnknownEvenWhenUserHasNoQualification() {
        PlanningStateDTO state = planState(true, "计算机（定向培养专项）");

        PlanEvaluationDTO evaluation = service.evaluate(state, state.getCandidatePoolState().getItems());

        assertEquals("unknown", finding(evaluation, "special_plan_unknown").getResultStatus());
        assertNull(evaluation.getHardFeasible());
    }

    @Test
    void genericQualificationDoesNotVerifySpecificSpecialPlanType() {
        PlanningStateDTO state = planState(false, "计算机（国家专项）");
        state.getCandidatePoolState().setSpecialPlan(true);

        PlanEvaluationDTO evaluation = service.evaluate(state, state.getCandidatePoolState().getItems());

        assertEquals("unknown", finding(evaluation, "special_plan_unknown").getResultStatus());
        assertNull(evaluation.getHardFeasible());
    }

    @Test
    void formalSpecialPlanTagsAreNotLostFromEvaluation() {
        PlanningStateDTO state = planState(false, "计算机");
        state.getCandidatePoolState().getItems().get(0).getMajorPlanTags().add("地方专项");

        PlanEvaluationDTO evaluation = service.evaluate(state, state.getCandidatePoolState().getItems());

        assertEquals("unknown", finding(evaluation, "special_plan_unknown").getResultStatus());
        assertNull(evaluation.getHardFeasible());
    }

    @Test
    void selectedGroupMajorMatchesConfirmedPreferenceWithoutCandidateLookup() {
        PlanningStateDTO state = groupPlan("电气工程及其自动化");
        state.getProfileState().getExplicitProfile().getPositiveMajors().add("电气工程及其自动化");
        state.getCandidatePoolState().getItems().clear();

        PlanEvaluationDTO evaluation = service.evaluate(state, Lists.newArrayList());

        assertEquals("pass", finding(evaluation, "preference_matched").getResultStatus());
        assertFalse(evaluation.getFindings().stream()
                .anyMatch(result -> "preference_not_matched".equals(result.getCode())));
    }

    @Test
    void selectedGroupMajorSpecialPlanTagsAreCheckedWithoutCandidateLookup() {
        PlanningStateDTO state = groupPlan("计算机");
        state.getOrderedPlanState().getUnits().get(0).getMajorItems().get(0)
                .getMajorPlanTags().add("地方专项");
        state.getCandidatePoolState().getItems().clear();

        PlanEvaluationDTO evaluation = service.evaluate(state, Lists.newArrayList());

        assertEquals("unknown", finding(evaluation, "special_plan_unknown").getResultStatus());
        assertNull(evaluation.getHardFeasible());
        state.getCandidatePoolState().setSpecialPlan(false);
        assertEquals(Boolean.FALSE, service.evaluate(state, Lists.newArrayList()).getHardFeasible());
    }

    @Test
    void directedAndPublicFundingTagsDoNotImplyVerifiedEligibility() {
        for (String tag : Lists.newArrayList("公费定向", "定向培养", "公费师范生", "楚怡工匠")) {
            PlanningStateDTO state = planState(true, "计算机");
            state.getCandidatePoolState().getItems().get(0).getMajorPlanTags().add(tag);

            PlanEvaluationDTO evaluation = service.evaluate(state, state.getCandidatePoolState().getItems());

            assertEquals("unknown", finding(evaluation, "special_plan_unknown").getResultStatus(), tag);
            assertNull(evaluation.getHardFeasible(), tag);
        }
    }

    @Test
    void negatedSpecialAndDirectedTagsDoNotMisclassifyOrdinaryPlans() {
        for (String tag : Lists.newArrayList("非专项计划", "非专项", "非定向", "非公费")) {
            PlanningStateDTO state = planState(true, "计算机");
            state.getCandidatePoolState().getItems().get(0).getMajorPlanTags().add(tag);

            assertEquals(Boolean.TRUE,
                    service.evaluate(state, state.getCandidatePoolState().getItems()).getHardFeasible(), tag);
        }
    }

    @Test
    void ordinaryPlanWithoutSpecialEvidenceRemainsFeasible() {
        PlanningStateDTO state = planState(true, "计算机");

        assertEquals(Boolean.TRUE,
                service.evaluate(state, state.getCandidatePoolState().getItems()).getHardFeasible());
    }

    @Test
    void evaluationVersionIsNewAndHasNoCommandSuggestions() {
        PlanningStateDTO state = planState(false, "计算机");
        PlanEvaluationDTO evaluation = service.evaluate(state, state.getCandidatePoolState().getItems());

        assertNotNull(evaluation.getEvaluationVersion());
        assertEquals("quality-v2", evaluation.getObjectiveModelVersion());
        assertTrue(evaluation.getFindings().stream().allMatch(f -> "quality_v2".equals(f.getSource())));
        assertTrue(evaluation.getFindings().stream().noneMatch(f -> f.getSuggestedCommand() != null));
        assertTrue(evaluation.getFindings().stream().noneMatch(f -> f.getObjectiveDelta() != null));
    }

    @Test
    void ratioConcentrationIsWarnAndNeverPresentedAsProbability() {
        PlanningStateDTO state = multiUnitPlan(
                new String[]{"u1", "u2", "u3", "u4", "u5"},
                new String[]{"冲", "冲", "冲", "冲", "冲"},
                new Double[]{1D, 1D, 1D, 8D, 14D});

        PlanEvaluationDTO evaluation = service.evaluate(state, Lists.newArrayList());

        EvaluationFindingDTO finding = finding(evaluation, "ratio_bucket_concentration");
        assertEquals("warn", finding.getResultStatus());
        assertTrue(finding.getSummary().contains("≤1%"));
        assertTrue(finding.getSummary().contains("不是精确概率"));
    }

    @Test
    void provinceAndNatureConcentrationAreWarned() {
        PlanningStateDTO state = multiUnitPlan(
                new String[]{"u1", "u2", "u3", "u4", "u5"},
                new String[]{"冲", "稳", "稳", "保", "保"},
                new Double[]{8D, 55D, 60D, 75D, 90D});
        for (OrderedUnitDTO unit : state.getOrderedPlanState().getUnits()) {
            unit.setProvinceName("广东");
            unit.setSchoolNature("民办");
        }

        PlanEvaluationDTO evaluation = service.evaluate(state, Lists.newArrayList());

        EvaluationFindingDTO finding = finding(evaluation, "diversity_concentration");
        assertEquals("warn", finding.getResultStatus());
        assertTrue(finding.getSummary().contains("广东"));
    }

    private PlanningStateDTO multiUnitPlan(String[] ids, String[] tiers, Double[] ratios) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(12);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(ids.length);
        state.getDataFreshnessState().setDataVersion("data-v1");
        for (int index = 0; index < ids.length; index++) {
            OrderedUnitDTO unit = new OrderedUnitDTO();
            unit.setUnitId(ids[index]);
            unit.setSchoolName("学校" + index);
            unit.setPosition(index + 1);
            unit.setTier(tiers[index]);
            unit.setSchoolEnrollRatio(ratios[index]);
            unit.setAdmissionRatio(ratios[index]);
            unit.setProvinceName("广东");
            unit.setSchoolNature("民办");
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(ids[index] + "_m");
            major.setMajorName("计算机");
            unit.getMajorItems().add(major);
            state.getOrderedPlanState().getUnits().add(unit);
        }
        return state;
    }

    private EvaluationFindingDTO finding(PlanEvaluationDTO evaluation, String code) {
        List<EvaluationFindingDTO> findings = evaluation.getFindings();
        return findings.stream().filter(f -> code.equals(f.getCode())).findFirst()
                .orElseThrow(() -> new AssertionError("missing finding " + code + " in " + findings));
    }

    private PlanningStateDTO groupPlan(String majorName) {
        PlanningStateDTO state = planState(false, majorName);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getOrderedPlanState().getItems().clear();
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setSchoolName("学校A");
        unit.setPosition(1);
        unit.setTier("稳");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId("v1");
        major.setMajorName(majorName);
        unit.getMajorItems().add(major);
        state.getOrderedPlanState().getUnits().add(unit);
        return state;
    }

    private PlanningStateDTO planState(boolean noSpecialPlan, String majorName) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getCandidatePoolState().setSpecialPlan(noSpecialPlan ? Boolean.FALSE : null);
        state.getDataFreshnessState().setDataVersion("data-v1");
        state.getDataFreshnessState().setExamYear("2026");
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId("v1");
        candidate.setSchoolName("学校A");
        candidate.setMajorName(majorName);
        candidate.setTier("稳");
        candidate.setAdmissionRatio(0.6D);
        state.getCandidatePoolState().getItems().add(candidate);
        OrderedItemDTO ordered = new OrderedItemDTO();
        ordered.setPosition(1);
        ordered.setVolunteerId("v1");
        ordered.setSchoolName("学校A");
        ordered.setMajorName(majorName);
        ordered.setTier("稳");
        state.getOrderedPlanState().getItems().add(ordered);
        return state;
    }
}
