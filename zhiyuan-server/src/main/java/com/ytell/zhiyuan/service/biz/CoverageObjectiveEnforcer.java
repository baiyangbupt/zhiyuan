package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

final class CoverageObjectiveEnforcer {

    private CoverageObjectiveEnforcer() {
    }

    static void enforce(PlanningStateDTO state, List<CandidateItemDTO> effectiveCandidates) {
        List<CoverageRequirementDTO> requirements = CoverageRequirementSupport.confirmedRequirements(state);
        Integer requiredCount = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        enforce(state, effectiveCandidates, requirements, requiredCount, "方案覆盖要求");
    }

    static void enforce(PlanningStateDTO state,
                        List<CandidateItemDTO> effectiveCandidates,
                        List<CoverageRequirementDTO> requirements,
                        Integer explicitTargetCount,
                        String objectiveLabel) {
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (requirements.isEmpty() || draft == null) {
            return;
        }
        boolean unitMode = state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        List<Option> current = currentOptions(draft, effectiveCandidates, unitMode);
        List<Option> available = availableOptions(draft, effectiveCandidates, unitMode);
        int[] counts = coverageCounts(current, requirements);
        List<Option> additions = CoverageSelectionSolver.selectMinimum(
                available, requirements, counts,
                CoverageRequirementSupport::minCount, Option::matches);
        if (additions == null) {
            throw new BusinessException(409,
                    "已确认的" + objectiveLabel + "在当前有效候选中无法满足，请先调整要求或刷新候选池");
        }
        if (additions.isEmpty()) {
            return;
        }
        for (Option option : additions) {
            for (int index = 0; index < requirements.size(); index++) {
                if (option.matches(requirements.get(index))) {
                    counts[index]++;
                }
            }
        }

        int targetCount = explicitTargetCount == null || explicitTargetCount <= 0
                ? current.size() + additions.size() : explicitTargetCount;
        int removalCount = Math.max(0, current.size() + additions.size() - targetCount);
        List<Option> removals = Lists.newArrayList();
        for (int index = current.size() - 1; index >= 0 && removals.size() < removalCount; index--) {
            Option option = current.get(index);
            if (option.locked || !canRemove(option, requirements, counts)) {
                continue;
            }
            option.removeFromCounts(requirements, counts);
            removals.add(option);
        }
        if (removals.size() < removalCount) {
            throw new BusinessException(409,
                    "已确认的" + objectiveLabel + "需要等量替换，但当前没有足够的未锁定项目可移出");
        }

        Set<String> removeIds = removals.stream()
                .flatMap(option -> option.volunteerIds.stream())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (!removeIds.isEmpty()) {
            draft.setItems(defaultList(draft.getItems()).stream()
                    .filter(item -> !removeIds.contains(item.getVolunteerId()))
                    .collect(Collectors.toList()));
        }
        for (Option addition : additions) {
            for (CandidateItemDTO candidate : addition.candidates) {
                if (!WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(
                        draft, candidate, "coverage_objective")) {
                    throw new BusinessException(409,
                            "已确认的" + objectiveLabel + "候选无法补入当前方案：" + candidate.getVolunteerId());
                }
            }
        }
        WorkingPlanMutationSupport.syncWorkingPlanUnitsWithItems(
                draft, effectiveCandidates, state.getCandidatePoolState());
        WorkingPlanMutationSupport.recalculateWorkingPlanSummary(
                draft, state.getCandidatePoolState());
    }

    static int[] currentCounts(PlanningStateDTO state,
                               List<CandidateItemDTO> effectiveCandidates,
                               List<CoverageRequirementDTO> requirements) {
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (draft == null) {
            return new int[requirements == null ? 0 : requirements.size()];
        }
        boolean unitMode = state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        return coverageCounts(currentOptions(draft, effectiveCandidates, unitMode), defaultList(requirements));
    }

