package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FindingPostconditionDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

import java.util.HashSet;
import java.util.Set;

public final class FindingPostconditionEvaluator {

    public FindingPostconditionDTO evaluate(String findingCode, ReviewStateDTO freshlyEvaluatedReview) {
        FindingPostconditionDTO result = new FindingPostconditionDTO();
        result.setFindingCode(findingCode);
        if (Strings.isNullOrEmpty(findingCode) || freshlyEvaluatedReview == null
                || !"completed".equals(freshlyEvaluatedReview.getEvaluationStatus())
                || Strings.isNullOrEmpty(freshlyEvaluatedReview.getEvaluationVersion())
                || freshlyEvaluatedReview.getProbesRun() == null
                || freshlyEvaluatedReview.getProbesRun() <= 0
                || freshlyEvaluatedReview.getFindings() == null
                || freshlyEvaluatedReview.getProbesRun() != freshlyEvaluatedReview.getFindings().size()) {
            return result;
        }
        result.setEvaluationVersion(freshlyEvaluatedReview.getEvaluationVersion());
        EvaluationFindingDTO originalProbe = null;
        boolean hasHardEvidence = false;
        boolean hardFeasible = true;
        Set<String> codes = new HashSet<String>();
        for (EvaluationFindingDTO finding : freshlyEvaluatedReview.getFindings()) {
            if (finding == null || Strings.isNullOrEmpty(finding.getCode())
                    || Strings.isNullOrEmpty(finding.getRuleStrength()) || !codes.add(finding.getCode())) {
                return result;
            }
            if (findingCode.equals(finding.getCode())) {
                if (originalProbe != null) {
                    return result;
                }
                originalProbe = finding;
            }
            if ("hard".equals(finding.getRuleStrength()) || confirmedGoal(finding)) {
                if ("count_target".equals(finding.getCode())
                        && "not_applicable".equals(finding.getResultStatus())) {
                    continue;
                }
                hasHardEvidence |= "hard".equals(finding.getRuleStrength());
                if (!knownStatus(finding.getResultStatus())) {
                    return result;
                }
                hardFeasible &= "pass".equals(finding.getResultStatus());
            }
        }
        if (!hasHardEvidence || originalProbe == null || !knownStatus(originalProbe.getResultStatus())
                || freshlyEvaluatedReview.getHardFeasible() == null) {
            return result;
        }
        hardFeasible &= Boolean.TRUE.equals(freshlyEvaluatedReview.getHardFeasible());
        boolean probeSatisfied = "pass".equals(originalProbe.getResultStatus());
        result.setProbeSatisfied(probeSatisfied);
        result.setHardFeasible(hardFeasible);
        result.setSatisfied(probeSatisfied && hardFeasible);
        result.setReasonCode(!probeSatisfied ? "repair_goal_unreachable"
                : !hardFeasible ? "hard_constraints_unsatisfied" : null);
        return result;
    }

    private boolean knownStatus(String status) {
        return "pass".equals(status) || "fail".equals(status);
    }

    private boolean confirmedGoal(EvaluationFindingDTO finding) {
        return "count_target".equals(finding.getCode())
                || finding.getCode().startsWith("coverage:")
                || ("ratio_distribution".equals(finding.getCode()) && finding.getThreshold() != null
                && finding.getThreshold().containsKey("sprintActual"));
    }
}
