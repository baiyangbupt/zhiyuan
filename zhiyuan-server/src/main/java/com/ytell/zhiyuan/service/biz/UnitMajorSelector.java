package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import org.ojalgo.optimisation.Expression;
import org.ojalgo.optimisation.ExpressionsBasedModel;
import org.ojalgo.optimisation.Optimisation;
import org.ojalgo.optimisation.Variable;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 两阶段组内选择阶段 2：单个专业组的小型 MILP。
 *
 * <p>约束：组内专业不足 requiredMajorCount 时全选；否则恰好选 c 个；
 * 有 safety major 时至少 1 个；preferred 优先（独立阶段），再最大化组内
 * 效用并用原始顺序做确定性平局。模型很小；不可证明最优时回退既有
 * GroupInnerMajorSelector，保证可用性。</p>
 */
final class UnitMajorSelector {

    private static final long TIME_BUDGET_MS = 200L;

    private UnitMajorSelector() {
    }

    static List<CandidateItemDTO> select(List<CandidateItemDTO> unitCandidates,
                                         Integer requiredMajorCount,
                                         Double unitEnrollRatio) {
        List<CandidateItemDTO> candidates = unitCandidates == null
                ? new ArrayList<CandidateItemDTO>() : unitCandidates;
        if (candidates.isEmpty() || requiredMajorCount == null
                || requiredMajorCount <= 0 || candidates.size() <= requiredMajorCount) {
            return candidates;
        }
        try {
            List<CandidateItemDTO> solved = solve(candidates, requiredMajorCount, unitEnrollRatio);
            return solved == null || solved.isEmpty()
                    ? GroupInnerMajorSelector.select(candidates, requiredMajorCount, unitEnrollRatio)
                    : solved;
        } catch (RuntimeException unavailable) {
            return GroupInnerMajorSelector.select(candidates, requiredMajorCount, unitEnrollRatio);
        }
    }

    private static List<CandidateItemDTO> solve(List<CandidateItemDTO> candidates,
                                                int requiredMajorCount,
                                                Double unitEnrollRatio) {
        ExpressionsBasedModel model = new ExpressionsBasedModel();
        List<Variable> variables = new ArrayList<Variable>();
        long deadline = System.nanoTime() + TIME_BUDGET_MS * 1_000_000L;
        Expression count = model.addExpression("major_count").level(requiredMajorCount);
        Expression safety = null;
        for (int index = 0; index < candidates.size(); index++) {
            CandidateItemDTO candidate = candidates.get(index);
            Variable variable = Variable.makeBinary("major_" + index);
            variable.weight(BigDecimal.ZERO);
            model.addVariable(variable);
            variables.add(variable);
            count.set(variable, 1);
            if (isSafetyMajor(candidate, unitEnrollRatio)) {
                if (safety == null) {
                    safety = model.addExpression("safety_major").lower(1);
                }
                safety.set(variable, 1);
            }
        }

        Expression preferredObjective = null;
        int preferredCount = 0;
        for (int index = 0; index < candidates.size(); index++) {
            if (Boolean.TRUE.equals(candidates.get(index).getPreferred())) {
                preferredCount++;
            }
        }
        if (preferredCount > 0) {
            preferredObjective = model.addExpression("preferred_objective").weight(-1);
            for (int index = 0; index < candidates.size(); index++) {
                if (Boolean.TRUE.equals(candidates.get(index).getPreferred())) {
                    preferredObjective.set(variables.get(index), 1);
                }
            }
            Optimisation.Result preferredSolved = solvePhase(model, deadline);
            if (preferredSolved == null || !preferredSolved.getState().isOptimal()) {
                return null;
            }
            int selectedPreferred = 0;
            for (int index = 0; index < candidates.size(); index++) {
                if (Boolean.TRUE.equals(candidates.get(index).getPreferred())
                        && preferredSolved.doubleValue(index) > 0.5D) {
                    selectedPreferred++;
                }
            }
            preferredObjective.weight(0);
            Expression fixPreferred = model.addExpression("fix_preferred").lower(selectedPreferred);
            for (int index = 0; index < candidates.size(); index++) {
                if (Boolean.TRUE.equals(candidates.get(index).getPreferred())) {
                    fixPreferred.set(variables.get(index), 1);
                }
            }
        }

        long maxIndexSum = (long) candidates.size() * (candidates.size() - 1) / 2L;
        long utilityWeight = maxIndexSum + 1L;
        Expression utilityObjective = model.addExpression("major_utility")
                .weight(BigDecimal.valueOf(-utilityWeight));
        Expression stableObjective = model.addExpression("major_stable").weight(1);
        for (int index = 0; index < candidates.size(); index++) {
            utilityObjective.set(variables.get(index), BigDecimal.valueOf(utility(candidates.get(index))));
            stableObjective.set(variables.get(index), BigDecimal.valueOf(index));
        }
        Optimisation.Result solved = solvePhase(model, deadline);
        if (solved == null || !solved.getState().isOptimal()) {
            return null;
        }
        Set<Integer> selected = new LinkedHashSet<Integer>();
        for (int index = 0; index < candidates.size(); index++) {
            if (solved.doubleValue(index) > 0.5D) {
                selected.add(index);
            }
        }
        List<CandidateItemDTO> result = new ArrayList<CandidateItemDTO>();
        for (int index = 0; index < candidates.size(); index++) {
            if (selected.contains(index)) {
                result.add(candidates.get(index));
            }
        }
        return result;
    }

    private static Optimisation.Result solvePhase(ExpressionsBasedModel model, long deadline) {
        long remaining = (deadline - System.nanoTime()) / 1_000_000L;
        if (remaining <= 0) {
            return null;
        }
        model.options.time_abort = remaining;
        model.options.time_suffice = remaining;
        model.options.iterations_abort = 50_000;
        model.options.iterations_suffice = 50_000;
        model.options.mip_gap = 0D;
        return model.minimise();
    }

    private static boolean isSafetyMajor(CandidateItemDTO candidate, Double unitEnrollRatio) {
        return candidate != null && candidate.getAdmissionRatio() != null
                && unitEnrollRatio != null && candidate.getAdmissionRatio() >= unitEnrollRatio;
    }

    /**
     * 与全局 solver 同权重的组内效用（×100 定点，避免整数舍入把不同
     * 录取率的专业压成同分而被稳定序覆盖）。
     */
    private static int utility(CandidateItemDTO candidate) {
        if (candidate == null) {
            return 0;
        }
        int intent = clamp(candidate.getIntentScore());
        int quality = clamp(candidate.getFinalScore());
        int safety = clamp(candidate.getAdmissionRatio());
        int future = clamp(candidate.getFutureDevelopmentScore());
        int cost = candidate.getTuitionPerYear() == null ? 0
                : Math.max(0, 100 - Math.round(Math.min(100_000, candidate.getTuitionPerYear())
                * 100.0F / 100_000));
        return intent * 40 + quality * 25 + safety * 20 + future * 10 + cost * 5;
    }

    private static int clamp(Double value) {
        if (value == null || value.isNaN() || value.isInfinite()) {
            return 0;
        }
        return (int) Math.max(0, Math.min(100, Math.round(value)));
    }
}
