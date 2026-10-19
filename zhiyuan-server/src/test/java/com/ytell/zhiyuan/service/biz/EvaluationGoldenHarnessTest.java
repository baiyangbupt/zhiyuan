package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.*;

class EvaluationGoldenHarnessTest {

    private final EvaluationGoldenShadowTest harness = new EvaluationGoldenShadowTest();

    @Test
    void usesProductionSafetyAndCandidateTierFallback() {
        PlanningStateDTO state = state();
        EvaluationContextDTO context = harness.buildContext(state);

        assertEquals("applicable", context.getSafetyFloorMode());
        assertEquals(Integer.valueOf(2), context.getSafetyMinLocalProtect());
        assertEquals("protect", context.getEntries().get(0).getPathTier());
        assertTrue(context.getEntries().get(0).getRiskTags().contains("色弱限报"));
        assertEquals(Integer.valueOf(450), context.getBatchScore());
        assertEquals(JSON.toJSONString(new EvaluationContextBuilder().build(state,
                state.getCandidatePoolState().getItems(), state.getReviewState())),
                JSON.toJSONString(context));
    }

    @Test
    void verifiesDerivedSafetyFailureWithoutWeakeningItToPass() {
        PlanningStateDTO state = state();
        StringBuilder report = new StringBuilder();

        assertDoesNotThrow(() -> harness.assertGolden(state, "safety-shortfall", report));
        assertTrue(report.toString().contains("safety_guard"));
        assertTrue(report.toString().contains("fail/block"));
        assertTrue(report.toString().contains("actual=1"));
        assertTrue(report.toString().contains("required=2"));
    }

    @Test
    void explainsHistoricalDerivedDifferenceAndPreservesInputs() {
        PlanningStateDTO state = state();
        state.getCandidatePoolState().setUserScore(600);
        String before = JSON.toJSONString(state);
        StringBuilder report = new StringBuilder();

        assertDoesNotThrow(() -> harness.assertGolden(state, "historical-safety", report));
        assertTrue(report.toString().contains("MIGRATION safety_guard"));
        assertTrue(report.toString().contains("legacy=fail"));
        assertTrue(report.toString().contains("derived=pass/info"));
        assertTrue(report.toString().contains("score_ge_580"));
        assertEquals(before, JSON.toJSONString(state));
    }

    @Test
    void reportsMissingReviewAsSkipRatherThanSuccessfulComparison() {
        PlanningStateDTO state = state();
        state.setReviewState(null);
        StringBuilder report = new StringBuilder();

        harness.assertGolden(state, "no-review", report);

        assertTrue(report.toString().contains("SKIP: no review checks"));
        assertFalse(report.toString().contains("PASS:"));
    }

    @Test
    void rejectsStatusDriftForUnchangedLegacyTranslation() {
        rejectsMutation(state(), "probability_gap", finding -> finding.setResultStatus("pass"));
    }

    @Test
    void preservesUnknownRatherThanTurningMissingLegacyInputGreen() {
        PlanningStateDTO state = state();
        ReviewCheckDTO check = state.getReviewState().getChecks().get(1);
        check.setPassed(true);
        check.setLevel("warn");
        check.setSeverity("action");

        assertEquals("unknown", evaluate(state, "probability_gap").getResultStatus());
        rejectsMutation(state, "probability_gap", finding -> finding.setResultStatus("pass"));
    }

    @Test
    void rejectsAlteredLegacyCountSplit() {
        rejectsMutation(state(), "count_validation_hard", finding -> finding.setResultStatus("pass"));
        rejectsMutation(state(), "count_target", finding -> finding.setResultStatus("pass"));
    }

    @Test
    void independentlyChecksBothLegacyCountContracts() {
        PlanningStateDTO state = state();
        ReviewCheckDTO check = state.getReviewState().getChecks().get(2);
        state.setConstraintState(JSON.parseObject("{\"hardPlanningObjectives\":{\"selectionTargetCount\":2}}",
                ConstraintStateDTO.class));
        check.setReasonCode("count_below_target");
        assertEquals("pass", evaluate(state, "count_validation_hard").getResultStatus());
        assertEquals("fail", evaluate(state, "count_target").getResultStatus());

        check.setReasonCode("count_over_limit");
        assertEquals("fail", evaluate(state, "count_validation_hard").getResultStatus());
        assertEquals("pass", evaluate(state, "count_target").getResultStatus());

        check.setPassed(true);
        check.setLevel("warn");
        check.setReasonCode(null);
        assertEquals("unknown", evaluate(state, "count_validation_hard").getResultStatus());
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(null);
        assertEquals("not_applicable", evaluate(state, "count_target").getResultStatus());
    }

