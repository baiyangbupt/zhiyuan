package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;

import java.util.ArrayList;
import java.util.List;

/**
 * 专项资格的动作层判据：只处理用户明确“没有任何专项”的场景。
 *
 * <p>unknown 不在这里判冲突；它保留可探索，但不能被当成“资格已通过”。
 * 纯删除不调用本类的后置，否则会把“分次清掉冲突项”误伤成失败。</p>
 */
final class SpecialPlanQualification {

    private SpecialPlanQualification() {
    }

    static boolean isConflict(CandidateItemDTO candidate, Boolean specialPlan) {
        if (!Boolean.FALSE.equals(specialPlan) || candidate == null) {
            return false;
        }
        SpecialPlanRequirementSupport.Requirement requirement =
                SpecialPlanRequirementSupport.requirement(candidate);
        return requirement.anyExplicit() || requirement.evidenceConflict();
    }

    /** 用户没回答专项资格时，带明确专项要求的计划不能进入新选入集合。 */
    static boolean isUnknownRequirement(CandidateItemDTO candidate, Boolean specialPlan) {
        if (specialPlan != null || candidate == null) {
            return false;
        }
        SpecialPlanRequirementSupport.Requirement requirement =
                SpecialPlanRequirementSupport.requirement(candidate);
        return requirement.anyExplicit() || requirement.evidenceConflict();
    }

    static boolean isConflict(PlanningUnitDTO unit, Boolean specialPlan) {
        if (!Boolean.FALSE.equals(specialPlan) || unit == null) {
            return false;
        }
        SpecialPlanRequirementSupport.Requirement requirement =
                SpecialPlanRequirementSupport.requirement(unit);
        return requirement.anyExplicit() || requirement.evidenceConflict();
    }

    static List<CandidateItemDTO> filterKnownConflicts(List<CandidateItemDTO> candidates,
                                                       Boolean specialPlan) {
        if (!Boolean.FALSE.equals(specialPlan) || candidates == null) {
            return candidates;
        }
        List<CandidateItemDTO> result = new ArrayList<CandidateItemDTO>();
        for (CandidateItemDTO candidate : candidates) {
            if (!isConflict(candidate, specialPlan)) {
                result.add(candidate);
            }
        }
        return result;
    }

    static boolean hasConflictInCandidates(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        if (!Boolean.FALSE.equals(specialPlanOf(state))) {
            return false;
        }
        for (CandidateItemDTO candidate : candidates == null
                ? new ArrayList<CandidateItemDTO>() : candidates) {
            if (isConflict(candidate, Boolean.FALSE)) {
                return true;
            }
        }
        return false;
    }

    /** 新选入/正式方案不得含“资格未知的专项计划”；纯删除不调用。 */
    static boolean stateHasUnknownSpecialPlan(PlanningStateDTO state) {
        Boolean specialPlan = specialPlanOf(state);
        if (specialPlan != null || state == null) {
            return false;
        }
        if (state.getOrderedPlanState() != null) {
            for (OrderedUnitDTO unit : state.getOrderedPlanState().getUnits() == null
                    ? new ArrayList<OrderedUnitDTO>() : state.getOrderedPlanState().getUnits()) {
                if (unit == null) {
                    continue;
                }
                PlanningUnitDTO asUnit = new PlanningUnitDTO();
                asUnit.setSchoolName(unit.getSchoolName());
                asUnit.setSelectedMajors(defaultList(unit.getMajorItems()));
                if (SpecialPlanRequirementSupport.requirement(asUnit).anyExplicit()) {
                    return true;
                }
            }
            for (OrderedItemDTO item : state.getOrderedPlanState().getItems() == null
                    ? new ArrayList<OrderedItemDTO>() : state.getOrderedPlanState().getItems()) {
                if (item == null) {
                    continue;
                }
                CandidateItemDTO candidate = candidateById(state, item.getVolunteerId());
                if (candidate == null) {
                    candidate = new CandidateItemDTO();
                    candidate.setVolunteerId(item.getVolunteerId());
                    candidate.setSchoolName(item.getSchoolName());
                    candidate.setMajorName(item.getMajorName());
                }
                if (isUnknownRequirement(candidate, null)) {
                    return true;
                }
            }
        }
        if (state.getWorkingPlanState() != null) {
            for (DraftItemDTO item : defaultList(state.getWorkingPlanState().getItems())) {
                if (item == null) {
                    continue;
                }
                CandidateItemDTO candidate = candidateById(state, item.getVolunteerId());
                if (candidate == null) {
                    candidate = new CandidateItemDTO();
                    candidate.setVolunteerId(item.getVolunteerId());
                    candidate.setSchoolName(item.getSchoolName());
                    candidate.setMajorName(item.getMajorName());
                }
                if (isUnknownRequirement(candidate, null)) {
                    return true;
                }
            }
        }
        return false;
    }

