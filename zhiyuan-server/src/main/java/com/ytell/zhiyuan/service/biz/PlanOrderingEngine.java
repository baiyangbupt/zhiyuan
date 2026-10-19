package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 纯排序引擎：取代旧 Ojalgo 仅用于同档优先/排序的求解调用。
 *
 * <p>语义与旧 solver 的 {@code applyPriorityOrdering} 一致：按“档位首次出现顺序”
 * 分组；组内命中优先规则的条目稳定前置；pinned 条目所在档位发生任何位置变化
 * 即判 conflict。</p>
 */
final class PlanOrderingEngine {

    private PlanOrderingEngine() {
    }

    static OrderResult order(List<OrderEntry> entries, boolean priorityEnabled) {
        List<OrderEntry> selected = entries == null
                ? new ArrayList<OrderEntry>() : new ArrayList<OrderEntry>(entries);
        List<OrderEntry> ordered = new ArrayList<OrderEntry>(selected);
        if (priorityEnabled) {
            Set<String> tiers = new LinkedHashSet<String>();
            for (OrderEntry entry : selected) {
                tiers.add(tier(entry));
            }
            for (String tier : tiers) {
                List<Integer> indexes = new ArrayList<Integer>();
                List<OrderEntry> matched = new ArrayList<OrderEntry>();
                List<OrderEntry> other = new ArrayList<OrderEntry>();
                for (int index = 0; index < selected.size(); index++) {
                    OrderEntry entry = selected.get(index);
                    if (!tier.equals(tier(entry))) {
                        continue;
                    }
                    indexes.add(index);
                    (entry.priorityMatched ? matched : other).add(entry);
                }
                matched.addAll(other);
                for (int index = 0; index < indexes.size(); index++) {
                    ordered.set(indexes.get(index), matched.get(index));
                }
            }
        }
        Map<String, Integer> beforePositions = positions(selected);
        Map<String, Integer> afterPositions = positions(ordered);
        Set<String> changedTiers = new LinkedHashSet<String>();
        for (OrderEntry entry : selected) {
            Integer before = beforePositions.get(entry.entityId);
            Integer after = afterPositions.get(entry.entityId);
            if (before != null && after != null && !before.equals(after)) {
                changedTiers.add(tier(entry));
            }
        }
        boolean pinnedConflict = selected.stream()
                .anyMatch(entry -> entry.pinned && changedTiers.contains(tier(entry)));
        OrderResult result = new OrderResult();
        result.selectedIds = ids(selected);
        result.orderedIds = ids(ordered);
        result.pinnedConflict = pinnedConflict;
        result.inversionCount = priorityEnabled ? priorityInversions(ordered) : 0;
        return result;
    }

    static OrderResult orderByProbability(List<OrderEntry> entries, Map<String, Double> ratios) {
        if (entries == null || ratios == null) {
            throw new IllegalArgumentException("probability_order_input_missing");
        }
        Set<String> identities = new LinkedHashSet<String>();
        List<OrderEntry> movable = new ArrayList<OrderEntry>();
        for (OrderEntry entry : entries) {
            Double ratio = entry == null ? null : ratios.get(entry.entityId);
            if (entry == null || Strings.isNullOrEmpty(entry.entityId) || !identities.add(entry.entityId)
                    || ratio == null || !Double.isFinite(ratio)) {
                throw new IllegalArgumentException("probability_order_facts_incomplete");
            }
            if (!entry.pinned) {
                movable.add(entry);
            }
        }
        movable.sort((left, right) -> Double.compare(ratios.get(left.entityId), ratios.get(right.entityId)));
        List<OrderEntry> ordered = new ArrayList<OrderEntry>();
        int next = 0;
        for (OrderEntry entry : entries) {
            ordered.add(entry.pinned ? entry : movable.get(next++));
        }
        OrderResult result = new OrderResult();
        result.selectedIds = ids(entries);
        result.orderedIds = ids(ordered);
        for (int index = 1; index < ordered.size(); index++) {
            if (ratios.get(ordered.get(index - 1).entityId) - ratios.get(ordered.get(index).entityId) > 1e-9D) {
                result.inversionCount++;
            }
        }
        return result;
    }

    private static int priorityInversions(List<OrderEntry> ordered) {
        Map<String, Integer> unmatched = new LinkedHashMap<String, Integer>();
        int result = 0;
        for (OrderEntry entry : ordered) {
            String tier = tier(entry);
            if (entry.priorityMatched) {
                Integer count = unmatched.get(tier);
                result += count == null ? 0 : count;
            } else {
                unmatched.put(tier, (unmatched.get(tier) == null ? 0 : unmatched.get(tier)) + 1);
            }
        }
        return result;
    }

    private static Map<String, Integer> positions(List<OrderEntry> entries) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        for (int index = 0; index < entries.size(); index++) {
            result.put(entries.get(index).entityId, index);
        }
        return result;
    }

    private static List<String> ids(List<OrderEntry> entries) {
        List<String> result = new ArrayList<String>();
        for (OrderEntry entry : entries) {
            result.add(entry.entityId);
        }
        return result;
    }

    private static String tier(OrderEntry entry) {
        String tier = TierAllocationSupport.canonicalTierKey(entry == null ? null : entry.tier);
        return Strings.isNullOrEmpty(tier) ? "unknown" : tier;
    }

    static final class OrderEntry {
        final String entityId;
        final String tier;
        final boolean priorityMatched;
        final boolean pinned;

        OrderEntry(String entityId, String tier, boolean priorityMatched, boolean pinned) {
            this.entityId = entityId;
            this.tier = tier;
            this.priorityMatched = priorityMatched;
            this.pinned = pinned;
        }
    }

    static final class OrderResult {
        List<String> selectedIds;
        List<String> orderedIds;
        boolean pinnedConflict;
        int inversionCount;

        boolean changed() {
            return !selectedIds.equals(orderedIds);
        }
    }
}
