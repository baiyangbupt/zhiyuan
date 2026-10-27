package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DiversityPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureQualityPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import com.ytell.zhiyuan.model.dto.planning.UtilityModelDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationResolutionDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

final class PlanningObjectiveCompiler {

    static final String SCHEMA_VERSION = "4.1.0-m2";
    static final String SCHEMA_VERSION_V2 = "4.2.0-j53";
    static final String SOLVER_OBJECTIVE_VERSION = "solver-objective-v1";
    private static final String FILL_TO_COUNT = "fill_to_count";
    private static final String PRIORITIZE_WITHIN_TIER = "prioritize_within_tier";

    private PlanningObjectiveCompiler() {
    }

    static CanonicalPlanningObjectiveSetDTO compile(PlanningStateDTO state,
                                                     UserGoalFixProposalReq request) {
        if (request == null) {
            throw new CompilationException("objective_request_missing", "用户目标请求不能为空。");
        }
        String goalType = normalized(request.getGoalType());
        if (!FILL_TO_COUNT.equals(goalType) && !PRIORITIZE_WITHIN_TIER.equals(goalType)) {
            throw new CompilationException("objective_goal_type_not_supported",
                    "M1 canonical compiler 只承接 fill_to_count 和 prioritize_within_tier。");
        }
        validateRequest(state, request, goalType);

        CanonicalPlanningObjectiveSetDTO result = base(state);
        if (FILL_TO_COUNT.equals(goalType)) {
            result.setTargetCount(request.getTargetCount());
        }
        result.setEligibilityConstraints(canonicalHardConstraints(
                ProjectedHardRequirementSupport.project(state, request.getRequirements())));
        result.setCoverageConstraints(mergedCoverage(state, request.getRequirements()));
        applyTierAllocation(result, compileTierAllocation(
                state, request.getTierQuotaGoal(), result.getTargetCount()));
        result.setOrderingConstraints(request.getPriorityRules() == null || request.getPriorityRules().isEmpty()
                ? canonicalPriorityRules(PriorityRuleSupport.confirmedRules(state))
                : canonicalPriorityRules(request.getPriorityRules()));
        freezeDigest(result);
        return result;
    }

    static CanonicalPlanningObjectiveSetDTO compileConfirmed(PlanningStateDTO state) {
        CanonicalPlanningObjectiveSetDTO result = base(state);
        result.setEligibilityConstraints(canonicalHardConstraints(
                ProjectedHardRequirementSupport.project(state, Lists.newArrayList())));
        result.setCoverageConstraints(canonicalCoverage(
                CoverageRequirementSupport.confirmedRequirements(state)));
        applyTierAllocation(result, compileConfirmedTierAllocation(state, result.getTargetCount()));
        result.setOrderingConstraints(canonicalPriorityRules(PriorityRuleSupport.confirmedRules(state)));
        freezeDigest(result);
        return result;
    }

