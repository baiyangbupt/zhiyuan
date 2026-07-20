package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationResolutionDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.TierWeightsDTO;
import lombok.Data;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

final class TierAllocationSupport {

    static final String TYPE_EXACT_COUNTS = "exact_counts";
    static final String TYPE_COUNT_RANGES = "count_ranges";
    static final String TYPE_RATIOS = "ratios";
    static final String UPDATE_PATCH = "patch";
    static final String UPDATE_REPLACE = "replace";
    static final List<String> TIER_ORDER = Arrays.asList("sprint", "stable", "protect");

    private TierAllocationSupport() {
    }

    static CompiledTierAllocation compile(PlanningStateDTO state,
                                          TierQuotaGoalRequestDTO request,
                                          Integer targetCount) {
        TierQuotaGoalDTO confirmed = confirmedGoal(state);
        if (request == null && confirmed == null) {
            return new CompiledTierAllocation();
        }
        requireTarget(targetCount);

        TierQuotaGoalDTO effectiveSource = request == null
                ? copyGoal(confirmed) : applyRequest(confirmed, request, targetCount);
        SourceCompilation source = compileSource(effectiveSource, targetCount);
        TierAllocationResolutionDTO confirmedResolution = confirmedResolution(state);
        boolean stateChanged = request != null
                ? confirmed == null
                || !sameCanonicalGoal(compileSource(confirmed, targetCount).canonicalGoal,
                source.canonicalGoal)
                || confirmedResolution != null
                && !sameResolution(confirmedResolution, source.resolution)
                : confirmedResolution != null
                && !sameResolution(confirmedResolution, source.resolution);

        CompiledTierAllocation result = new CompiledTierAllocation();
        result.setRequestedGoal(minimalRequestDelta(confirmed, request));
        result.setEffectiveSourceGoal(stateChanged || confirmed == null
                ? effectiveSource : copyGoal(confirmed));
        result.setCanonicalGoal(source.canonicalGoal);
        result.setConstraint(source.constraint);
        result.setResolution(source.resolution);
        result.setStateChanged(stateChanged);
        return result;
    }

    private static TierQuotaGoalRequestDTO minimalRequestDelta(
            TierQuotaGoalDTO confirmed,
            TierQuotaGoalRequestDTO request) {
        TierQuotaGoalRequestDTO result = copyRequest(request);
        if (result == null || !TYPE_COUNT_RANGES.equals(normalized(result.getType()))
                || !UPDATE_PATCH.equals(normalized(result.getUpdateMode()))
                || confirmed != null
                && !TYPE_COUNT_RANGES.equals(normalized(confirmed.getType()))) {
            return result;
        }
        result.setSprint(changedBound(
                confirmed == null ? null : confirmed.getSprint(), request.getSprint()));
        result.setStable(changedBound(
                confirmed == null ? null : confirmed.getStable(), request.getStable()));
        result.setProtect(changedBound(
                confirmed == null ? null : confirmed.getProtect(), request.getProtect()));
        return result;
    }

    private static TierCountRangeDTO changedBound(TierCountRangeDTO confirmed,
                                                  TierCountRangeDTO requested) {
        if (requested == null) {
            return null;
        }
        Integer confirmedMin = confirmed == null || confirmed.getMinCount() == null
                ? 0 : confirmed.getMinCount();
        Integer confirmedMax = confirmed == null ? null : confirmed.getMaxCount();
        Integer changedMin = requested.getMinCount() != null
                && !equal(requested.getMinCount(), confirmedMin) ? requested.getMinCount() : null;
        Integer changedMax = requested.getMaxCount() != null
                && !equal(requested.getMaxCount(), confirmedMax) ? requested.getMaxCount() : null;
        return changedMin == null && changedMax == null ? null : bound(changedMin, changedMax);
    }

    static CompiledTierAllocation compileConfirmed(PlanningStateDTO state, Integer targetCount) {
        return compile(state, null, targetCount);
    }

    static TierQuotaGoalDTO confirmedGoal(PlanningStateDTO state) {
        HardPlanningObjectivesDTO objectives = objectives(state);
        return objectives == null ? null : objectives.getTierQuotaGoal();
    }

    static TierAllocationResolutionDTO confirmedResolution(PlanningStateDTO state) {
        HardPlanningObjectivesDTO objectives = objectives(state);
        return objectives == null ? null : objectives.getTierQuotaResolution();
    }

