package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

import java.util.List;
import java.util.Locale;

final class TierQuotaSupport {

    static final String TYPE_EXACT_COUNTS = "exact_counts";

    private TierQuotaSupport() {
    }

    static String validate(TierQuotaGoalDTO goal, Integer targetCount) {
        if (goal == null) {
            return null;
        }
        if (!TYPE_EXACT_COUNTS.equals(normalized(goal.getType()))) {
            return "冲稳保精确配额只支持 exact_counts 类型。";
        }
        if (goal.getSprintCount() == null || goal.getStableCount() == null
                || goal.getProtectCount() == null) {
            return "冲稳保精确配额必须同时给出冲、稳、保三个数量。";
        }
        if (goal.getSprintCount() < 0 || goal.getStableCount() < 0 || goal.getProtectCount() < 0) {
            return "冲稳保精确配额必须是非负整数。";
        }
        if (targetCount == null || targetCount <= 0) {
            return "冲稳保精确配额需要明确且有效的方案总数。";
        }
        if (total(goal) != targetCount) {
            return "冲稳保精确配额合计必须等于方案目标总数 " + targetCount + "。";
        }
        return null;
    }

    static int total(TierQuotaGoalDTO goal) {
        if (goal == null) {
            return 0;
        }
        return safe(goal.getSprintCount()) + safe(goal.getStableCount()) + safe(goal.getProtectCount());
    }

    static String summarize(TierQuotaGoalDTO goal) {
        return goal == null ? "" : "冲" + safe(goal.getSprintCount()) + "个、稳"
                + safe(goal.getStableCount()) + "个、保" + safe(goal.getProtectCount()) + "个";
    }

    static List<UserGoalFixProposalReq.RequirementDTO> syntheticRequirements(TierQuotaGoalDTO goal) {
        List<UserGoalFixProposalReq.RequirementDTO> result = Lists.newArrayList();
        if (goal == null) {
            return result;
        }
        result.add(requirement("冲", safe(goal.getSprintCount())));
        result.add(requirement("稳", safe(goal.getStableCount())));
        result.add(requirement("保", safe(goal.getProtectCount())));
        return result;
    }

    static List<CoverageRequirementDTO> syntheticObjectives(TierQuotaGoalDTO goal) {
        List<CoverageRequirementDTO> result = Lists.newArrayList();
        if (goal == null) {
            return result;
        }
        result.add(objective("冲", safe(goal.getSprintCount())));
        result.add(objective("稳", safe(goal.getStableCount())));
        result.add(objective("保", safe(goal.getProtectCount())));
        return result;
    }

    static void persist(PlanningStateDTO state, TierQuotaGoalDTO goal) {
        if (state == null || goal == null) {
            return;
        }
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives() == null) {
            state.getConstraintState().setHardPlanningObjectives(new HardPlanningObjectivesDTO());
        }
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(copy(goal));
    }

    static TierQuotaGoalDTO confirmedGoal(PlanningStateDTO state) {
        HardPlanningObjectivesDTO objectives = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        return objectives == null ? null : objectives.getTierQuotaGoal();
    }

    static boolean isPersisted(PlanningStateDTO state, TierQuotaGoalDTO expected) {
        return same(confirmedGoal(state), expected);
    }

    private static UserGoalFixProposalReq.RequirementDTO requirement(String tier, int count) {
        UserGoalFixProposalReq.RequirementDTO result = new UserGoalFixProposalReq.RequirementDTO();
        result.setKind(ProjectedHardRequirementSupport.KIND_INCLUDE);
        result.setDomain("admission");
        result.setKey("tier");
        result.setValues(Lists.newArrayList(tier));
        result.setMinCount(count);
        return result;
    }

    private static CoverageRequirementDTO objective(String tier, int count) {
        CoverageRequirementDTO result = new CoverageRequirementDTO();
        result.setDomain("admission");
        result.setKey("tier");
        result.setValues(Lists.newArrayList(tier));
        result.setMinCount(count);
        return result;
    }

    private static TierQuotaGoalDTO copy(TierQuotaGoalDTO source) {
        TierQuotaGoalDTO result = new TierQuotaGoalDTO();
        result.setType(TYPE_EXACT_COUNTS);
        result.setSprintCount(source.getSprintCount());
        result.setStableCount(source.getStableCount());
        result.setProtectCount(source.getProtectCount());
        return result;
    }

    private static boolean same(TierQuotaGoalDTO left, TierQuotaGoalDTO right) {
        return left != null && right != null
                && TYPE_EXACT_COUNTS.equals(normalized(left.getType()))
                && TYPE_EXACT_COUNTS.equals(normalized(right.getType()))
                && safe(left.getSprintCount()) == safe(right.getSprintCount())
                && safe(left.getStableCount()) == safe(right.getStableCount())
                && safe(left.getProtectCount()) == safe(right.getProtectCount());
    }

    private static int safe(Integer value) {
        return value == null ? 0 : value;
    }

    private static String normalized(String value) {
        return Strings.nullToEmpty(value).trim().toLowerCase(Locale.ROOT);
    }
}