    @Test
    void rejectsFalseGreenSafetyAndFabricatedSafetyEvidence() {
        rejectsMutation(state(), "safety_guard", finding -> finding.setResultStatus("pass"));
        rejectsMutation(state(), "safety_guard", finding -> finding.setDisplaySeverity("info"));
        rejectsMutation(state(), "safety_guard", finding -> finding.setReasonCode(null));
        rejectsMutation(state(), "safety_guard", finding -> finding.getThreshold().put("actual", 2));
        rejectsMutation(state(), "safety_guard", finding -> finding.setAffectedEntryRefs(Collections.emptyList()));
    }

    @Test
    void rejectsWrongDerivedResultsEvenWhenHistoricalChecksAreAbsent() {
        for (String code : Arrays.asList("probability_inversion", "high_tuition", "admission_limit",
                "special_enrollment", "cooperative_program", "edge_score")) {
            rejectsMutation(state(), code, finding -> finding.setResultStatus(
                    "pass".equals(finding.getResultStatus()) ? "fail" : "pass"));
        }
    }

    @Test
    void rejectsInventedDerivedCountsRatherThanOnlyCheckingStatus() {
        rejectsMutation(state(), "probability_inversion", finding -> finding.getThreshold().put("inversionCount", 3));
        rejectsMutation(state(), "high_tuition", finding -> finding.getThreshold().put("matchedCount", 0));
        rejectsMutation(state(), "admission_limit", finding -> finding.getThreshold().put("matchedCount", 0));
        rejectsMutation(state(), "edge_score", finding -> finding.getThreshold().put("delta", 30));
    }

    @Test
    void rejectsMissingDuplicateAndUnexpectedFindings() {
        PlanningStateDTO state = state();
        EvaluationContextDTO context = harness.buildContext(state);
        PlanEvaluationDTO evaluation = new ReviewEvaluationMapper().map(state.getReviewState(), context);
        EvaluationFindingDTO removed = EvaluationGoldenOracle.finding(evaluation, "high_tuition");
        evaluation.getFindings().remove(removed);
        assertThrows(AssertionError.class, () -> verify(state, context, evaluation));
        evaluation.getFindings().add(removed);
        evaluation.getFindings().add(removed);
        assertThrows(AssertionError.class, () -> verify(state, context, evaluation));
        evaluation.getFindings().remove(evaluation.getFindings().size() - 1);
        EvaluationFindingDTO unexpected = JSON.parseObject(JSON.toJSONString(removed), EvaluationFindingDTO.class);
        unexpected.setCode("adjustment_notice");
        unexpected.setLayer("soft");
        unexpected.setRuleStrength("policy");
        evaluation.getFindings().add(unexpected);
        assertThrows(AssertionError.class, () -> verify(state, context, evaluation));
    }

    @Test
    void keepsUnavailableDerivedInputsOnStrictLegacyComparison() {
        PlanningStateDTO state = state();
        CandidateItemDTO candidate = state.getCandidatePoolState().getItems().get(0);
        candidate.setTuitionPerYear(null);
        candidate.setAdmissionRatio(null);
        candidate.setSchoolEnrollRatio(null);
        state.getCandidatePoolState().setBatchScore(null);
        for (String code : Arrays.asList("high_tuition", "probability_inversion", "edge_score")) {
            ReviewCheckDTO check = new ReviewCheckDTO();
            check.setCode(code);
            check.setPassed(false);
            state.getReviewState().getChecks().add(check);
            assertEquals("fail", evaluate(state, code).getResultStatus());
            rejectsMutation(state, code, finding -> finding.setResultStatus("pass"));
        }
    }