    static String summarize(TierQuotaGoalDTO goal) {
        return goal == null ? "" : "冲" + safe(goal.getSprintCount()) + "个、稳"
                + safe(goal.getStableCount()) + "个、保" + safe(goal.getProtectCount()) + "个";
    }

    static String canonicalTierKey(String value) {
        String text = Strings.nullToEmpty(value).trim();
        String normalized = text.toLowerCase(Locale.ROOT);
        if ("冲".equals(text) || "冲刺".equals(text)
                || "sprint".equals(normalized) || "reach".equals(normalized)) {
            return "sprint";
        }
        if ("稳".equals(text) || "稳妥".equals(text)
                || "stable".equals(normalized) || "safe".equals(normalized)) {
            return "stable";
        }
        if ("保".equals(text) || "保底".equals(text) || "兜底".equals(text) || "保险".equals(text)
                || "protect".equals(normalized)
                || "protective".equals(normalized) || "safety".equals(normalized)) {
            return "protect";
        }
        return "";
    }

    static void persist(PlanningStateDTO state,
                        TierQuotaGoalDTO effectiveSourceGoal,
                        TierAllocationResolutionDTO resolution) {
        if (state == null || effectiveSourceGoal == null) {
            return;
        }
        HardPlanningObjectivesDTO objectives = ensureObjectives(state);
        objectives.setTierQuotaGoal(copyGoal(effectiveSourceGoal));
        objectives.setTierQuotaResolution(copyResolution(resolution));
    }

    static boolean isPersisted(PlanningStateDTO state,
                               TierQuotaGoalDTO effectiveSourceGoal,
                               TierAllocationResolutionDTO resolution) {
        TierQuotaGoalDTO confirmed = confirmedGoal(state);
        if (confirmed == null || effectiveSourceGoal == null) {
            return false;
        }
        Integer targetCount = resolution == null ? null : resolution.getTargetCount();
        if (targetCount == null || targetCount <= 0) {
            return false;
        }
        return sameCanonicalGoal(
                compileSource(confirmed, targetCount).canonicalGoal,
                compileSource(effectiveSourceGoal, targetCount).canonicalGoal)
                && samePersistedResolution(confirmedResolution(state), resolution);
    }

    static boolean isLegacyExactPersisted(PlanningStateDTO state, TierQuotaGoalDTO expected) {
        TierQuotaGoalDTO confirmed = confirmedGoal(state);
        return confirmed != null && expected != null
                && TYPE_EXACT_COUNTS.equals(normalized(confirmed.getType()))
                && TYPE_EXACT_COUNTS.equals(normalized(expected.getType()))
                && equal(confirmed.getSprintCount(), expected.getSprintCount())
                && equal(confirmed.getStableCount(), expected.getStableCount())
                && equal(confirmed.getProtectCount(), expected.getProtectCount());
    }

    private static TierQuotaGoalDTO applyRequest(TierQuotaGoalDTO confirmed,
                                                 TierQuotaGoalRequestDTO request,
                                                 Integer targetCount) {
        String type = normalized(request == null ? null : request.getType());
        if (TYPE_EXACT_COUNTS.equals(type)) {
            requireReplaceOrLegacy(request.getUpdateMode());
            TierQuotaGoalDTO result = copyGoal(request);
            validateExact(result, targetCount);
            return result;
        }
        if (TYPE_COUNT_RANGES.equals(type)) {
            String updateMode = requireUpdateMode(request.getUpdateMode(), true);
            validateRequestedRanges(request);
            if (UPDATE_PATCH.equals(updateMode) && confirmed != null
                    && !TYPE_COUNT_RANGES.equals(normalized(confirmed.getType()))) {
                throw new ContractException("tier_quota_update_type_conflict",
                        "历史冲稳保目标类型不同，必须明确 replace。");
            }
            TierQuotaGoalDTO result = UPDATE_PATCH.equals(updateMode) && confirmed != null
                    ? mergeRanges(confirmed, request) : copyGoal(request);
            validateEffectiveRanges(result, targetCount);
            return result;
        }
        if (TYPE_RATIOS.equals(type)) {
            requireUpdateMode(request.getUpdateMode(), false);
            TierQuotaGoalDTO result = copyGoal(request);
            validateRatios(result);
            return result;
        }
        throw new ContractException("tier_quota_type_invalid", "冲稳保目标类型不受支持。");
    }