    private static <T> List<T> defaultList(List<T> value) {
        return value == null ? new ArrayList<T>() : value;
    }

    /**
     * 看正式方案（ordered），没有正式方案时看工作草案。用于写出动作的最终门槛；
     * 纯 remove 不得调用。
     */
    static boolean stateHasConflict(PlanningStateDTO state) {
        Boolean specialPlan = specialPlanOf(state);
        if (!Boolean.FALSE.equals(specialPlan) || state == null) {
            return false;
        }
        OrderedPlanStateSlice ordered = orderedSlice(state);
        if (ordered.present) {
            return ordered.hasConflict(specialPlan);
        }
        if (state.getWorkingPlanState() == null
                || state.getWorkingPlanState().getItems() == null) {
            return false;
        }
        for (DraftItemDTO item : state.getWorkingPlanState().getItems()) {
            if (item == null) {
                continue;
            }
            CandidateItemDTO candidate = candidateById(state, item.getVolunteerId());
            if (candidate == null) {
                candidate = new CandidateItemDTO();
                candidate.setVolunteerId(item.getVolunteerId());
                candidate.setSchoolName(item.getSchoolName());
                candidate.setMajorName(item.getMajorName());
            }
            if (isConflict(candidate, specialPlan)) {
                return true;
            }
        }
        return false;
    }

    static boolean blocksNewSelection(PlanningStateDTO state) {
        return stateHasConflict(state) || stateHasUnknownSpecialPlan(state);
    }

    static Boolean specialPlanOf(PlanningStateDTO state) {
        return state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getSpecialPlan();
    }

    private static OrderedPlanStateSlice orderedSlice(PlanningStateDTO state) {
        if (state.getOrderedPlanState() == null) {
            return new OrderedPlanStateSlice(false, null, null, state);
        }
        return new OrderedPlanStateSlice(
                (state.getOrderedPlanState().getUnits() != null
                        && !state.getOrderedPlanState().getUnits().isEmpty())
                        || (state.getOrderedPlanState().getItems() != null
                        && !state.getOrderedPlanState().getItems().isEmpty()),
                state.getOrderedPlanState().getUnits(),
                state.getOrderedPlanState().getItems(), state);
    }

    private static final class OrderedPlanStateSlice {
        private final boolean present;
        private final List<OrderedUnitDTO> units;
        private final List<OrderedItemDTO> items;
        private final PlanningStateDTO state;

        private OrderedPlanStateSlice(boolean present, List<OrderedUnitDTO> units,
                                      List<OrderedItemDTO> items, PlanningStateDTO state) {
            this.present = present;
            this.units = units;
            this.items = items;
            this.state = state;
        }

        private boolean hasConflict(Boolean specialPlan) {
            for (OrderedUnitDTO unit : units == null ? new ArrayList<OrderedUnitDTO>() : units) {
                if (unit == null) {
                    continue;
                }
                PlanningUnitDTO asUnit = new PlanningUnitDTO();
                asUnit.setSchoolName(unit.getSchoolName());
                List<PlanningUnitMajorDTO> majors = unit.getMajorItems() == null
                        ? new ArrayList<PlanningUnitMajorDTO>() : unit.getMajorItems();
                asUnit.setSelectedMajors(majors);
                if (isConflict(asUnit, specialPlan)) {
                    return true;
                }
            }
            for (OrderedItemDTO item : items == null ? new ArrayList<OrderedItemDTO>() : items) {
                if (item == null) {
                    continue;
                }
                CandidateItemDTO candidate = candidateById(state, item.getVolunteerId());
                if (candidate == null) {
                    candidate = new CandidateItemDTO();
                    candidate.setVolunteerId(item.getVolunteerId());
                    candidate.setSchoolName(item.getSchoolName());
                    candidate.setMajorName(item.getMajorName());
                }
                if (isConflict(candidate, specialPlan)) {
                    return true;
                }
            }
            return false;
        }
    }

    private static CandidateItemDTO candidateById(PlanningStateDTO state, String volunteerId) {
        if (state == null || state.getCandidatePoolState() == null
                || state.getCandidatePoolState().getItems() == null
                || Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        for (CandidateItemDTO candidate : state.getCandidatePoolState().getItems()) {
            if (candidate != null && volunteerId.equals(candidate.getVolunteerId())) {
                return candidate;
            }
        }
        return null;
    }
}