    private static List<Option> currentOptions(DraftPlanStateDTO draft,
                                               List<CandidateItemDTO> candidates,
                                               boolean unitMode) {
        Map<String, CandidateItemDTO> byVolunteerId = defaultList(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate,
                        (left, right) -> left, LinkedHashMap::new));
        if (!unitMode) {
            List<Option> result = Lists.newArrayList();
            for (DraftItemDTO item : defaultList(draft == null ? null : draft.getItems())) {
                CandidateItemDTO candidate = byVolunteerId.get(item.getVolunteerId());
                if (candidate != null) {
                    result.add(new Option(candidate, Boolean.TRUE.equals(item.getLocked())));
                }
            }
            return result;
        }
        Map<String, List<CandidateItemDTO>> groupedCandidates = new LinkedHashMap<String, List<CandidateItemDTO>>();
        Map<String, Boolean> groupedLocked = new LinkedHashMap<String, Boolean>();
        for (DraftItemDTO item : defaultList(draft == null ? null : draft.getItems())) {
            CandidateItemDTO candidate = byVolunteerId.get(item.getVolunteerId());
            if (candidate == null) {
                continue;
            }
            String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            groupedCandidates.computeIfAbsent(unitId, ignored -> Lists.newArrayList()).add(candidate);
            groupedLocked.put(unitId, Boolean.TRUE.equals(groupedLocked.get(unitId))
                    || Boolean.TRUE.equals(item.getLocked()));
        }
        return groupedCandidates.entrySet().stream()
                .map(entry -> new Option(entry.getKey(), entry.getValue(), Boolean.TRUE.equals(groupedLocked.get(entry.getKey()))))
                .collect(Collectors.toList());
    }

    private static List<Option> availableOptions(DraftPlanStateDTO draft,
                                                 List<CandidateItemDTO> candidates,
                                                 boolean unitMode) {
        Set<String> selectedVolunteerIds = defaultList(draft == null ? null : draft.getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> bannedVolunteerIds = new LinkedHashSet<String>(defaultList(
                draft == null ? null : draft.getBannedVolunteerIds()));
        Map<String, CandidateItemDTO> byVolunteerId = defaultList(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate,
                        (left, right) -> left, LinkedHashMap::new));
        Set<String> selectedUnitIds = selectedVolunteerIds.stream()
                .map(byVolunteerId::get)
                .filter(candidate -> candidate != null)
                .map(RepairCandidateSelector::resolveInitialRecommendationUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (unitMode) {
            Map<String, List<CandidateItemDTO>> grouped = defaultList(candidates).stream()
                    .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                    .filter(candidate -> !selectedUnitIds.contains(
                            RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate)))
                    .collect(Collectors.groupingBy(
                            RepairCandidateSelector::resolveInitialRecommendationUnitId,
                            LinkedHashMap::new,
                            Collectors.toList()));
            return grouped.entrySet().stream()
                    .filter(entry -> !Strings.isNullOrEmpty(entry.getKey()))
                    .filter(entry -> entry.getValue().stream().allMatch(candidate ->
                            !selectedVolunteerIds.contains(candidate.getVolunteerId())
                                    && !bannedVolunteerIds.contains(candidate.getVolunteerId())
                                    && RepairCandidateSelector.isCompensationSafeCandidate(candidate)))
                    .map(entry -> new Option(entry.getKey(), entry.getValue().stream()
                            .sorted(candidateComparator()).collect(Collectors.toList()), false))
                    .sorted((left, right) -> candidateComparator().compare(
                            left.candidates.get(0), right.candidates.get(0)))
                    .collect(Collectors.toList());
        }
        List<CandidateItemDTO> availableCandidates = defaultList(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> !bannedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .sorted(candidateComparator())
                .collect(Collectors.toList());
        return availableCandidates.stream().map(candidate -> new Option(candidate, false)).collect(Collectors.toList());
    }

    private static int[] coverageCounts(List<Option> options, List<CoverageRequirementDTO> requirements) {
        int[] counts = new int[requirements.size()];
        for (int index = 0; index < requirements.size(); index++) {
            CoverageRequirementDTO requirement = requirements.get(index);
            counts[index] = (int) options.stream().filter(option -> option.matches(requirement)).count();
        }
        return counts;
    }

    private static boolean canRemove(Option option,
                                     List<CoverageRequirementDTO> requirements,
                                     int[] counts) {
        for (int index = 0; index < requirements.size(); index++) {
            if (option.matches(requirements.get(index))
                    && counts[index] <= CoverageRequirementSupport.minCount(requirements.get(index))) {
                return false;
            }
        }
        return true;
    }

    private static Comparator<CandidateItemDTO> candidateComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static final class Option {
        private final List<CandidateItemDTO> candidates;
        private final List<String> volunteerIds;
        private final boolean locked;

        private Option(CandidateItemDTO candidate, boolean locked) {
            this.candidates = Lists.newArrayList(candidate);
            this.volunteerIds = Lists.newArrayList(candidate.getVolunteerId());
            this.locked = locked;
        }

        private Option(String unitId, List<CandidateItemDTO> candidates, boolean locked) {
            this.candidates = defaultList(candidates);
            this.volunteerIds = this.candidates.stream()
                    .map(CandidateItemDTO::getVolunteerId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList());
            this.locked = locked;
        }

        private boolean matches(CoverageRequirementDTO requirement) {
            return candidates.stream().anyMatch(candidate -> CoverageRequirementSupport.matches(candidate, requirement));
        }

        private void removeFromCounts(List<CoverageRequirementDTO> requirements, int[] counts) {
            for (int index = 0; index < requirements.size(); index++) {
                if (matches(requirements.get(index))) {
                    counts[index]--;
                }
            }
        }
    }
}