    private static SourceCompilation compileSource(TierQuotaGoalDTO source, Integer targetCount) {
        requireTarget(targetCount);
        if (source == null) {
            return new SourceCompilation();
        }
        String type = normalized(source.getType());
        if (TYPE_EXACT_COUNTS.equals(type)) {
            validateExact(source, targetCount);
            TierQuotaGoalDTO canonical = copyGoal(source);
            canonical.setType(TYPE_EXACT_COUNTS);
            TierCountsDTO counts = counts(
                    source.getSprintCount(), source.getStableCount(), source.getProtectCount());
            TierAllocationConstraintDTO constraint = exactConstraint(TYPE_EXACT_COUNTS, counts);
            return sourceCompilation(canonical, constraint,
                    resolution(targetCount, constraint, null, counts, "exact_counts"));
        }
        if (TYPE_COUNT_RANGES.equals(type)) {
            validateEffectiveRanges(source, targetCount);
            TierQuotaGoalDTO canonical = copyGoal(source);
            canonical.setType(TYPE_COUNT_RANGES);
            TierAllocationConstraintDTO constraint = rangeConstraint(source, targetCount);
            return sourceCompilation(canonical, constraint,
                    resolution(targetCount, constraint, null, null, "count_ranges"));
        }
        if (TYPE_RATIOS.equals(type)) {
            validateRatios(source);
            TierWeightsDTO canonicalWeights = canonicalWeights(source);
            TierCountsDTO resolved = resolveRatio(canonicalWeights, targetCount);
            TierQuotaGoalDTO canonical = new TierQuotaGoalDTO();
            canonical.setType(TYPE_RATIOS);
            canonical.setSprintWeight(canonicalWeights.getSprintWeight());
            canonical.setStableWeight(canonicalWeights.getStableWeight());
            canonical.setProtectWeight(canonicalWeights.getProtectWeight());
            TierAllocationConstraintDTO constraint = exactConstraint(TYPE_RATIOS, resolved);
            return sourceCompilation(canonical, constraint,
                    resolution(targetCount, constraint, canonicalWeights, resolved, "largest_remainder"));
        }
        throw new ContractException("tier_quota_type_invalid", "已确认冲稳保目标类型不受支持。");
    }

    private static SourceCompilation sourceCompilation(TierQuotaGoalDTO canonical,
                                                       TierAllocationConstraintDTO constraint,
                                                       TierAllocationResolutionDTO resolution) {
        SourceCompilation result = new SourceCompilation();
        result.canonicalGoal = canonical;
        result.constraint = constraint;
        result.resolution = resolution;
        return result;
    }

    private static TierQuotaGoalDTO mergeRanges(TierQuotaGoalDTO confirmed,
                                                TierQuotaGoalRequestDTO request) {
        TierQuotaGoalDTO result = copyGoal(confirmed);
        result.setType(TYPE_COUNT_RANGES);
        result.setSprint(mergeBound(confirmed.getSprint(), request.getSprint()));
        result.setStable(mergeBound(confirmed.getStable(), request.getStable()));
        result.setProtect(mergeBound(confirmed.getProtect(), request.getProtect()));
        return result;
    }

    private static TierCountRangeDTO mergeBound(TierCountRangeDTO confirmed,
                                                TierCountRangeDTO requested) {
        if (requested == null) {
            return copyBound(confirmed);
        }
        TierCountRangeDTO result = copyBound(confirmed);
        if (result == null) {
            result = new TierCountRangeDTO();
        }
        if (requested.getMinCount() != null) {
            result.setMinCount(requested.getMinCount());
        }
        if (requested.getMaxCount() != null) {
            result.setMaxCount(requested.getMaxCount());
        }
        return result;
    }

    private static void validateExact(TierQuotaGoalDTO goal, Integer targetCount) {
        if (goal.getSprintCount() == null || goal.getStableCount() == null
                || goal.getProtectCount() == null) {
            throw new ContractException("tier_exact_counts_required", "冲稳保精确配额必须完整。");
        }
        if (goal.getSprintCount() < 0 || goal.getStableCount() < 0 || goal.getProtectCount() < 0) {
            throw new ContractException("tier_exact_count_invalid", "冲稳保精确配额必须是非负整数。");
        }
        long total = (long) goal.getSprintCount() + goal.getStableCount() + goal.getProtectCount();
        if (total != targetCount) {
            throw new ContractException("tier_exact_total_mismatch", "冲稳保精确配额合计必须等于目标总数。");
        }
    }

