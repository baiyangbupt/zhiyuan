package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

final class ReviewProtectionSupport {
    private ReviewProtectionSupport() {
    }

    static boolean hasProtection(PlanningStateDTO state) {
        if (state == null) {
            return false;
        }
        if (state.getWorkingPlanState() != null) {
            if (state.getWorkingPlanState().getItems() != null) {
                for (DraftItemDTO item : state.getWorkingPlanState().getItems()) {
                    if (item != null && Boolean.TRUE.equals(item.getLocked())) {
                        return true;
                    }
                }
            }
            if (state.getWorkingPlanState().getUnits() != null) {
                for (DraftUnitDTO unit : state.getWorkingPlanState().getUnits()) {
                    if (unit != null && Boolean.TRUE.equals(unit.getLocked())) {
                        return true;
                    }
                }
            }
        }
        if (state.getOrderedPlanState() != null) {
            if (state.getOrderedPlanState().getItems() != null) {
                for (OrderedItemDTO item : state.getOrderedPlanState().getItems()) {
                    if (item != null && (Boolean.TRUE.equals(item.getLocked())
                            || Boolean.TRUE.equals(item.getPinned()) || item.getPinnedPosition() != null)) {
                        return true;
                    }
                }
            }
            if (state.getOrderedPlanState().getUnits() != null) {
                for (OrderedUnitDTO unit : state.getOrderedPlanState().getUnits()) {
                    if (unit != null && (Boolean.TRUE.equals(unit.getLocked())
                            || Boolean.TRUE.equals(unit.getPinned()) || unit.getPinnedPosition() != null)) {
                        return true;
                    }
                }
            }
        }
        return false;
    }
}