    @Test
    void independentlyCountsPositionOrderedInversionsAndTuitionBoundary() {
        PlanningStateDTO state = state();
        state.getCandidatePoolState().getItems().get(0).setAdmissionRatio(0.7D);
        state.getOrderedPlanState().getItems().get(0).setPosition(3);
        addItem(state, "b", 1, null, 0.9D, 20000);
        addItem(state, "c", 2, 0.8D, null, 20001);

        EvaluationFindingDTO inversion = evaluate(state, "probability_inversion");
        assertEquals("fail", inversion.getResultStatus());
        assertEquals(2, inversion.getThreshold().get("inversionCount"));
        assertEquals(Arrays.asList("b", "c", "a"), Arrays.asList(
                inversion.getAffectedEntryRefs().get(0).getId(), inversion.getAffectedEntryRefs().get(1).getId(),
                inversion.getAffectedEntryRefs().get(2).getId()));
        assertEquals(2, evaluate(state, "high_tuition").getThreshold().get("matchedCount"));
    }

    @Test
    void respectsInversionEpsilonNullPositionsAndMissingAdjacentRatios() {
        PlanningStateDTO state = state();
        state.getCandidatePoolState().getItems().get(0).setAdmissionRatio(0.8000000005D);
        addItem(state, "b", 2, 0.8D, null, 20000);
        addItem(state, "c", null, 0.9D, null, 20000);
        assertEquals(0, evaluate(state, "probability_inversion").getThreshold().get("inversionCount"));

        state.getCandidatePoolState().getItems().get(1).setAdmissionRatio(null);
        state.getCandidatePoolState().getItems().get(2).setAdmissionRatio(0.7D);
        assertEquals(0, evaluate(state, "probability_inversion").getThreshold().get("inversionCount"));
    }

    @Test
    void checksUnknownExcludedAndHighScoreSafetyModesExplicitly() {
        PlanningStateDTO state = state();
        state.getCandidatePoolState().setSourceProvinceName(null);
        EvaluationFindingDTO unknown = evaluate(state, "safety_guard");
        assertEquals("unknown", unknown.getResultStatus());
        assertEquals("block", unknown.getDisplaySeverity());
        assertEquals("province_missing", unknown.getThreshold().get("safetyReasonCode"));

        state.getCandidatePoolState().setSourceProvinceName("江西");
        state.setConstraintState(JSON.parseObject("{\"hardConstraints\":{\"mustExcludeRegions\":[\"江西省\"]}}",
                ConstraintStateDTO.class));
        EvaluationFindingDTO excluded = evaluate(state, "safety_guard");
        assertEquals("pass", excluded.getResultStatus());
        assertEquals("not_applicable", excluded.getThreshold().get("mode"));
        assertEquals("province_excluded", excluded.getThreshold().get("safetyReasonCode"));

        state.setConstraintState(null);
        state.getCandidatePoolState().setUserScore(580);
        assertEquals(0, evaluate(state, "safety_guard").getThreshold().get("required"));
        assertEquals("pass", evaluate(state, "safety_guard").getResultStatus());
    }

    @Test
    void countsGroupFactsOnceAndEnrichesRiskTagsFromAllMemberCandidates() {
        PlanningStateDTO state = groupState();
        EvaluationFindingDTO safety = evaluate(state, "safety_guard");
        assertEquals(1, safety.getThreshold().get("actual"));
        assertEquals("fail", safety.getResultStatus());
        assertEquals("unit", safety.getAffectedEntryRefs().get(0).getLevel());
        assertEquals(40000, evaluate(state, "high_tuition").getThreshold().get("maxTuitionPerYear"));
        assertEquals(1, evaluate(state, "high_tuition").getThreshold().get("matchedCount"));
        assertEquals("fail", evaluate(state, "admission_limit").getResultStatus());
        assertEquals("fail", evaluate(state, "special_enrollment").getResultStatus());
        assertEquals("fail", evaluate(state, "cooperative_program").getResultStatus());
        assertEquals(1, evaluate(state, "coverage:0").getThreshold().get("matchedCount"));
        assertEquals("fail", evaluate(state, "coverage:0").getResultStatus());
        assertEquals("pass", evaluate(state, "ratio_distribution").getResultStatus());
    }

