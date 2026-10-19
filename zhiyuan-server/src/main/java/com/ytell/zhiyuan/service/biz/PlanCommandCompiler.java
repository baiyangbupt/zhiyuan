package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.alibaba.fastjson.serializer.SerializerFeature;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.ObjectiveDeltaDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.TreeSet;

public class PlanCommandCompiler {

    public PlanCommandDTO compile(ObjectiveDeltaDTO delta, EvaluationContextDTO context) {
        if (delta == null || context == null || !isSupported(delta.getStrategy())
                || !validRefs(delta.getRemoveTargets()) || !validRefs(delta.getReorderTargets())
                || !validRefs(delta.getAddTargets())) {
            return null;
        }
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy(delta.getStrategy());
        command.setSourceStrategy(delta.getStrategy());
        command.setApplyStrategy(isSearch(delta.getStrategy())
                ? RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT : delta.getStrategy());
        command.setSourceCheck(delta.getSourceCheck());
        command.setReasonCode(delta.getReasonCode());
        command.setLevel("major_group".equals(context.getAdmissionMode()) ? "unit"
                : "major".equals(context.getAdmissionMode()) ? "volunteer" : null);
        if (command.getLevel() == null && context.getEntries() != null && !context.getEntries().isEmpty()) {
            command.setLevel(context.getEntries().get(0).getLevel());
        }
        command.setTargetCount(delta.getTargetCount());
        if (command.getTargetCount() == null && delta.getTargetCountDelta() != null) {
            command.setTargetCount(Math.addExact(context.getEntries().size(), delta.getTargetCountDelta()));
        }
        if (command.getTargetCount() != null && command.getTargetCount() < 0) {
            return null;
        }
        if (command.getTargetCount() == null && (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(delta.getStrategy())
                || "count_validation".equals(delta.getSourceCheck()))) {
            return null;
        }
        command.setTierConstraint(copy(delta.getTierConstraint(), TierAllocationConstraintDTO.class));
        command.setSafetyMinLocalProtect(delta.getSafetyMinLocalProtect());
        command.setCoverageRequirements(canonicalCoverage(delta.getCoverageRequirements()));
        if (delta.getConstraintPatch() != null && !delta.getConstraintPatch().isEmpty()) {
            command.setConstraintPatch(canonicalConstraints(delta.getConstraintPatch()));
        }
        command.setForcedRemoveTargets(refs(delta.getRemoveTargets(), true));
        command.setReorderTargets(refs(delta.getReorderTargets(), false));
        List<EvaluationEntryRefDTO> targets = new ArrayList<EvaluationEntryRefDTO>();
        targets.addAll(command.getForcedRemoveTargets());
        targets.addAll(command.getReorderTargets());
        targets.addAll(refs(delta.getAddTargets(), true));
        command.setTargets(refs(targets, true));
        command.setEvaluationVersion(EvaluationVersion.evaluationVersion(context.getEvaluatedStateVersion(),
                context.getPlanContentDigest(), context.getCandidateSourceVersion(), context.getDataVersion(),
                EvaluationVersion.objectiveModelVersion()));
        if (Strings.isNullOrEmpty(command.getEvaluationVersion())) {
            return null;
        }
        Map<String, Object> canonical = new TreeMap<String, Object>();
        canonical.put("evaluationVersion", command.getEvaluationVersion());
        canonical.put("commandType", command.getCommandType());
        canonical.put("strategy", command.getStrategy());
        canonical.put("applyStrategy", command.getApplyStrategy());
        canonical.put("sourceStrategy", command.getSourceStrategy());
        canonical.put("sourceCheck", command.getSourceCheck());
        canonical.put("reasonCode", command.getReasonCode());
        canonical.put("level", command.getLevel());
        canonical.put("targetCount", command.getTargetCount());
        canonical.put("tierTargetCounts", command.getTierTargetCounts());
        canonical.put("tierConstraint", command.getTierConstraint());
        canonical.put("safetyMinLocalProtect", command.getSafetyMinLocalProtect());
        canonical.put("coverageRequirements", command.getCoverageRequirements());
        canonical.put("constraintPatch", command.getConstraintPatch());
        canonical.put("targets", identities(command.getTargets()));
        canonical.put("forcedRemoveTargets", identities(command.getForcedRemoveTargets()));
        canonical.put("replacementPairs", command.getReplacementPairs());
        canonical.put("reorderTargets", identities(command.getReorderTargets()));
        command.setCommandDigest(EvaluationVersion.sha256(JSON.toJSONString(canonical,
                SerializerFeature.MapSortField, SerializerFeature.SortField, SerializerFeature.WriteMapNullValue)));
        return command;
    }