    private static void validateRequestedRanges(TierQuotaGoalRequestDTO request) {
        if (request.getSprint() == null && request.getStable() == null && request.getProtect() == null) {
            throw new ContractException("tier_range_empty", "count_ranges 至少需要一个档位边界。");
        }
        validateBound(request.getSprint(), false);
        validateBound(request.getStable(), false);
        validateBound(request.getProtect(), false);
    }

    private static void validateEffectiveRanges(TierQuotaGoalDTO goal, Integer targetCount) {
        validateBound(goal.getSprint(), true);
        validateBound(goal.getStable(), true);
        validateBound(goal.getProtect(), true);
        TierAllocationConstraintDTO constraint = rangeConstraint(goal, targetCount);
        long sumMin = (long) constraint.getSprint().getMinCount()
                + constraint.getStable().getMinCount() + constraint.getProtect().getMinCount();
        long sumMax = (long) constraint.getSprint().getMaxCount()
                + constraint.getStable().getMaxCount() + constraint.getProtect().getMaxCount();
        if (sumMin > targetCount) {
            throw new ContractException("tier_range_min_infeasible", "档位最低数量合计超过总数。");
        }
        if (sumMax < targetCount) {
            throw new ContractException("tier_range_max_infeasible", "档位最高数量合计不足总数。");
        }
    }

    private static void validateBound(TierCountRangeDTO bound, boolean allowNull) {
        if (bound == null) {
            return;
        }
        if (bound.getMinCount() == null && bound.getMaxCount() == null) {
            throw new ContractException("tier_range_bound_invalid", "档位边界至少包含 min 或 max。");
        }
        if ((bound.getMinCount() != null && bound.getMinCount() < 0)
                || (bound.getMaxCount() != null && bound.getMaxCount() < 0)
                || (bound.getMinCount() != null && bound.getMaxCount() != null
                && bound.getMinCount() > bound.getMaxCount())) {
            throw new ContractException("tier_range_bound_invalid", "档位边界必须是有效的非负整数范围。");
        }
    }

    private static void validateRatios(TierQuotaGoalDTO goal) {
        if (goal.getSprintWeight() == null || goal.getStableWeight() == null
                || goal.getProtectWeight() == null
                || goal.getSprintWeight() < 0 || goal.getStableWeight() < 0
                || goal.getProtectWeight() < 0
                || (long) goal.getSprintWeight() + goal.getStableWeight() + goal.getProtectWeight() <= 0L) {
            throw new ContractException("tier_ratio_weight_invalid", "比例权重必须完整、非负且合计大于零。");
        }
    }

    private static void requireReplaceOrLegacy(String updateMode) {
        String normalizedMode = normalized(updateMode);
        if (!normalizedMode.isEmpty() && !UPDATE_REPLACE.equals(normalizedMode)) {
            throw new ContractException("tier_quota_update_mode_invalid", "exact_counts 只允许 replace。");
        }
    }

    private static String requireUpdateMode(String updateMode, boolean patchAllowed) {
        String normalizedMode = normalized(updateMode);
        if (UPDATE_REPLACE.equals(normalizedMode)
                || patchAllowed && UPDATE_PATCH.equals(normalizedMode)) {
            return normalizedMode;
        }
        throw new ContractException("tier_quota_update_mode_invalid",
                patchAllowed ? "count_ranges 必须明确 patch 或 replace。" : "ratios 只允许 replace。");
    }

    private static void requireTarget(Integer targetCount) {
        if (targetCount == null || targetCount <= 0) {
            throw new ContractException("tier_target_count_required", "冲稳保目标需要有效的最终总数。");
        }
    }

    private static TierAllocationConstraintDTO rangeConstraint(TierQuotaGoalDTO goal, int targetCount) {
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType(TYPE_COUNT_RANGES);
        result.setSourceType(TYPE_COUNT_RANGES);
        result.setSprint(effectiveBound(goal.getSprint(), targetCount));
        result.setStable(effectiveBound(goal.getStable(), targetCount));
        result.setProtect(effectiveBound(goal.getProtect(), targetCount));
        return result;
    }

