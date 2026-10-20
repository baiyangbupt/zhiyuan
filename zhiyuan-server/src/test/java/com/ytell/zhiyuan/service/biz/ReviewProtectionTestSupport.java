package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

import java.util.function.Consumer;

final class ReviewProtectionTestSupport {
    enum Carrier {
        WORKING_ITEM_LOCK(state -> state.getWorkingPlanState().getItems().get(0).setLocked(true)),
        ORDERED_ITEM_LOCK(state -> state.getOrderedPlanState().getItems().get(0).setLocked(true)),
        ORDERED_ITEM_PIN(state -> state.getOrderedPlanState().getItems().get(0).setPinned(true)),
        ORDERED_ITEM_PIN_POSITION(state -> state.getOrderedPlanState().getItems().get(0).setPinnedPosition(1)),
        WORKING_UNIT_LOCK(state -> state.getWorkingPlanState().getUnits().get(0).setLocked(true)),
        ORDERED_UNIT_LOCK(state -> state.getOrderedPlanState().getUnits().get(0).setLocked(true)),
        ORDERED_UNIT_PIN(state -> state.getOrderedPlanState().getUnits().get(0).setPinned(true)),
        ORDERED_UNIT_PIN_POSITION(state -> state.getOrderedPlanState().getUnits().get(0).setPinnedPosition(1));

        private final Consumer<PlanningStateDTO> protection;

        Carrier(Consumer<PlanningStateDTO> protection) {
            this.protection = protection;
        }

        void protect(PlanningStateDTO state) {
            protection.accept(state);
        }
    }

    private ReviewProtectionTestSupport() {
    }
}