    /**
     * J5.3：在已编译的硬目标上补 StructureTarget/UtilityModel/MutationPolicy，
     * 并重新冻结 digest。旧路径不调用此方法，digest 不变。
     */
    static CanonicalPlanningObjectiveSetDTO enrichV2(PlanningStateDTO state,
                                                     CanonicalPlanningObjectiveSetDTO source,
                                                     MutationPolicyDTO policy) {
        if (source == null) {
            return null;
        }
        source.setSchemaVersion(SCHEMA_VERSION_V2);
        StructureTargetDTO structureTarget = SafetyFloorSupport.build(state);
        // S2：显式 quota 的单点锚优先；范围配额/无配额保持 solver 投影。
        com.ytell.zhiyuan.model.dto.planning.TierCountsDTO tierAnchor =
                TierQuotaResolver.explicitAnchor(state);
        if (tierAnchor != null) {
            structureTarget.setTierAnchor(tierAnchor);
        }
        source.setStructureTarget(structureTarget);
        source.setUtilityModel(new UtilityModelDTO());
        source.setMutationPolicy(policy);
        // P4 灰度：仅在显式开启时写入 soft 策略；默认保持 null（off）。
        // diversityPolicy 不在 digest 白名单内，冻结值不受影响。
        if (SolverFeatureFlags.diversityEnabled()) {
            DiversityPolicyDTO diversity = new DiversityPolicyDTO();
            diversity.setMode("soft");
            source.setDiversityPolicy(diversity);
        }
        String structureQualityMode = SolverFeatureFlags.structureQualityMode();
        if (!"off".equals(structureQualityMode)) {
            StructureQualityPolicyDTO structureQuality = new StructureQualityPolicyDTO();
            structureQuality.setMode(structureQualityMode);
            structureQuality.setMaxUtilityLossRatio(
                    SolverFeatureFlags.structureQualityMaxUtilityLossRatio());
            source.setStructureQualityPolicy(structureQuality);
        }
        source.setHardObjectiveVersion(StagedDeterministicPlanSolver.HARD_OBJECTIVE_VERSION);
        source.setSolverObjectiveVersion(SOLVER_OBJECTIVE_VERSION);
        freezeDigest(source);
        return source;
    }

    private static CanonicalPlanningObjectiveSetDTO base(PlanningStateDTO state) {
        CanonicalPlanningObjectiveSetDTO result = new CanonicalPlanningObjectiveSetDTO();
        result.setSchemaVersion(SCHEMA_VERSION);
        result.setSourceVersion(state == null ? null : state.getVersion());
        CandidatePoolStateDTO pool = state == null ? null : state.getCandidatePoolState();
        result.setCountMode(pool != null && "majorgroup".equals(normalized(pool.getVolunteerModel()))
                ? "unit" : "volunteer");
        Integer confirmedTarget = state == null || state.getConstraintState() == null
                || state.getConstraintState().getHardPlanningObjectives() == null ? null
                : state.getConstraintState().getHardPlanningObjectives().getSelectionTargetCount();
        result.setTargetCount(confirmedTarget == null
                ? pool == null ? null : pool.getRequiredCount() : confirmedTarget);
        return result;
    }

    private static void validateRequest(PlanningStateDTO state,
                                        UserGoalFixProposalReq request,
                                        String goalType) {
        if (FILL_TO_COUNT.equals(goalType)
                && (request.getTargetCount() == null || request.getTargetCount() <= 0)) {
            throw new CompilationException("selection_target_invalid",
                    "补齐目标数量必须是大于 0 的整数。");
        }
        String requirementError = ProjectedHardRequirementSupport.validate(request.getRequirements());
        if (!Strings.isNullOrEmpty(requirementError)) {
            throw new CompilationException("projected_requirements_invalid", requirementError);
        }
        String priorityError = PriorityRuleSupport.validate(request.getPriorityRules());
        if (!Strings.isNullOrEmpty(priorityError)) {
            throw new CompilationException("priority_rule_invalid", priorityError);
        }
        boolean hasRequestedTierGoal = request.getTierQuotaGoal() != null;
        boolean exactRequestedTierGoal = hasRequestedTierGoal
                && "exact_counts".equalsIgnoreCase(request.getTierQuotaGoal().getType());
        boolean hasRequestedRequirements = !defaultList(request.getRequirements()).isEmpty();
        boolean hasRequestedPriorities = !defaultList(request.getPriorityRules()).isEmpty();
        boolean hasConfirmedTierGoal = TierAllocationSupport.confirmedGoal(state) != null;
        boolean hasConfirmedCoverage = !defaultList(
                CoverageRequirementSupport.confirmedRequirements(state)).isEmpty();
        boolean hasConfirmedPriorities = !defaultList(
                PriorityRuleSupport.confirmedRules(state)).isEmpty();
        // 精确配额可以作为本轮要求的一部分与 coverage 同时编译；范围/比例配额
        // 仍要求先单独确认，避免把未验证的组合当成原子动作。
        if (hasRequestedTierGoal && (hasRequestedPriorities || hasConfirmedCoverage
                || hasConfirmedPriorities
                || (!exactRequestedTierGoal && hasRequestedRequirements))
                || hasConfirmedTierGoal && (hasRequestedRequirements || hasRequestedPriorities)) {
            throw new CompilationException("tier_quota_composite_not_supported",
                    "冲稳保目标暂不能与该组合一起新建或修改；精确配额 + 专业要求请直接走同一张卡。");
        }
        if (hasRequestedTierGoal && !FILL_TO_COUNT.equals(goalType)) {
            throw new CompilationException("tier_quota_invalid",
                    "冲稳保目标只支持 fill_to_count 方案目标。");
        }
        if (PRIORITIZE_WITHIN_TIER.equals(goalType)
                && defaultList(request.getPriorityRules()).isEmpty()) {
            throw new CompilationException("priority_rule_invalid",
                    "prioritize_within_tier 需要一条明确的优先规则。");
        }
    }

