package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;

public class OrderedPlanPositioningSupportTest {

    @Test
    void shouldRebuildItemsSequentiallyAndIgnoreHistoricalPinnedFields() {
        OrderedItemDTO floatingA = item("a");
        OrderedItemDTO historicalPinnedB = pinnedItem("b", 2);
        OrderedItemDTO historicalPinnedC = pinnedItem("c", 2);
        OrderedItemDTO floatingD = item("d");

        List<OrderedItemDTO> rebuilt = OrderedPlanPositioningSupport.rebuildItems(
                Arrays.asList(floatingA, historicalPinnedB, historicalPinnedC, floatingD));

        assertEquals("a", rebuilt.get(0).getVolunteerId());
        assertEquals("b", rebuilt.get(1).getVolunteerId());
        assertEquals("c", rebuilt.get(2).getVolunteerId());
        assertEquals("d", rebuilt.get(3).getVolunteerId());
        assertEquals(Integer.valueOf(1), rebuilt.get(0).getPosition());
        assertEquals(Integer.valueOf(2), rebuilt.get(1).getPosition());
        assertEquals(Integer.valueOf(3), rebuilt.get(2).getPosition());
        assertEquals(Integer.valueOf(4), rebuilt.get(3).getPosition());
    }

    @Test
    void shouldIgnoreHistoricalPinnedPositionWhenRebuildingItems() {
        OrderedItemDTO historicalPinnedA = pinnedItem("a", 99);
        OrderedItemDTO floatingB = item("b");
        OrderedItemDTO floatingC = item("c");

        List<OrderedItemDTO> rebuilt = OrderedPlanPositioningSupport.rebuildItems(
                Arrays.asList(historicalPinnedA, floatingB, floatingC));

        assertEquals("a", rebuilt.get(0).getVolunteerId());
        assertEquals("b", rebuilt.get(1).getVolunteerId());
        assertEquals("c", rebuilt.get(2).getVolunteerId());
        assertEquals(Integer.valueOf(1), rebuilt.get(0).getPosition());
        assertEquals(Integer.valueOf(2), rebuilt.get(1).getPosition());
        assertEquals(Integer.valueOf(3), rebuilt.get(2).getPosition());
    }

    @Test
    void shouldResolveMoveTargetWithoutSkippingHistoricalPinnedSlot() {
        List<OrderedItemDTO> items = Arrays.asList(
                item("a"),
                pinnedItem("b", 2),
                item("c"),
                item("d"));

        assertEquals(1, OrderedPlanPositioningSupport.resolveMovableTargetIndex(items, 0, 2));
        assertEquals(1, OrderedPlanPositioningSupport.resolveMovableTargetIndex(items, 3, 2));
    }

    @Test
    void shouldMoveWithinUnlockedSlotsWithoutMutatingInputList() {
        OrderedItemDTO itemA = item("a");
        OrderedItemDTO itemB = item("b");
        OrderedItemDTO itemC = item("c");
        List<OrderedItemDTO> source = Arrays.asList(itemA, itemB, itemC);

        List<OrderedItemDTO> moved = OrderedPlanPositioningSupport.moveWithinUnlockedSlots(source, 0, 2);

        assertSame(itemA, source.get(0));
        assertEquals("b", moved.get(0).getVolunteerId());
        assertEquals("c", moved.get(1).getVolunteerId());
        assertEquals("a", moved.get(2).getVolunteerId());
    }

    @Test
    void shouldNormalizePositionAndIndex() {
        assertEquals(1, OrderedPlanPositioningSupport.normalizePosition(null, 3));
        assertEquals(1, OrderedPlanPositioningSupport.normalizePosition(0, 3));
        assertEquals(3, OrderedPlanPositioningSupport.normalizePosition(99, 3));
        assertEquals(1, OrderedPlanPositioningSupport.normalizePosition(1, 0));

        assertEquals(0, OrderedPlanPositioningSupport.normalizeIndex(null, 3));
        assertEquals(0, OrderedPlanPositioningSupport.normalizeIndex(0, 3));
        assertEquals(2, OrderedPlanPositioningSupport.normalizeIndex(99, 3));
        assertEquals(0, OrderedPlanPositioningSupport.normalizeIndex(1, 0));
    }

    private static OrderedItemDTO item(String volunteerId) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        return item;
    }

    private static OrderedItemDTO pinnedItem(String volunteerId, Integer pinnedPosition) {
        OrderedItemDTO item = item(volunteerId);
        item.setPinned(true);
        item.setPinnedPosition(pinnedPosition);
        return item;
    }
}
