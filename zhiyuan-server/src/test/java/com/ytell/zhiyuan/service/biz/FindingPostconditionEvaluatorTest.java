package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FindingPostconditionDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class FindingPostconditionEvaluatorTest {
    private final FindingPostconditionEvaluator evaluator = new FindingPostconditionEvaluator();

    @Test
    void acceptsFreshOriginalProbePassWithHardConstraintsSatisfied() {
        FindingPostconditionDTO result = evaluator.evaluate("safety_guard", review("pass", "pass"));
        assertTrue(result.getSatisfied());
        assertTrue(result.getProbeSatisfied());
        assertTrue(result.getHardFeasible());
        assertEquals("after-evaluation", result.getEvaluationVersion());
    }

    @Test
    void solverReadinessCannotHideAnUnrepairedSoftSafetyProbe() {
        FindingPostconditionDTO result = evaluator.evaluate("safety_guard", review("fail", "pass"));
        assertFalse(result.getSatisfied());
        assertTrue(result.getHardFeasible());
        assertEquals("repair_goal_unreachable", result.getReasonCode());
    }

    @Test
    void rejectsUnknownMissingAndDuplicateOriginalProbe() {
        ReviewStateDTO review = review("unknown", "pass");
        assertUnavailable(evaluator.evaluate("safety_guard", review));
        review.getFindings().remove(0);
        assertUnavailable(evaluator.evaluate("safety_guard", review));
        review.getFindings().add(finding("safety_guard", "pass", "soft"));
        review.getFindings().add(finding("safety_guard", "pass", "soft"));
        assertUnavailable(evaluator.evaluate("safety_guard", review));
    }

    @Test
    void rejectsUnavailableIncompleteAndUnversionedEvaluation() {
        assertUnavailable(evaluator.evaluate("safety_guard", null));
        ReviewStateDTO review = review("pass", "pass");
        review.setEvaluationStatus("unavailable");
        assertUnavailable(evaluator.evaluate("safety_guard", review));
        review.setEvaluationStatus("completed");
        review.setProbesRun(0);
        assertUnavailable(evaluator.evaluate("safety_guard", review));
        review.setProbesRun(2);
        review.setEvaluationVersion(null);
        assertUnavailable(evaluator.evaluate("safety_guard", review));
    }

    @Test
    void recomputesHardFeasibilityRatherThanTrustingAggregateFlag() {
        FindingPostconditionDTO result = evaluator.evaluate("safety_guard", review("pass", "fail"));
        assertFalse(result.getSatisfied());
        assertFalse(result.getHardFeasible());
        assertEquals("hard_constraints_unsatisfied", result.getReasonCode());
        assertUnavailable(evaluator.evaluate("safety_guard", review("pass", "unknown")));
    }

    @Test
    void rejectsMissingHardEvidenceAndExplicitAggregateFailure() {
        ReviewStateDTO review = review("pass", "pass");
        review.getFindings().remove(1);
        assertUnavailable(evaluator.evaluate("safety_guard", review));
        review = review("pass", "pass");
        review.setHardFeasible(false);
        assertFalse(evaluator.evaluate("safety_guard", review).getSatisfied());
    }

    @Test
    void respectsConfirmedGoalsWithoutBlockingOnUnrelatedSoftFindings() {
        ReviewStateDTO review = review("pass", "pass");
        review.getFindings().add(finding("high_tuition", "fail", "soft"));
        review.setProbesRun(3);
        assertTrue(evaluator.evaluate("safety_guard", review).getSatisfied());
        review.getFindings().add(finding("count_target", "fail", "soft"));
        review.setProbesRun(4);
        assertFalse(evaluator.evaluate("safety_guard", review).getSatisfied());
    }

    @Test
    void missingOptionalCountTargetIsNotAHardGoal() {
        ReviewStateDTO review = review("pass", "pass");
        review.getFindings().add(finding("count_target", "not_applicable", "soft"));
        review.setProbesRun(3);
        assertTrue(evaluator.evaluate("safety_guard", review).getSatisfied());
    }

    @Test
    void incompleteProbeCountAndDuplicateEvidenceFailClosed() {
        ReviewStateDTO review = review("pass", "pass");
        review.setProbesRun(3);
        assertUnavailable(evaluator.evaluate("safety_guard", review));
        review.getFindings().add(finding("count_validation_hard", "pass", "hard"));
        assertUnavailable(evaluator.evaluate("safety_guard", review));
    }

    private void assertUnavailable(FindingPostconditionDTO result) {
        assertFalse(result.getSatisfied());
        assertEquals("review_fix_evaluation_unavailable", result.getReasonCode());
    }

    private ReviewStateDTO review(String probeStatus, String hardStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible(true);
        review.setFindings(Lists.newArrayList(finding("safety_guard", probeStatus, "soft"),
                finding("count_validation_hard", hardStatus, "hard")));
        return review;
    }

    private EvaluationFindingDTO finding(String code, String status, String strength) {
        EvaluationFindingDTO finding = new EvaluationFindingDTO();
        finding.setCode(code);
        finding.setResultStatus(status);
        finding.setRuleStrength(strength);
        return finding;
    }
}