    private static TierAllocationSupport.CompiledTierAllocation compileTierAllocation(
            PlanningStateDTO state,
            com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO request,
            Integer targetCount) {
        try {
            return TierAllocationSupport.compile(state, request, targetCount);
        } catch (TierAllocationSupport.ContractException ex) {
            throw new CompilationException(ex.getReasonCode(), ex.getMessage());
        }
    }

    private static TierAllocationSupport.CompiledTierAllocation compileConfirmedTierAllocation(
            PlanningStateDTO state,
            Integer targetCount) {
        try {
            return TierAllocationSupport.compileConfirmed(state, targetCount);
        } catch (TierAllocationSupport.ContractException ex) {
            throw new CompilationException(ex.getReasonCode(), ex.getMessage());
        }
    }

    private static void applyTierAllocation(
            CanonicalPlanningObjectiveSetDTO result,
            TierAllocationSupport.CompiledTierAllocation compiled) {
        result.setTierAllocationGoal(compiled.getCanonicalGoal());
        result.setTierAllocationConstraint(compiled.getConstraint());
        result.setTierAllocationResolution(compiled.getResolution());
        result.setTierAllocationStateChanged(compiled.isStateChanged());
    }

    private static HardConstraintsDTO canonicalHardConstraints(HardConstraintsDTO source) {
        HardConstraintsDTO result = new HardConstraintsDTO();
        result.setMustIncludeRegions(sortedValues(source == null ? null : source.getMustIncludeRegions()));
        result.setMustExcludeRegions(sortedValues(source == null ? null : source.getMustExcludeRegions()));
        result.setMustIncludeMajors(sortedValues(source == null ? null : source.getMustIncludeMajors()));
        result.setMustExcludeMajors(sortedValues(source == null ? null : source.getMustExcludeMajors()));
        result.setMustIncludeSchools(sortedValues(source == null ? null : source.getMustIncludeSchools()));
        result.setMustExcludeSchools(sortedValues(source == null ? null : source.getMustExcludeSchools()));
        return result;
    }

    private static List<CoverageRequirementDTO> mergedCoverage(
            PlanningStateDTO state,
            List<UserGoalFixProposalReq.RequirementDTO> requirements) {
        Map<String, CoverageRequirementDTO> merged = new LinkedHashMap<String, CoverageRequirementDTO>();
        for (CoverageRequirementDTO objective : canonicalCoverage(
                CoverageRequirementSupport.confirmedRequirements(state))) {
            merged.put(coverageIdentity(objective), objective);
        }
        for (UserGoalFixProposalReq.RequirementDTO requirement : defaultList(requirements)) {
            if (requirement == null || !ProjectedHardRequirementSupport.KIND_INCLUDE.equals(
                    normalized(requirement.getKind()))) {
                continue;
            }
            CoverageRequirementDTO objective = canonicalCoverage(
                    CoverageRequirementSupport.canonicalize(requirement));
            CoverageRequirementDTO existing = merged.get(coverageIdentity(objective));
            if (existing == null) {
                merged.put(coverageIdentity(objective), objective);
            } else {
                existing.setMinCount(Math.max(existing.getMinCount(), objective.getMinCount()));
            }
        }
        return sortedCoverage(merged.values());
    }

