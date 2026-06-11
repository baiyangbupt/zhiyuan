package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;

import java.util.ArrayList;
import java.util.List;

final class OrderedPlanPositioningSupport {

    private OrderedPlanPositioningSupport() {
    }

    static List<OrderedItemDTO> rebuildItems(List<OrderedItemDTO> items) {
        List<OrderedItemDTO> ordered = items == null ? new ArrayList<OrderedItemDTO>() : new ArrayList<OrderedItemDTO>(items);
        for (int i = 0; i < ordered.size(); i++) {
            ordered.get(i).setPosition(i + 1);
        }
        return ordered;
    }

    static int resolveMovableTargetIndex(List<OrderedItemDTO> items, int currentIndex, Integer requestedPosition) {
        if (items == null || items.isEmpty() || currentIndex < 0 || currentIndex >= items.size()) {
            return currentIndex;
        }
        int requestedIndex = normalizeIndex(requestedPosition, items.size());
        if (requestedIndex == currentIndex) {
            return currentIndex;
        }
        return requestedIndex;
    }

    static List<OrderedItemDTO> moveWithinUnlockedSlots(List<OrderedItemDTO> items, int fromIndex, int toIndex) {
        if (items == null || items.isEmpty() || fromIndex == toIndex) {
            return items;
        }
        List<OrderedItemDTO> reordered = new ArrayList<OrderedItemDTO>(items);
        OrderedItemDTO target = reordered.remove(fromIndex);
        reordered.add(toIndex, target);
        return reordered;
    }

    static int normalizeIndex(Integer position, int size) {
        if (size <= 0) {
            return 0;
        }
        return Math.max(0, Math.min(size - 1, normalizePosition(position, size) - 1));
    }

    static int normalizePosition(Integer position, int size) {
        if (size <= 0) {
            return 1;
        }
        if (position == null || position <= 0) {
            return 1;
        }
        return Math.min(position, size);
    }

}