    private static TierAllocationConstraintDTO exactConstraint(String sourceType, TierCountsDTO counts) {
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType(sourceType);
        result.setSourceType(sourceType);
        result.setSprintCount(counts.getSprintCount());
        result.setStableCount(counts.getStableCount());
        result.setProtectCount(counts.getProtectCount());
        result.setSprint(bound(counts.getSprintCount(), counts.getSprintCount()));
        result.setStable(bound(counts.getStableCount(), counts.getStableCount()));
        result.setProtect(bound(counts.getProtectCount(), counts.getProtectCount()));
        return result;
    }

    private static TierCountRangeDTO effectiveBound(TierCountRangeDTO source, int targetCount) {
        return bound(source == null || source.getMinCount() == null ? 0 : source.getMinCount(),
                source == null || source.getMaxCount() == null ? targetCount : source.getMaxCount());
    }

    private static TierAllocationResolutionDTO resolution(Integer targetCount,
                                                          TierAllocationConstraintDTO constraint,
                                                          TierWeightsDTO canonicalWeights,
                                                          TierCountsDTO resolvedCounts,
                                                          String method) {
        TierAllocationResolutionDTO result = new TierAllocationResolutionDTO();
        result.setTargetCount(targetCount);
        result.setEffectiveBounds(copyConstraint(constraint));
        result.setCanonicalWeights(copyWeights(canonicalWeights));
        result.setResolvedCounts(copyCounts(resolvedCounts));
        result.setResolutionMethod(method);
        result.setTieBreakOrder(new ArrayList<String>(TIER_ORDER));
        return result;
    }

    private static TierWeightsDTO canonicalWeights(TierQuotaGoalDTO source) {
        int divisor = gcd(gcd(source.getSprintWeight(), source.getStableWeight()), source.getProtectWeight());
        TierWeightsDTO result = new TierWeightsDTO();
        result.setSprintWeight(source.getSprintWeight() / divisor);
        result.setStableWeight(source.getStableWeight() / divisor);
        result.setProtectWeight(source.getProtectWeight() / divisor);
        return result;
    }

    private static TierCountsDTO resolveRatio(TierWeightsDTO weights, int targetCount) {
        Map<String, Integer> weightByTier = new LinkedHashMap<String, Integer>();
        weightByTier.put("sprint", weights.getSprintWeight());
        weightByTier.put("stable", weights.getStableWeight());
        weightByTier.put("protect", weights.getProtectWeight());
        long totalWeight = (long) weights.getSprintWeight()
                + weights.getStableWeight() + weights.getProtectWeight();
        Map<String, Integer> countByTier = new LinkedHashMap<String, Integer>();
        Map<String, Long> remainderByTier = new LinkedHashMap<String, Long>();
        int assigned = 0;
        for (String tier : TIER_ORDER) {
            long product = (long) targetCount * weightByTier.get(tier);
            int count = (int) (product / totalWeight);
            countByTier.put(tier, count);
            remainderByTier.put(tier, product % totalWeight);
            assigned += count;
        }
        List<String> remainderOrder = new ArrayList<String>(TIER_ORDER);
        remainderOrder.sort(Comparator
                .comparing((String tier) -> remainderByTier.get(tier)).reversed()
                .thenComparingInt(TIER_ORDER::indexOf));
        for (int index = 0; index < targetCount - assigned; index++) {
            String tier = remainderOrder.get(index);
            countByTier.put(tier, countByTier.get(tier) + 1);
        }
        return counts(countByTier.get("sprint"), countByTier.get("stable"), countByTier.get("protect"));
    }

    private static int gcd(int left, int right) {
        int a = Math.abs(left);
        int b = Math.abs(right);
        while (b != 0) {
            int next = a % b;
            a = b;
            b = next;
        }
        return a == 0 ? 1 : a;
    }

    private static boolean sameCanonicalGoal(TierQuotaGoalDTO left, TierQuotaGoalDTO right) {
        if (left == null || right == null) {
            return left == right;
        }
        return normalized(left.getType()).equals(normalized(right.getType()))
                && equal(left.getSprintCount(), right.getSprintCount())
                && equal(left.getStableCount(), right.getStableCount())
                && equal(left.getProtectCount(), right.getProtectCount())
                && sameBound(left.getSprint(), right.getSprint())
                && sameBound(left.getStable(), right.getStable())
                && sameBound(left.getProtect(), right.getProtect())
                && equal(left.getSprintWeight(), right.getSprintWeight())
                && equal(left.getStableWeight(), right.getStableWeight())
                && equal(left.getProtectWeight(), right.getProtectWeight());
    }