    private static List<CoverageRequirementDTO> canonicalCoverage(List<CoverageRequirementDTO> source) {
        List<CoverageRequirementDTO> result = new ArrayList<CoverageRequirementDTO>();
        for (CoverageRequirementDTO item : defaultList(source)) {
            if (item != null) {
                result.add(canonicalCoverage(item));
            }
        }
        return sortedCoverage(result);
    }

    private static CoverageRequirementDTO canonicalCoverage(CoverageRequirementDTO source) {
        CoverageRequirementDTO result = new CoverageRequirementDTO();
        result.setDomain(normalized(source == null ? null : source.getDomain()));
        result.setKey(normalized(source == null ? null : source.getKey()));
        result.setValues(sortedValues(source == null ? null : source.getValues()));
        result.setMinCount(source == null || source.getMinCount() == null ? 1 : source.getMinCount());
        return result;
    }

    private static List<CoverageRequirementDTO> sortedCoverage(Iterable<CoverageRequirementDTO> values) {
        List<CoverageRequirementDTO> result = new ArrayList<CoverageRequirementDTO>();
        for (CoverageRequirementDTO value : values) {
            result.add(value);
        }
        result.sort(Comparator.comparing(PlanningObjectiveCompiler::coverageIdentity));
        return result;
    }

    private static String coverageIdentity(CoverageRequirementDTO requirement) {
        return normalized(requirement == null ? null : requirement.getDomain()) + "|"
                + normalized(requirement == null ? null : requirement.getKey()) + "|"
                + String.join("\u001f", sortedValues(requirement == null ? null : requirement.getValues()));
    }

    private static List<PriorityRuleDTO> canonicalPriorityRules(List<PriorityRuleDTO> source) {
        List<PriorityRuleDTO> result = new ArrayList<PriorityRuleDTO>();
        for (PriorityRuleDTO rule : defaultList(source)) {
            if (rule == null) {
                continue;
            }
            PriorityRuleDTO canonical = new PriorityRuleDTO();
            canonical.setDomain(normalized(rule.getDomain()));
            canonical.setKey(normalized(rule.getKey()));
            canonical.setValues(sortedValues(rule.getValues()));
            canonical.setOrderingTarget(Strings.isNullOrEmpty(Strings.nullToEmpty(
                    rule.getOrderingTarget()).trim()) ? PriorityRuleSupport.ORDERING_RANK_BEFORE
                    : normalized(rule.getOrderingTarget()));
            canonical.setScope(Strings.isNullOrEmpty(Strings.nullToEmpty(rule.getScope()).trim())
                    ? PriorityRuleSupport.SCOPE_WITHIN_TIER : normalized(rule.getScope()));
            canonical.setRawText(null);
            result.add(canonical);
        }
        return result;
    }

