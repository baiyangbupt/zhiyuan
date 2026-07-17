package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.function.Predicate;
import java.util.stream.Collectors;

final class PriorityObjectiveEnforcer {

    private PriorityObjectiveEnforcer() {
    }

    static void enforce(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        List<PriorityRuleDTO> rules = PriorityRuleSupport.confirmedRules(state);
        if (rules.isEmpty()) {
            return;
        }
        String validationError = PriorityRuleSupport.validate(rules);
        if (!Strings.isNullOrEmpty(validationError)) {
            throw new BusinessException(409, validationError);
        }
        PriorityRuleDTO rule = rules.get(0);
        PriorityRuleSupport.Analysis analysis = PriorityRuleSupport.analyze(state, candidates, rule);
        if (analysis.getEntityCount() == 0) {
            throw new BusinessException(409, "当前没有正式方案，无法执行同档前置规则。");
        }
        if (analysis.getMatchedCount() == 0) {
            throw new BusinessException(409, "当前方案没有命中优先目标；同档前置不会自动增加新志愿。");
        }
        if (analysis.hasMissingTier()) {
            throw new BusinessException(409, "当前方案存在未标注冲稳保档位的项目，不能安全执行同档前置。" );
        }
        if (analysis.hasPinnedConflict()) {
            throw new BusinessException(409, "同档前置会影响已固定位置的志愿，不能在保留固定位置的同时执行。");
        }
        if (analysis.getInversionCount() == 0) {
            return;
        }
        if (analysis.isUnitMode()) {
            reorderUnits(state, candidates, rule);
        } else {
            reorderItems(state, candidates, rule);
        }
    }

    private static void reorderItems(PlanningStateDTO state,
                                     List<CandidateItemDTO> candidates,
                                     PriorityRuleDTO rule) {
        List<OrderedItemDTO> current = new ArrayList<OrderedItemDTO>(state.getOrderedPlanState().getItems());
        Map<String, CandidateItemDTO> byId = candidateMap(candidates);
        Map<String, Integer> before = positions(current, OrderedItemDTO::getVolunteerId);
        List<OrderedItemDTO> reordered = stablePartitionWithinTier(
                current,
                OrderedItemDTO::getTier,
                item -> PriorityRuleSupport.matches(candidateForItem(byId, item), rule));
        for (int index = 0; index < reordered.size(); index++) {
            OrderedItemDTO item = reordered.get(index);
            item.setPosition(index + 1);
            if (!Integer.valueOf(index + 1).equals(before.get(item.getVolunteerId()))) {
                item.setOrderedBy("system");
                item.setOrderReason("hard_priority_rank_before");
            }
        }
        state.getOrderedPlanState().setItems(reordered);
    }

    private static void reorderUnits(PlanningStateDTO state,
                                     List<CandidateItemDTO> candidates,
                                     PriorityRuleDTO rule) {
        List<OrderedUnitDTO> current = new ArrayList<OrderedUnitDTO>(state.getOrderedPlanState().getUnits());
        Map<String, CandidateItemDTO> byId = candidateMap(candidates);
        Map<String, Integer> before = positions(current, OrderedUnitDTO::getUnitId);
        List<OrderedUnitDTO> reordered = stablePartitionWithinTier(
                current,
                OrderedUnitDTO::getTier,
                unit -> unitMatches(unit, byId, rule));
        for (int index = 0; index < reordered.size(); index++) {
            OrderedUnitDTO unit = reordered.get(index);
            unit.setPosition(index + 1);
            if (!Integer.valueOf(index + 1).equals(before.get(unit.getUnitId()))) {
                unit.setOrderedBy("system");
                unit.setOrderReason("hard_priority_rank_before");
            }
        }
        state.getOrderedPlanState().setUnits(reordered);
        state.getOrderedPlanState().setItems(flattenItems(state.getOrderedPlanState().getItems(), reordered));
    }

    private static List<OrderedItemDTO> flattenItems(List<OrderedItemDTO> current,
                                                     List<OrderedUnitDTO> units) {
        Map<String, OrderedItemDTO> byId = current.stream()
                .filter(item -> item != null && !Strings.isNullOrEmpty(item.getVolunteerId()))
                .collect(Collectors.toMap(OrderedItemDTO::getVolunteerId, item -> item,
                        (left, right) -> left, LinkedHashMap::new));
        List<OrderedItemDTO> result = new ArrayList<OrderedItemDTO>();
        Set<String> added = new LinkedHashSet<String>();
        for (OrderedUnitDTO unit : units) {
            for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                OrderedItemDTO item = byId.get(major.getVolunteerId());
                if (item != null && added.add(item.getVolunteerId())) {
                    result.add(item);
                }
            }
        }
        for (OrderedItemDTO item : current) {
            if (item != null && added.add(item.getVolunteerId())) {
                result.add(item);
            }
        }
        for (int index = 0; index < result.size(); index++) {
            result.get(index).setPosition(index + 1);
        }
        return result;
    }

    private static boolean unitMatches(OrderedUnitDTO unit,
                                       Map<String, CandidateItemDTO> byId,
                                       PriorityRuleDTO rule) {
        for (PlanningUnitMajorDTO major : defaultList(unit == null ? null : unit.getMajorItems())) {
            CandidateItemDTO candidate = byId.get(major.getVolunteerId());
            if (PriorityRuleSupport.matches(
                    candidate == null ? PriorityRuleSupport.fallbackCandidate(unit, major) : candidate, rule)) {
                return true;
            }
        }
        return false;
    }

    private static CandidateItemDTO candidateForItem(Map<String, CandidateItemDTO> byId,
                                                      OrderedItemDTO item) {
        CandidateItemDTO candidate = byId.get(item.getVolunteerId());
        if (candidate != null) {
            return candidate;
        }
        CandidateItemDTO fallback = new CandidateItemDTO();
        fallback.setVolunteerId(item.getVolunteerId());
        fallback.setSchoolName(item.getSchoolName());
        fallback.setDisplaySchoolName(item.getSchoolName());
        fallback.setMajorName(item.getMajorName());
        return fallback;
    }

    private static <T> List<T> stablePartitionWithinTier(List<T> current,
                                                         Function<T, String> tier,
                                                         Predicate<T> matches) {
        List<T> result = new ArrayList<T>(current);
        Set<String> tiers = current.stream()
                .map(item -> Strings.nullToEmpty(tier.apply(item)).trim())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        for (String currentTier : tiers) {
            List<Integer> indexes = new ArrayList<Integer>();
            List<T> matching = new ArrayList<T>();
            List<T> other = new ArrayList<T>();
            for (int index = 0; index < current.size(); index++) {
                T item = current.get(index);
                if (!currentTier.equals(Strings.nullToEmpty(tier.apply(item)).trim())) {
                    continue;
                }
                indexes.add(index);
                (matches.test(item) ? matching : other).add(item);
            }
            List<T> partition = new ArrayList<T>(matching);
            partition.addAll(other);
            for (int index = 0; index < indexes.size(); index++) {
                result.set(indexes.get(index), partition.get(index));
            }
        }
        return result;
    }

    private static <T> Map<String, Integer> positions(List<T> values, Function<T, String> id) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        for (int index = 0; index < values.size(); index++) {
            result.put(id.apply(values.get(index)), index + 1);
        }
        return result;
    }

    private static Map<String, CandidateItemDTO> candidateMap(List<CandidateItemDTO> candidates) {
        return defaultList(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate,
                        (left, right) -> left, LinkedHashMap::new));
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
    }
}