    private static boolean sameResolution(TierAllocationResolutionDTO left,
                                          TierAllocationResolutionDTO right) {
        if (left == null || right == null) {
            return left == right;
        }
        return equal(left.getTargetCount(), right.getTargetCount())
                && sameConstraint(left.getEffectiveBounds(), right.getEffectiveBounds())
                && sameWeights(left.getCanonicalWeights(), right.getCanonicalWeights())
                && (bothRangeResolutions(left, right)
                || sameCounts(left.getResolvedCounts(), right.getResolvedCounts()))
                && normalized(left.getResolutionMethod()).equals(normalized(right.getResolutionMethod()))
                && defaultList(left.getTieBreakOrder()).equals(defaultList(right.getTieBreakOrder()));
    }

    private static boolean samePersistedResolution(TierAllocationResolutionDTO left,
                                                   TierAllocationResolutionDTO right) {
        return sameResolution(left, right)
                && sameCounts(left == null ? null : left.getResolvedCounts(),
                right == null ? null : right.getResolvedCounts())
                && equal(left == null ? null : left.getObjectiveDigest(),
                right == null ? null : right.getObjectiveDigest())
                && equal(left == null ? null : left.getSolverVersion(),
                right == null ? null : right.getSolverVersion());
    }

    private static boolean bothRangeResolutions(TierAllocationResolutionDTO left,
                                                TierAllocationResolutionDTO right) {
        return left.getEffectiveBounds() != null && right.getEffectiveBounds() != null
                && TYPE_COUNT_RANGES.equals(normalized(left.getEffectiveBounds().getSourceType()))
                && TYPE_COUNT_RANGES.equals(normalized(right.getEffectiveBounds().getSourceType()));
    }

    private static boolean sameConstraint(TierAllocationConstraintDTO left,
                                          TierAllocationConstraintDTO right) {
        return left == null || right == null ? left == right
                : normalized(left.getSourceType()).equals(normalized(right.getSourceType()))
                && sameBound(left.getSprint(), right.getSprint())
                && sameBound(left.getStable(), right.getStable())
                && sameBound(left.getProtect(), right.getProtect());
    }

    private static boolean sameWeights(TierWeightsDTO left, TierWeightsDTO right) {
        return left == null || right == null ? left == right
                : equal(left.getSprintWeight(), right.getSprintWeight())
                && equal(left.getStableWeight(), right.getStableWeight())
                && equal(left.getProtectWeight(), right.getProtectWeight());
    }

    private static boolean sameCounts(TierCountsDTO left, TierCountsDTO right) {
        return left == null || right == null ? left == right
                : equal(left.getSprintCount(), right.getSprintCount())
                && equal(left.getStableCount(), right.getStableCount())
                && equal(left.getProtectCount(), right.getProtectCount());
    }

    private static boolean sameBound(TierCountRangeDTO left, TierCountRangeDTO right) {
        return left == null || right == null ? left == right
                : equal(left.getMinCount(), right.getMinCount())
                && equal(left.getMaxCount(), right.getMaxCount());
    }

    private static boolean equal(Object left, Object right) {
        return left == null ? right == null : left.equals(right);
    }

    private static int safe(Integer value) {
        return value == null ? 0 : value;
    }

    static TierQuotaGoalDTO copyGoal(TierQuotaGoalDTO source) {
        if (source == null) {
            return null;
        }
        TierQuotaGoalDTO result = new TierQuotaGoalDTO();
        result.setType(normalized(source.getType()));
        result.setSprintCount(source.getSprintCount());
        result.setStableCount(source.getStableCount());
        result.setProtectCount(source.getProtectCount());
        result.setSprint(copyBound(source.getSprint()));
        result.setStable(copyBound(source.getStable()));
        result.setProtect(copyBound(source.getProtect()));
        result.setSprintWeight(source.getSprintWeight());
        result.setStableWeight(source.getStableWeight());
        result.setProtectWeight(source.getProtectWeight());
        return result;
    }

    static TierQuotaGoalRequestDTO copyRequest(TierQuotaGoalRequestDTO source) {
        if (source == null) {
            return null;
        }
        TierQuotaGoalDTO goal = copyGoal(source);
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        result.setType(goal.getType());
        result.setSprintCount(goal.getSprintCount());
        result.setStableCount(goal.getStableCount());
        result.setProtectCount(goal.getProtectCount());
        result.setSprint(goal.getSprint());
        result.setStable(goal.getStable());
        result.setProtect(goal.getProtect());
        result.setSprintWeight(goal.getSprintWeight());
        result.setStableWeight(goal.getStableWeight());
        result.setProtectWeight(goal.getProtectWeight());
        result.setUpdateMode(source.getUpdateMode());
        return result;
    }