    static String solverObjectiveDigest(CanonicalPlanningObjectiveSetDTO objectiveSet) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("objectiveDigest", digest(objectiveSet));
        payload.put("utilityModel", objectiveSet.getUtilityModel());
        payload.put("diversityPolicy", objectiveSet.getDiversityPolicy());
        return EvaluationVersion.sha256(com.alibaba.fastjson.JSON.toJSONString(payload));
    }

    private static String digest(CanonicalPlanningObjectiveSetDTO objectiveSet) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("schemaVersion", objectiveSet.getSchemaVersion());
        payload.put("countMode", objectiveSet.getCountMode());
        payload.put("targetCount", objectiveSet.getTargetCount());
        payload.put("eligibilityConstraints", objectiveSet.getEligibilityConstraints());
        payload.put("coverageConstraints", objectiveSet.getCoverageConstraints());
        payload.put("tierAllocationGoal", objectiveSet.getTierAllocationGoal());
        payload.put("tierAllocationConstraint", objectiveSet.getTierAllocationConstraint());
        payload.put("tierAllocationResolution", canonicalResolution(
                objectiveSet.getTierAllocationResolution()));
        payload.put("orderingConstraints", objectiveSet.getOrderingConstraints());
        // 旧路径字段为 null，不写入，保证旧 objectiveDigest 不变。
        if (objectiveSet.getStructureTarget() != null) {
            payload.put("structureTarget", objectiveSet.getStructureTarget());
        }
        if (objectiveSet.getMutationPolicy() != null) {
            payload.put("mutationPolicy", objectiveSet.getMutationPolicy());
        }
        if (objectiveSet.getStructureQualityPolicy() != null) {
            payload.put("structureQualityPolicy", objectiveSet.getStructureQualityPolicy());
        }
        if (!Strings.isNullOrEmpty(objectiveSet.getHardObjectiveVersion())) {
            payload.put("hardObjectiveVersion", objectiveSet.getHardObjectiveVersion());
        }
        // 求解目标契约版本参与冻结：solverObjectiveVersion 变化意味着
        // utility/policy 的解释方式变了，旧 pending 不应继续确认。
        if (!Strings.isNullOrEmpty(objectiveSet.getSolverObjectiveVersion())) {
            payload.put("solverObjectiveVersion", objectiveSet.getSolverObjectiveVersion());
        }
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return toHex(digest.digest(JSON.toJSONString(payload).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    private static Map<String, Object> canonicalResolution(TierAllocationResolutionDTO resolution) {
        if (resolution == null) {
            return null;
        }
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("targetCount", resolution.getTargetCount());
        payload.put("effectiveBounds", resolution.getEffectiveBounds());
        payload.put("canonicalWeights", resolution.getCanonicalWeights());
        payload.put("resolvedCounts", resolution.getResolvedCounts());
        payload.put("resolutionMethod", resolution.getResolutionMethod());
        payload.put("tieBreakOrder", resolution.getTieBreakOrder());
        return payload;
    }

    private static void freezeDigest(CanonicalPlanningObjectiveSetDTO objectiveSet) {
        String objectiveDigest = digest(objectiveSet);
        objectiveSet.setObjectiveDigest(objectiveDigest);
        if (objectiveSet.getTierAllocationResolution() != null) {
            objectiveSet.getTierAllocationResolution().setObjectiveDigest(objectiveDigest);
            objectiveSet.getTierAllocationResolution().setSolverVersion(
                    StagedDeterministicPlanSolver.SOLVER_VERSION);
        }
    }

    private static String toHex(byte[] values) {
        StringBuilder result = new StringBuilder(values.length * 2);
        for (byte value : values) {
            result.append(String.format("%02x", value & 0xff));
        }
        return result.toString();
    }

    private static List<String> sortedValues(List<String> values) {
        Set<String> normalizedValues = new LinkedHashSet<String>();
        for (String value : defaultList(values)) {
            String text = Strings.nullToEmpty(value).trim();
            if (!text.isEmpty()) {
                normalizedValues.add(text);
            }
        }
        List<String> result = new ArrayList<String>(normalizedValues);
        result.sort(String::compareTo);
        return result;
    }

    private static String normalized(String value) {
        return Strings.nullToEmpty(value).trim().toLowerCase(Locale.ROOT);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    static final class CompilationException extends IllegalArgumentException {
        private final String reasonCode;

        CompilationException(String reasonCode, String message) {
            super(message);
            this.reasonCode = reasonCode;
        }

        String getReasonCode() {
            return reasonCode;
        }
    }
}
