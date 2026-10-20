package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;

import java.util.List;

/**
 * 组内专业计划入口：两阶段开关 on 时走组内小 MILP，否则走既有确定性启发式。
 */
final class GroupInnerMajorPlanner {

    private GroupInnerMajorPlanner() {
    }

    static List<CandidateItemDTO> plan(List<CandidateItemDTO> candidates,
                                       Integer requiredMajorCount,
                                       Double unitEnrollRatio) {
        if (!GroupInnerMajorCapFlags.enabled()) {
            return candidates == null ? java.util.Collections.<CandidateItemDTO>emptyList() : candidates;
        }
        return GroupInnerMajorOptimizationFlags.enabled()
                ? planOptimized(candidates, requiredMajorCount, unitEnrollRatio)
                : GroupInnerMajorSelector.select(candidates, requiredMajorCount, unitEnrollRatio);
    }

    /**
     * 显式走组内 MILP；shadow 需要用它计算真实的新口径结果做对比，
     * 但又不能把结果写回生产路径。
     */
    static List<CandidateItemDTO> planOptimized(List<CandidateItemDTO> candidates,
                                                Integer requiredMajorCount,
                                                Double unitEnrollRatio) {
        if (!GroupInnerMajorCapFlags.enabled()) {
            return candidates == null ? java.util.Collections.<CandidateItemDTO>emptyList() : candidates;
        }
        return UnitMajorSelector.select(candidates, requiredMajorCount, unitEnrollRatio);
    }
}