    static TierAllocationResolutionDTO copyResolution(TierAllocationResolutionDTO source) {
        if (source == null) {
            return null;
        }
        TierAllocationResolutionDTO result = new TierAllocationResolutionDTO();
        result.setTargetCount(source.getTargetCount());
        result.setEffectiveBounds(copyConstraint(source.getEffectiveBounds()));
        result.setCanonicalWeights(copyWeights(source.getCanonicalWeights()));
        result.setResolvedCounts(copyCounts(source.getResolvedCounts()));
        result.setResolutionMethod(source.getResolutionMethod());
        result.setTieBreakOrder(new ArrayList<String>(defaultList(source.getTieBreakOrder())));
        result.setObjectiveDigest(source.getObjectiveDigest());
        result.setSolverVersion(source.getSolverVersion());
        return result;
    }

    private static TierAllocationConstraintDTO copyConstraint(TierAllocationConstraintDTO source) {
        if (source == null) {
            return null;
        }
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType(source.getType());
        result.setSourceType(source.getSourceType());
        result.setSprintCount(source.getSprintCount());
        result.setStableCount(source.getStableCount());
        result.setProtectCount(source.getProtectCount());
        result.setSprint(copyBound(source.getSprint()));
        result.setStable(copyBound(source.getStable()));
        result.setProtect(copyBound(source.getProtect()));
        result.setSprintWeight(source.getSprintWeight());
        result.setStableWeight(source.getStableWeight());
        result.setProtectWeight(source.getProtectWeight());
        return result;
    }

    private static TierCountRangeDTO copyBound(TierCountRangeDTO source) {
        return source == null ? null : bound(source.getMinCount(), source.getMaxCount());
    }

    static TierCountsDTO copyCounts(TierCountsDTO source) {
        return source == null ? null
                : counts(source.getSprintCount(), source.getStableCount(), source.getProtectCount());
    }

    private static TierWeightsDTO copyWeights(TierWeightsDTO source) {
        if (source == null) {
            return null;
        }
        TierWeightsDTO result = new TierWeightsDTO();
        result.setSprintWeight(source.getSprintWeight());
        result.setStableWeight(source.getStableWeight());
        result.setProtectWeight(source.getProtectWeight());
        return result;
    }

    private static TierCountRangeDTO bound(Integer min, Integer max) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        result.setMinCount(min);
        result.setMaxCount(max);
        return result;
    }

    private static TierCountsDTO counts(Integer sprint, Integer stable, Integer protect) {
        TierCountsDTO result = new TierCountsDTO();
        result.setSprintCount(sprint);
        result.setStableCount(stable);
        result.setProtectCount(protect);
        return result;
    }

    private static HardPlanningObjectivesDTO objectives(PlanningStateDTO state) {
        return state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
    }

    private static HardPlanningObjectivesDTO ensureObjectives(PlanningStateDTO state) {
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives() == null) {
            state.getConstraintState().setHardPlanningObjectives(new HardPlanningObjectivesDTO());
        }
        return state.getConstraintState().getHardPlanningObjectives();
    }

    private static List<String> defaultList(List<String> values) {
        return values == null ? new ArrayList<String>() : values;
    }

    private static String normalized(String value) {
        return Strings.nullToEmpty(value).trim().toLowerCase(Locale.ROOT);
    }

    @Data
    static final class CompiledTierAllocation {
        private TierQuotaGoalRequestDTO requestedGoal;
        private TierQuotaGoalDTO effectiveSourceGoal;
        private TierQuotaGoalDTO canonicalGoal;
        private TierAllocationConstraintDTO constraint;
        private TierAllocationResolutionDTO resolution;
        private boolean stateChanged;
    }

    static final class ContractException extends IllegalArgumentException {
        private final String reasonCode;

        ContractException(String reasonCode, String message) {
            super(message);
            this.reasonCode = reasonCode;
        }

        String getReasonCode() {
            return reasonCode;
        }
    }

    private static final class SourceCompilation {
        private TierQuotaGoalDTO canonicalGoal;
        private TierAllocationConstraintDTO constraint;
        private TierAllocationResolutionDTO resolution;
    }
}
