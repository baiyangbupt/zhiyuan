package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;

import java.util.List;

final class TierQuotaObjectiveEnforcer {

    private TierQuotaObjectiveEnforcer() {
    }

    static boolean hasConfirmedGoal(PlanningStateDTO state) {
        return TierQuotaSupport.confirmedGoal(state) != null;
    }

    static void enforce(PlanningStateDTO state, List<CandidateItemDTO> effectiveCandidates) {
        TierQuotaGoalDTO quota = TierQuotaSupport.confirmedGoal(state);
        if (quota == null) {
            return;
        }
        int targetCount = TierQuotaSupport.total(quota);
        String validationError = TierQuotaSupport.validate(quota, targetCount);
        if (validationError != null) {
            throw new IllegalStateException(validationError);
        }
        List<CoverageRequirementDTO> combined = Lists.newArrayList(
                CoverageRequirementSupport.confirmedRequirements(state));
        combined.addAll(TierQuotaSupport.syntheticObjectives(quota));
        CoverageObjectiveEnforcer.enforce(
                state, effectiveCandidates, combined, targetCount, "方案覆盖要求和冲稳保精确配额");
        List<CoverageRequirementDTO> quotaObjectives = TierQuotaSupport.syntheticObjectives(quota);
        int[] actualCounts = CoverageObjectiveEnforcer.currentCounts(
                state, effectiveCandidates, quotaObjectives);
        if (actualCounts.length != 3
                || actualCounts[0] != quota.getSprintCount()
                || actualCounts[1] != quota.getStableCount()
                || actualCounts[2] != quota.getProtectCount()) {
            throw new BusinessException(409, "当前有效候选无法形成互斥且精确的冲稳保配额");
        }
    }
}
