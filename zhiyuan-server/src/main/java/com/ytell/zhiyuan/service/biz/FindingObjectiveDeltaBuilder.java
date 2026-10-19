package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.ObjectiveDeltaDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;

public class FindingObjectiveDeltaBuilder {

    public ObjectiveDeltaDTO build(EvaluationFindingDTO finding, EvaluationContextDTO context) {
        if (!"fail".equals(finding.getResultStatus())
                || "needs_input".equals(finding.getFixability())
                || "none".equals(finding.getFixability())
                || "policy".equals(finding.getRuleStrength())) {
            return null;
        }
        ObjectiveDeltaDTO delta = new ObjectiveDeltaDTO();
        delta.setSourceCheck(finding.getCode());
        delta.setReasonCode(finding.getReasonCode());
        String code = finding.getCode();
        switch (code.startsWith("coverage:") ? "coverage" : code) {
            case "count_target":
                if (context.getSelectionTargetCount() == null || context.getSelectionTargetCount() <= 0) {
                    return null;
                }
                delta.setSourceCheck("count_validation");
                delta.setStrategy(RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT);
                delta.setTargetCount(context.getSelectionTargetCount());
                break;
            case "count_validation_hard":
                if (context.getRequiredCount() == null || context.getRequiredCount() <= 0) {
                    return null;
                }
                delta.setSourceCheck("count_validation");
                delta.setStrategy("count_over_limit".equals(finding.getReasonCode())
                        ? RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS
                        : RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT);
                delta.setTargetCount(context.getRequiredCount());
                break;
            case "safety_guard":
                if (!"applicable".equals(context.getSafetyFloorMode())
                        || context.getSafetyMinLocalProtect() == null
                        || context.getSafetyMinLocalProtect() <= 0) {
                    return null;
                }
                delta.setStrategy(RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS);
                delta.setSafetyMinLocalProtect(context.getSafetyMinLocalProtect());
                delta.setTargetCount(baseTarget(context));
                break;
            case "ratio_distribution":
                if (context.getTierConstraint() == null) {
                    return null;
                }
                delta.setStrategy(RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO);
                delta.setTierConstraint(JSON.parseObject(JSON.toJSONString(context.getTierConstraint()),
                        TierAllocationConstraintDTO.class));
                delta.setTargetCount(baseTarget(context));
                break;
            case "coverage":
                delta.setSourceCheck("coverage");
                delta.setStrategy(RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE);
                delta.setCoverageRequirements(JSON.parseArray(JSON.toJSONString(context.getCoverageRequirements()),
                        CoverageRequirementDTO.class));
                delta.setTargetCount(baseTarget(context));
                break;
            case "probability_inversion":
                delta.setStrategy(RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY);
                delta.getReorderTargets().addAll(finding.getAffectedEntryRefs());
                break;
            case "high_tuition":
            case "cooperative_program":
                delta.setStrategy(RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS);
                delta.getRemoveTargets().addAll(finding.getAffectedEntryRefs());
                delta.setTargetCount(baseTarget(context));
                break;
            case "admission_limit":
            case "special_enrollment":
                delta.setStrategy(RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS);
                delta.getRemoveTargets().addAll(finding.getAffectedEntryRefs());
                break;
            default:
                return null;
        }
        if (delta.getTargetCount() != null) {
            delta.setTargetCountDelta(delta.getTargetCount() - context.getEntries().size());
        }
        return delta;
    }

    private Integer baseTarget(EvaluationContextDTO context) {
        return context.getSelectionTargetCount() != null ? context.getSelectionTargetCount()
                : context.getRequiredCount() != null ? context.getRequiredCount() : context.getEntries().size();
    }
}
