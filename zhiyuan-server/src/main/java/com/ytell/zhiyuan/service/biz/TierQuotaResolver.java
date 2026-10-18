package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;

import java.util.List;

/**
 * J5.4 S2：显式冲稳保配额（tierQuotaGoal）是档位判据的第一真源。
 *
 * <p>存在显式配额时，review 不再用 20/40% 软带判 fail，而是直接比较
 * 实际档位数量与 effectiveBounds（精确配额 min=max）。没有显式配额时
 * 返回 null，调用方保留既有 requiredTierCounts 缩放 + 软带逻辑。</p>
 */
final class TierQuotaResolver {

    private TierQuotaResolver() {
    }

    /**
     * 显式配额的单点锚（仅 exact/ratios 有 resolvedCounts；范围配额没有
     * 单点最优，返回 null，让 solver 继续用 constraint 投影）。
     */
    static com.ytell.zhiyuan.model.dto.planning.TierCountsDTO explicitAnchor(PlanningStateDTO state) {
        if (state == null || TierAllocationSupport.confirmedGoal(state) == null) {
            return null;
        }
        Integer target = resolveTarget(state);
        if (target == null || target <= 0) {
            return null;
        }
        try {
            TierAllocationSupport.CompiledTierAllocation compiled =
                    TierAllocationSupport.compileConfirmed(state, target);
            return compiled.getResolution() == null
                    ? null : TierAllocationSupport.copyCounts(
                    compiled.getResolution().getResolvedCounts());
        } catch (RuntimeException ex) {
            return null;
        }
    }

    static ExplicitCheck evaluateExplicit(PlanningStateDTO state) {
        if (state == null || TierAllocationSupport.confirmedGoal(state) == null) {
            return null;
        }
        Integer target = resolveTarget(state);
        if (target == null || target <= 0) {
            return null;
        }
        TierAllocationConstraintDTO constraint;
        try {
            constraint = TierAllocationSupport.compileConfirmed(state, target).getConstraint();
        } catch (RuntimeException ex) {
            // 配额本身不合法时不在 review 里抛；交给上层既有逻辑/预览报错。
            return null;
        }
        if (constraint == null) {
            return null;
        }
        int sprint = countTier(state, "sprint");
        int stable = countTier(state, "stable");
        int protect = countTier(state, "protect");
        boolean sprintOk = within(constraint.getSprint(), sprint);
        boolean stableOk = within(constraint.getStable(), stable);
        boolean protectOk = within(constraint.getProtect(), protect);
        String detail = "冲" + sprint + label(constraint.getSprint())
                + "；稳" + stable + label(constraint.getStable())
                + "；保" + protect + label(constraint.getProtect());
        if (sprintOk && stableOk && protectOk) {
            return new ExplicitCheck(true, null, "info", detail);
        }
        String reason;
        String level;
        if (below(constraint.getProtect(), protect)) {
            reason = "protect_tier_missing";
            level = "risk";
        } else if (above(constraint.getSprint(), sprint)) {
            reason = "sprint_tier_over_limit";
            level = "risk";
        } else if (below(constraint.getSprint(), sprint)) {
            reason = "sprint_tier_missing";
            level = "warn";
        } else {
            reason = "tier_quota_mismatch";
            level = "warn";
        }
        return new ExplicitCheck(false, reason, level, detail);
    }

    static String summary(String reasonCode) {
        if ("protect_tier_missing".equals(reasonCode)) {
            return "保区数量低于已确认配额";
        }
        if ("sprint_tier_over_limit".equals(reasonCode)) {
            return "冲区数量超出已确认配额";
        }
        if ("sprint_tier_missing".equals(reasonCode)) {
            return "冲区数量低于已确认配额";
        }
        return "冲稳保数量与已确认配额不一致";
    }

    private static Integer resolveTarget(PlanningStateDTO state) {
        Integer confirmed = state.getConstraintState() == null
                || state.getConstraintState().getHardPlanningObjectives() == null
                ? null : state.getConstraintState().getHardPlanningObjectives()
                .getSelectionTargetCount();
        if (confirmed != null && confirmed > 0) {
            return confirmed;
        }
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        return pool == null ? null : pool.getRequiredCount();
    }

    private static int countTier(PlanningStateDTO state, String tier) {
        boolean unitMode = state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        if (unitMode) {
            int count = 0;
            for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState() == null
                    ? null : state.getOrderedPlanState().getUnits())) {
                if (unit != null && tier.equals(TierAllocationSupport.canonicalTierKey(unit.getTier()))) {
                    count++;
                }
            }
            return count;
        }
        int count = 0;
        for (OrderedItemDTO item : defaultList(state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems())) {
            if (item != null && tier.equals(TierAllocationSupport.canonicalTierKey(item.getTier()))) {
                count++;
            }
        }
        return count;
    }

    private static boolean within(TierCountRangeDTO bound, int actual) {
        if (bound == null) {
            return true;
        }
        return (bound.getMinCount() == null || actual >= bound.getMinCount())
                && (bound.getMaxCount() == null || actual <= bound.getMaxCount());
    }

    private static boolean below(TierCountRangeDTO bound, int actual) {
        return bound != null && bound.getMinCount() != null && actual < bound.getMinCount();
    }

    private static boolean above(TierCountRangeDTO bound, int actual) {
        return bound != null && bound.getMaxCount() != null && actual > bound.getMaxCount();
    }

    private static String label(TierCountRangeDTO bound) {
        if (bound == null) {
            return "(无配额)";
        }
        Integer min = bound.getMinCount();
        Integer max = bound.getMaxCount();
        if (min != null && max != null && min.equals(max)) {
            return "(配额" + min + ")";
        }
        return "(配额" + (min == null ? "-" : min) + ".." + (max == null ? "-" : max) + ")";
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? java.util.Collections.<T>emptyList() : values;
    }

    static final class ExplicitCheck {
        private final boolean passed;
        private final String reasonCode;
        private final String level;
        private final String detail;

        ExplicitCheck(boolean passed, String reasonCode, String level, String detail) {
            this.passed = passed;
            this.reasonCode = reasonCode;
            this.level = level;
            this.detail = detail;
        }

        boolean isPassed() {
            return passed;
        }

        String getReasonCode() {
            return reasonCode;
        }

        String getLevel() {
            return level;
        }

        String getDetail() {
            return detail;
        }
    }
}