    @Test
    void checksCoverageAndQuotaMigrationFactsAndRejectsFabrication() {
        PlanningStateDTO state = groupState();
        rejectsMutation(state, "coverage:0", finding -> finding.setResultStatus("pass"));
        rejectsMutation(state, "coverage:0", finding -> finding.getThreshold().put("matchedCount", 2));
        rejectsMutation(state, "ratio_distribution", finding -> finding.getThreshold().put("protectActual", 2));

        state.getOrderedPlanState().getUnits().get(0).setTier("sprint");
        EvaluationFindingDTO ratio = evaluate(state, "ratio_distribution");
        assertEquals("fail", ratio.getResultStatus());
        assertEquals("protect_tier_missing", ratio.getReasonCode());
        assertEquals(0, ratio.getThreshold().get("protectActual"));
        rejectsMutation(state, "ratio_distribution", finding -> finding.setResultStatus("pass"));
    }

    @Test
    void rejectsDroppedRawRiskEvidenceEvenIfMapperAndContextAgreeOnGreen() {
        PlanningStateDTO state = state();
        EvaluationContextDTO context = harness.buildContext(state);
        context.getEntries().get(0).getRiskTags().clear();
        PlanEvaluationDTO evaluation = new ReviewEvaluationMapper().map(state.getReviewState(), context);

        assertEquals("pass", EvaluationGoldenOracle.finding(evaluation, "admission_limit").getResultStatus());
        assertThrows(AssertionError.class, () -> verify(state, context, evaluation));
    }

    @Test
    void detectsGroupMemberNameCooperationWithoutExplicitRiskFlag() {
        PlanningStateDTO state = groupState();
        CandidateItemDTO member = state.getCandidatePoolState().getItems().get(1);
        member.getRiskFlags().clear();
        member.setMajorName("工程管理(中外合作办学)");
        OrderedItemDTO ordered = new OrderedItemDTO();
        ordered.setVolunteerId("b");
        state.getOrderedPlanState().getItems().add(ordered);
        ReviewCheckDTO historical = new ReviewCheckDTO();
        historical.setCode("cooperative_program");
        historical.setPassed(false);
        historical.getAffectedVolunteerIds().add("b");
        state.getReviewState().getChecks().add(historical);
        StringBuilder report = new StringBuilder();

        harness.assertGolden(state, "group-name-projection", report);

        assertTrue(report.toString().contains("historicalCandidateMatches=1"));
        assertTrue(report.toString().contains("工程管理(中外合作办学)"));
        assertTrue(report.toString().contains("selectedHistoricalAffected=[b]"));
        assertTrue(harness.buildContext(state).getEntries().get(0).getRiskTags().contains("cooperative_program"));
        assertEquals("fail", evaluate(state, "cooperative_program").getResultStatus());
        assertEquals(1, evaluate(state, "cooperative_program").getThreshold().get("matchedCount"));
        assertTrue(report.toString().contains("derived=fail/action historicalDifference=false"));
    }

    @Test
    void rejectsDroppedConfirmedCoverageFromContext() {
        PlanningStateDTO state = groupState();
        EvaluationContextDTO context = harness.buildContext(state);
        context.getCoverageRequirements().clear();
        PlanEvaluationDTO evaluation = new ReviewEvaluationMapper().map(state.getReviewState(), context);

        assertFalse(evaluation.getFindings().stream().anyMatch(finding -> "coverage:0".equals(finding.getCode())));
        assertThrows(AssertionError.class, () -> verify(state, context, evaluation));
    }

    @Test
    void rejectsLoweredSafetyFloorFromContext() {
        PlanningStateDTO state = state();
        EvaluationContextDTO context = harness.buildContext(state);
        context.setSafetyMinLocalProtect(0);
        PlanEvaluationDTO evaluation = new ReviewEvaluationMapper().map(state.getReviewState(), context);

        assertEquals("pass", EvaluationGoldenOracle.finding(evaluation, "safety_guard").getResultStatus());
        assertThrows(AssertionError.class, () -> verify(state, context, evaluation));
    }

    private EvaluationFindingDTO evaluate(PlanningStateDTO state, String code) {
        EvaluationContextDTO context = harness.buildContext(state);
        PlanEvaluationDTO evaluation = new ReviewEvaluationMapper().map(state.getReviewState(), context);
        verify(state, context, evaluation);
        return EvaluationGoldenOracle.finding(evaluation, code);
    }