    private boolean isSearch(String strategy) {
        return RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(strategy)
                || RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS.equals(strategy)
                || RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO.equals(strategy)
                || RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE.equals(strategy)
                || RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS.equals(strategy);
    }

    private boolean isSupported(String strategy) {
        return isSearch(strategy) || RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS.equals(strategy)
                || RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY.equals(strategy);
    }

    private boolean validRefs(List<EvaluationEntryRefDTO> refs) {
        if (refs == null) {
            return true;
        }
        for (EvaluationEntryRefDTO ref : refs) {
            if (ref == null || Strings.isNullOrEmpty(ref.getId()) || ref.getId().trim().isEmpty()
                    || !("unit".equals(ref.getLevel()) || "volunteer".equals(ref.getLevel()))) {
                return false;
            }
        }
        return true;
    }

    private HardConstraintsDTO canonicalConstraints(Map<String, Object> patch) {
        HardConstraintsDTO constraints = JSON.parseObject(JSON.toJSONString(patch), HardConstraintsDTO.class);
        JSONObject canonical = (JSONObject) JSON.toJSON(constraints);
        for (String key : canonical.keySet()) {
            if (canonical.getJSONArray(key) != null) {
                TreeSet<String> values = new TreeSet<String>();
                for (String value : canonical.getJSONArray(key).toJavaList(String.class)) {
                    if (value != null) {
                        values.add(value);
                    }
                }
                canonical.put(key, new ArrayList<String>(values));
            }
        }
        return JSON.parseObject(canonical.toJSONString(), HardConstraintsDTO.class);
    }

    private List<CoverageRequirementDTO> canonicalCoverage(List<CoverageRequirementDTO> requirements) {
        Map<String, CoverageRequirementDTO> merged = new TreeMap<String, CoverageRequirementDTO>();
        if (requirements == null) {
            return new ArrayList<CoverageRequirementDTO>();
        }
        for (CoverageRequirementDTO requirement : requirements) {
            if (requirement == null) {
                continue;
            }
            CoverageRequirementDTO normalized = copy(requirement, CoverageRequirementDTO.class);
            TreeSet<String> values = new TreeSet<String>();
            if (normalized.getValues() != null) {
                for (String value : normalized.getValues()) {
                    if (!Strings.isNullOrEmpty(value)) {
                        values.add(value);
                    }
                }
            }
            normalized.setValues(new ArrayList<String>(values));
            normalized.setMinCount(CoverageRequirementSupport.minCount(requirement));
            String identity = JSON.toJSONString(java.util.Arrays.asList(normalized.getDomain(), normalized.getKey(), normalized.getValues()));
            CoverageRequirementDTO previous = merged.get(identity);
            if (previous == null || previous.getMinCount() < normalized.getMinCount()) {
                merged.put(identity, normalized);
            }
        }
        return new ArrayList<CoverageRequirementDTO>(merged.values());
    }

    private List<EvaluationEntryRefDTO> refs(List<EvaluationEntryRefDTO> source, boolean sort) {
        List<EvaluationEntryRefDTO> result = new ArrayList<EvaluationEntryRefDTO>();
        TreeSet<String> seen = new TreeSet<String>();
        if (source != null) {
            for (EvaluationEntryRefDTO ref : source) {
                if (ref != null && !Strings.isNullOrEmpty(ref.getId())
                        && seen.add(ref.getLevel() + ":" + ref.getId())) {
                    result.add(copy(ref, EvaluationEntryRefDTO.class));
                }
            }
        }
        if (sort) {
            result.sort(Comparator.comparing(ref -> ref.getLevel() + ":" + ref.getId()));
        }
        return result;
    }

    private List<List<String>> identities(List<EvaluationEntryRefDTO> refs) {
        List<List<String>> identities = new ArrayList<List<String>>();
        for (EvaluationEntryRefDTO ref : refs) {
            identities.add(java.util.Arrays.asList(ref.getLevel(), ref.getId()));
        }
        return identities;
    }

    private <Value> Value copy(Value value, Class<Value> type) {
        return value == null ? null : JSON.parseObject(JSON.toJSONString(value), type);
    }
}