    private void rejectsMutation(PlanningStateDTO state, String code, Consumer<EvaluationFindingDTO> mutation) {
        EvaluationContextDTO context = harness.buildContext(state);
        PlanEvaluationDTO evaluation = new ReviewEvaluationMapper().map(state.getReviewState(), context);
        verify(state, context, evaluation);
        mutation.accept(EvaluationGoldenOracle.finding(evaluation, code));
        AssertionError failure = assertThrows(AssertionError.class, () -> verify(state, context, evaluation));
        assertTrue(failure.getMessage().contains(code), failure.getMessage());
    }

    private void verify(PlanningStateDTO state, EvaluationContextDTO context, PlanEvaluationDTO evaluation) {
        EvaluationGoldenOracle.verify(state, context, evaluation, "focused", new StringBuilder());
    }

    private void addItem(PlanningStateDTO state, String id, Integer position, Double majorRatio,
                         Double schoolRatio, Integer tuition) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setAdmissionRatio(majorRatio);
        candidate.setSchoolEnrollRatio(schoolRatio);
        candidate.setTuitionPerYear(tuition);
        state.getCandidatePoolState().getItems().add(candidate);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(id);
        item.setPosition(position);
        state.getOrderedPlanState().getItems().add(item);
    }

    private PlanningStateDTO groupState() {
        PlanningStateDTO state = state();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().getItems().add(JSON.parseObject("{\"volunteerId\":\"b\","
                + "\"tuitionPerYear\":40000,\"tier\":\"protect\",\"riskFlags\":[\"cooperative_program\"],"
                + "\"reasonCodes\":[\"公费定向\"]}", CandidateItemDTO.class));
        state.getOrderedPlanState().getItems().clear();
        state.getOrderedPlanState().getUnits().add(JSON.parseObject("{\"unitId\":\"group-a\",\"position\":1,"
                + "\"tier\":\"protect\",\"provinceName\":\"江西省\",\"admissionRatio\":0.8,"
                + "\"majorItems\":[{\"volunteerId\":\"a\"},{\"volunteerId\":\"b\"}]}", OrderedUnitDTO.class));
        state.setConstraintState(JSON.parseObject("{\"hardPlanningObjectives\":{\"selectionTargetCount\":1,"
                + "\"tierQuotaGoal\":{\"type\":\"exact_counts\",\"sprintCount\":0,\"stableCount\":0,\"protectCount\":1},"
                + "\"coverageRequirements\":[{\"domain\":\"admission\",\"key\":\"tier\",\"values\":[\"protect\"],\"minCount\":2}]}}",
                ConstraintStateDTO.class));
        ReviewCheckDTO ratio = new ReviewCheckDTO();
        ratio.setCode("ratio_distribution");
        ratio.setPassed(false);
        ratio.setSeverity("action");
        state.getReviewState().getChecks().add(ratio);
        return state;
    }

    static PlanningStateDTO state() {
        return JSON.parseObject("{\"version\":7,\"candidatePoolState\":{"
                + "\"volunteerModel\":\"major\",\"sourceProvinceName\":\"江西省\","
                + "\"userScore\":500,\"batchScore\":450,\"requiredCount\":2,\"sourceVersion\":3,"
                + "\"items\":[{\"volunteerId\":\"a\",\"tier\":\"protect\","
                + "\"provinceName\":\"江西\",\"admissionRatio\":0.8,\"tuitionPerYear\":20001,"
                + "\"mustSubjects\":[\"色弱限报\"]}]},"
                + "\"orderedPlanState\":{\"items\":[{\"volunteerId\":\"a\",\"position\":1}]},"
                + "\"reviewState\":{\"sourceVersion\":7,\"checks\":["
                + "{\"code\":\"safety_guard\",\"passed\":false,\"severity\":\"block\"},"
                + "{\"code\":\"probability_gap\",\"passed\":false,\"severity\":\"action\"},"
                + "{\"code\":\"count_validation\",\"passed\":false,\"severity\":\"block\","
                + "\"reasonCode\":\"count_missing\"}]}}", PlanningStateDTO.class);
    }
}
