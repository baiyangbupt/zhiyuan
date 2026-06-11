package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;

import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

final class RepairCandidateSelector {

    private RepairCandidateSelector() {
    }

    static Selection selectTierRatioReplacementSources(PlanningStateDTO state,
                                                       List<CandidateItemDTO> candidates,
                                                       String targetTier,
                                                       int limit) {
        boolean majorGroupMode = isMajorGroupMode(state == null ? null : state.getCandidatePoolState());
        String removeTier = resolveCompensationSurplusTier(state, targetTier, majorGroupMode);
        Selection selection = majorGroupMode
                ? selectSurplusUnitReplacementSources(state, candidates, removeTier, limit)
                : selectSurplusVolunteerReplacementSources(state, candidates, removeTier, limit);
        selection.removeTier = removeTier;
        return selection;
    }

    static Selection selectProbabilityGapReplacementSources(PlanningStateDTO state,
                                                            List<CandidateItemDTO> candidates,
                                                            ReviewCheckDTO check,
                                                            int limit) {
        boolean majorGroupMode = isMajorGroupMode(state == null ? null : state.getCandidatePoolState());
        return majorGroupMode
                ? selectProbabilityGapUnitReplacementSources(state, candidates, check, limit)
                : selectProbabilityGapVolunteerReplacementSources(state, candidates, check, limit);
    }

    static RiskReplacementSelection selectRiskItemReplacements(PlanningStateDTO state,
                                                               List<CandidateItemDTO> candidates,
                                                               List<String> affectedVolunteerIds) {
        RiskReplacementSelection selection = new RiskReplacementSelection();
        if (state == null || state.getCandidatePoolState() == null) {
            selection.noReplacementCount = defaultList(affectedVolunteerIds).size();
            return selection;
        }
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        Set<String> currentVolunteerIds = defaultDraftItems(state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> currentUnitIds = defaultDraftItems(state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .map(item -> resolveUnitId(item.getVolunteerId(), candidates))
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> usedReplacementVolunteerIds = new LinkedHashSet<String>();
        Set<String> usedReplacementUnitIds = new LinkedHashSet<String>();

        for (String affectedVolunteerId : defaultList(affectedVolunteerIds)) {
            CandidateItemDTO source = findCandidate(candidates, affectedVolunteerId);
            if (source == null) {
                selection.missingSourceCount++;
                continue;
            }
            CandidateItemDTO replacement = defaultCandidates(candidates).stream()
                    .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                    .filter(candidate -> !affectedVolunteerId.equals(candidate.getVolunteerId()))
                    .filter(candidate -> !currentVolunteerIds.contains(candidate.getVolunteerId()))
                    .filter(candidate -> !usedReplacementVolunteerIds.contains(candidate.getVolunteerId()))
                    .filter(candidate -> sameTierValue(candidate.getTier(), source.getTier()))
                    .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                    .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                    .filter(candidate -> !majorGroupMode || !currentUnitIds.contains(resolveInitialRecommendationUnitId(candidate)))
                    .filter(candidate -> !majorGroupMode || !usedReplacementUnitIds.contains(resolveInitialRecommendationUnitId(candidate)))
                    .filter(candidate -> isRiskReplacementQualityAcceptable(source, candidate))
                    .sorted(buildRiskReplacementCandidateComparator(source))
                    .findFirst()
                    .orElse(null);
            if (replacement == null) {
                selection.noReplacementCount++;
                continue;
            }
            selection.pairs.add(new RiskReplacementPair(source, replacement));
            usedReplacementVolunteerIds.add(replacement.getVolunteerId());
            String replacementUnitId = resolveInitialRecommendationUnitId(replacement);
            if (!Strings.isNullOrEmpty(replacementUnitId)) {
                usedReplacementUnitIds.add(replacementUnitId);
            }
        }
        return selection;
    }

    static Selection selectTotalCountVolunteerAdditions(PlanningStateDTO state,
                                                        List<CandidateItemDTO> availableCandidates) {
        Integer requiredCount = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        int currentCount = currentOrderedOrDraftItemCount(state);
        if (requiredCount == null || requiredCount <= currentCount) {
            return new Selection();
        }
        return selectTotalCountVolunteerAdditions(
                state, availableCandidates, requiredCount - currentCount, resolveCompensationShortageTier(state, false));
    }

    static Selection selectTotalCountVolunteerAdditions(PlanningStateDTO state,
                                                        List<CandidateItemDTO> availableCandidates,
                                                        int limit,
                                                        String shortageTier) {
        Selection selection = new Selection();
        if (limit <= 0) {
            return selection;
        }
        List<CandidateItemDTO> candidatesWithoutHardConstraints = defaultCandidates(availableCandidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toList());
        List<CandidateItemDTO> candidatesWithHardConstraints = candidatesWithoutHardConstraints.stream()
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .collect(Collectors.toList());
        List<String> volunteerIds = candidatesWithHardConstraints.stream()
                .sorted(buildTotalCountCandidateComparator(state, shortageTier))
                .limit(limit)
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        selection.candidateVolunteerIds.addAll(volunteerIds);
        applySelectionDiagnostics(state, selection, limit, shortageTier, selection.candidateVolunteerIds.size(),
                candidatesWithHardConstraints.size(), candidatesWithoutHardConstraints.size());
        return selection;
    }

    static Selection selectTotalCountUnitAdditions(PlanningStateDTO state,
                                                   List<PlanningUnitDTO> availableUnits) {
        Integer requiredCount = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        int currentCount = currentOrderedOrDraftUnitCount(state);
        if (requiredCount == null || requiredCount <= currentCount) {
            return new Selection();
        }
        int gap = requiredCount - currentCount;
        Selection selection = new Selection();
        List<PlanningUnitDTO> unitsWithoutHardConstraints = defaultPlanningUnits(availableUnits).stream()
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        List<PlanningUnitDTO> unitsWithHardConstraints = unitsWithoutHardConstraints.stream()
                .filter(unit -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(unit, state))
                .collect(Collectors.toList());
        List<PlanningUnitDTO> selectedUnits = unitsWithHardConstraints.stream()
                .sorted(buildTotalCountUnitComparator(state))
                .limit(gap)
                .collect(Collectors.toList());
        addSelectedUnits(selection, selectedUnits);
        applySelectionDiagnostics(state, selection, gap, resolveCompensationShortageTier(state, true),
                selection.candidateUnitIds.size(), unitsWithHardConstraints.size(), unitsWithoutHardConstraints.size());
        return selection;
    }

    static Selection selectLocalProtectVolunteerAdditions(PlanningStateDTO state,
                                                          List<CandidateItemDTO> candidates,
                                                          List<CandidateItemDTO> availableCandidates) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        String sourceProvinceName = candidatePoolState == null ? null : candidatePoolState.getSourceProvinceName();
        Integer userScore = candidatePoolState == null ? null : candidatePoolState.getUserScore();
        if (userScore != null && userScore >= 580) {
            return new Selection();
        }
        if (Strings.isNullOrEmpty(sourceProvinceName)) {
            return new Selection();
        }

        int localProtectCount = 0;
        for (OrderedItemDTO orderedItem : defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems())) {
            if (!"保".equals(orderedItem.getTier())) {
                continue;
            }
            CandidateItemDTO candidateItem = findCandidate(candidates, orderedItem.getVolunteerId());
            if (candidateItem != null && containsIgnoreCase(candidateItem.getProvinceName(), sourceProvinceName)) {
                localProtectCount++;
            }
        }
        if (localProtectCount >= 2) {
            return new Selection();
        }

        int need = 2 - localProtectCount;
        Selection selection = new Selection();
        List<CandidateItemDTO> candidatesWithoutHardConstraints = defaultCandidates(availableCandidates).stream()
                .filter(item -> item != null && "保".equals(item.getTier()))
                .filter(item -> containsIgnoreCase(item.getProvinceName(), sourceProvinceName))
                .collect(Collectors.toList());
        List<CandidateItemDTO> candidatesWithHardConstraints = candidatesWithoutHardConstraints.stream()
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .collect(Collectors.toList());
        List<String> volunteerIds = candidatesWithHardConstraints.stream()
                .limit(need)
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        selection.candidateVolunteerIds.addAll(volunteerIds);
        applySelectionDiagnostics(state, selection, need, "保", selection.candidateVolunteerIds.size(),
                candidatesWithHardConstraints.size(), candidatesWithoutHardConstraints.size());
        return selection;
    }

    static Selection selectLocalProtectUnitAdditions(PlanningStateDTO state,
                                                     List<PlanningUnitDTO> availableUnits) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        String sourceProvinceName = candidatePoolState == null ? null : candidatePoolState.getSourceProvinceName();
        Integer userScore = candidatePoolState == null ? null : candidatePoolState.getUserScore();
        if (userScore != null && userScore >= 580) {
            return new Selection();
        }
        if (Strings.isNullOrEmpty(sourceProvinceName)) {
            return new Selection();
        }

        int localProtectCount = (int) defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits()).stream()
                .filter(unit -> "保".equals(unit.getTier()))
                .filter(unit -> containsIgnoreCase(unit.getProvinceName(), sourceProvinceName))
                .count();
        if (localProtectCount >= 2) {
            return new Selection();
        }

        int need = 2 - localProtectCount;
        Selection selection = new Selection();
        List<PlanningUnitDTO> unitsWithoutHardConstraints = defaultPlanningUnits(availableUnits).stream()
                .filter(unit -> unit != null && "保".equals(unit.getTier()))
                .filter(unit -> containsIgnoreCase(unit.getProvinceName(), sourceProvinceName))
                .collect(Collectors.toList());
        List<PlanningUnitDTO> unitsWithHardConstraints = unitsWithoutHardConstraints.stream()
                .filter(unit -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(unit, state))
                .collect(Collectors.toList());
        List<PlanningUnitDTO> selectedUnits = unitsWithHardConstraints.stream()
                .limit(need)
                .collect(Collectors.toList());
        addSelectedUnits(selection, selectedUnits);
        applySelectionDiagnostics(state, selection, need, "保", selection.candidateUnitIds.size(),
                unitsWithHardConstraints.size(), unitsWithoutHardConstraints.size());
        return selection;
    }

    static Selection selectProtectRatioVolunteerAdditions(PlanningStateDTO state,
                                                          List<CandidateItemDTO> availableCandidates) {
        int total = currentOrderedOrDraftItemCount(state);
        if (total <= 0) {
            return new Selection();
        }
        int protectCount = currentOrderedOrDraftTierCount(state, "保");
        int targetProtectCount = resolveCompensationTierTargetCount(state, "保", total);
        if (targetProtectCount <= 0 || protectCount >= targetProtectCount) {
            return new Selection();
        }

        int need = targetProtectCount - protectCount;
        String sourceProvinceName = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getSourceProvinceName();
        Selection selection = new Selection();
        List<CandidateItemDTO> candidatesWithoutHardConstraints = defaultCandidates(availableCandidates).stream()
                .filter(item -> item != null && "保".equals(item.getTier()))
                .collect(Collectors.toList());
        List<CandidateItemDTO> candidatesWithHardConstraints = candidatesWithoutHardConstraints.stream()
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .collect(Collectors.toList());
        List<String> volunteerIds = candidatesWithHardConstraints.stream()
                .sorted(buildProtectCandidateComparator(sourceProvinceName))
                .limit(need)
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        selection.candidateVolunteerIds.addAll(volunteerIds);
        applySelectionDiagnostics(state, selection, need, "保", selection.candidateVolunteerIds.size(),
                candidatesWithHardConstraints.size(), candidatesWithoutHardConstraints.size());
        return selection;
    }

    static Selection selectProtectRatioUnitAdditions(PlanningStateDTO state,
                                                     List<PlanningUnitDTO> availableUnits) {
        int total = currentOrderedOrDraftUnitCount(state);
        if (total <= 0) {
            return new Selection();
        }
        int protectCount = currentOrderedOrDraftUnitTierCount(state, "保");
        int targetProtectCount = resolveCompensationTierTargetCount(state, "保", total);
        if (targetProtectCount <= 0 || protectCount >= targetProtectCount) {
            return new Selection();
        }

        int need = targetProtectCount - protectCount;
        String sourceProvinceName = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getSourceProvinceName();
        Selection selection = new Selection();
        List<PlanningUnitDTO> unitsWithoutHardConstraints = defaultPlanningUnits(availableUnits).stream()
                .filter(unit -> unit != null && "保".equals(unit.getTier()))
                .collect(Collectors.toList());
        List<PlanningUnitDTO> unitsWithHardConstraints = unitsWithoutHardConstraints.stream()
                .filter(unit -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(unit, state))
                .collect(Collectors.toList());
        List<PlanningUnitDTO> selectedUnits = unitsWithHardConstraints.stream()
                .sorted(buildProtectUnitComparator(sourceProvinceName))
                .limit(need)
                .collect(Collectors.toList());
        addSelectedUnits(selection, selectedUnits);
        applySelectionDiagnostics(state, selection, need, "保", selection.candidateUnitIds.size(),
                unitsWithHardConstraints.size(), unitsWithoutHardConstraints.size());
        return selection;
    }

    static Selection selectProbabilityGapVolunteerAdditions(PlanningStateDTO state,
                                                            List<CandidateItemDTO> candidates,
                                                            List<CandidateItemDTO> availableCandidates) {
        List<OrderedItemDTO> orderedItems = defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems());
        if (orderedItems.size() <= 1) {
            return new Selection();
        }
        for (int i = 1; i < orderedItems.size(); i++) {
            OrderedItemDTO previous = orderedItems.get(i - 1);
            OrderedItemDTO current = orderedItems.get(i);
            Double previousRatio = admissionRatioOf(candidates, previous.getVolunteerId());
            Double currentRatio = admissionRatioOf(candidates, current.getVolunteerId());
            if (previousRatio == null || currentRatio == null || Math.abs(currentRatio - previousRatio) <= 8D) {
                continue;
            }
            double min = Math.min(previousRatio, currentRatio);
            double max = Math.max(previousRatio, currentRatio);
            double midpoint = (min + max) / 2D;
            Selection selection = new Selection();
            selection.rangeMin = min;
            selection.rangeMax = max;
            List<CandidateItemDTO> candidatesWithoutHardConstraints = defaultCandidates(availableCandidates).stream()
                    .filter(item -> item != null && item.getAdmissionRatio() != null)
                    .filter(item -> item.getAdmissionRatio() > min && item.getAdmissionRatio() < max)
                    .collect(Collectors.toList());
            List<CandidateItemDTO> candidatesWithHardConstraints = candidatesWithoutHardConstraints.stream()
                    .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                    .collect(Collectors.toList());
            List<String> volunteerIds = candidatesWithHardConstraints.stream()
                    .sorted(buildProbabilityGapCandidateComparator(midpoint))
                    .limit(2)
                    .map(CandidateItemDTO::getVolunteerId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList());
            selection.candidateVolunteerIds.addAll(volunteerIds);
            applySelectionDiagnostics(state, selection, 1, null, selection.candidateVolunteerIds.size(),
                    candidatesWithHardConstraints.size(), candidatesWithoutHardConstraints.size());
            if (!selection.candidateVolunteerIds.isEmpty()) {
                return selection;
            }
        }
        return new Selection();
    }

    static Selection selectProbabilityGapUnitAdditions(PlanningStateDTO state,
                                                       List<PlanningUnitDTO> availableUnits) {
        List<OrderedUnitDTO> orderedUnits = defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits());
        if (orderedUnits.size() <= 1) {
            return new Selection();
        }
        for (int i = 1; i < orderedUnits.size(); i++) {
            OrderedUnitDTO previous = orderedUnits.get(i - 1);
            OrderedUnitDTO current = orderedUnits.get(i);
            Double previousRatio = previous.getAdmissionRatio();
            Double currentRatio = current.getAdmissionRatio();
            if (previousRatio == null || currentRatio == null || Math.abs(currentRatio - previousRatio) <= 8D) {
                continue;
            }
            double min = Math.min(previousRatio, currentRatio);
            double max = Math.max(previousRatio, currentRatio);
            double midpoint = (min + max) / 2D;
            Selection selection = new Selection();
            selection.rangeMin = min;
            selection.rangeMax = max;
            List<PlanningUnitDTO> unitsWithoutHardConstraints = defaultPlanningUnits(availableUnits).stream()
                    .filter(unit -> unit != null && unit.getAdmissionRatio() != null)
                    .filter(unit -> unit.getAdmissionRatio() > min && unit.getAdmissionRatio() < max)
                    .collect(Collectors.toList());
            List<PlanningUnitDTO> unitsWithHardConstraints = unitsWithoutHardConstraints.stream()
                    .filter(unit -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(unit, state))
                    .collect(Collectors.toList());
            List<PlanningUnitDTO> selectedUnits = unitsWithHardConstraints.stream()
                    .sorted(buildProbabilityGapUnitCandidateComparator(midpoint))
                    .limit(2)
                    .collect(Collectors.toList());
            addSelectedUnits(selection, selectedUnits);
            applySelectionDiagnostics(state, selection, 1, null, selection.candidateUnitIds.size(),
                    unitsWithHardConstraints.size(), unitsWithoutHardConstraints.size());
            if (!selection.candidateUnitIds.isEmpty()) {
                return selection;
            }
        }
        return new Selection();
    }

    private static String resolveCompensationSurplusTier(PlanningStateDTO state,
                                                         String targetTier,
                                                         boolean majorGroupMode) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        if (candidatePoolState != null
                && candidatePoolState.getRequiredTierCounts() != null
                && !candidatePoolState.getRequiredTierCounts().isEmpty()) {
            String surplusTier = null;
            int maxSurplus = 0;
            for (String tier : Lists.newArrayList("冲", "稳", "保")) {
                if (tier.equals(targetTier)) {
                    continue;
                }
                int target = positiveCount(candidatePoolState.getRequiredTierCounts().get(tier));
                int current = majorGroupMode
                        ? currentOrderedOrDraftUnitTierCount(state, tier)
                        : currentOrderedOrDraftTierCount(state, tier);
                int surplus = current - target;
                if (surplus > maxSurplus) {
                    maxSurplus = surplus;
                    surplusTier = tier;
                }
            }
            if (!Strings.isNullOrEmpty(surplusTier)) {
                return surplusTier;
            }
        }
        if ("保".equals(targetTier)) {
            return "冲";
        }
        return "冲";
    }

    private static Selection selectSurplusVolunteerReplacementSources(PlanningStateDTO state,
                                                                      List<CandidateItemDTO> candidates,
                                                                      String removeTier,
                                                                      int limit) {
        Selection selection = new Selection();
        if (limit <= 0) {
            return selection;
        }
        List<String> removeIds = !defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).isEmpty()
                ? defaultOrderedItems(state.getOrderedPlanState().getItems()).stream()
                .filter(item -> item != null && removeTier.equals(item.getTier()))
                .filter(item -> !Boolean.TRUE.equals(item.getLocked()))
                .sorted(buildOrderedItemReplacementSourceComparator(candidates))
                .limit(limit)
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toList())
                : defaultDraftItems(state == null || state.getDraftPlanState() == null
                ? null : state.getDraftPlanState().getItems()).stream()
                .filter(item -> item != null && removeTier.equals(item.getTier()))
                .filter(item -> !Boolean.TRUE.equals(item.getLocked()))
                .sorted(buildDraftItemReplacementSourceComparator(candidates))
                .limit(limit)
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        selection.removeVolunteerIds.addAll(removeIds);
        return selection;
    }

    private static Selection selectSurplusUnitReplacementSources(PlanningStateDTO state,
                                                                 List<CandidateItemDTO> candidates,
                                                                 String removeTier,
                                                                 int limit) {
        Selection selection = new Selection();
        if (limit <= 0) {
            return selection;
        }
        List<OrderedUnitDTO> orderedUnits = defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits());
        if (!orderedUnits.isEmpty()) {
            List<String> unitIds = orderedUnits.stream()
                    .filter(unit -> unit != null && removeTier.equals(unit.getTier()))
                    .filter(unit -> !Boolean.TRUE.equals(unit.getLocked()))
                .sorted(buildOrderedUnitReplacementSourceComparator(candidates))
                .limit(limit)
                .map(OrderedUnitDTO::getUnitId)
                .collect(Collectors.toList());
            selection.removeUnitIds.addAll(unitIds);
            selection.removeVolunteerIds.addAll(filterOrderedVolunteerIdsByUnitIds(state, candidates, unitIds));
            return selection;
        }
        List<String> unitIds = defaultDraftUnits(state == null || state.getDraftPlanState() == null
                ? null : state.getDraftPlanState().getUnits()).stream()
                .filter(unit -> unit != null && removeTier.equals(unit.getTier()))
                .filter(unit -> !Boolean.TRUE.equals(unit.getLocked()))
                .sorted(buildDraftUnitReplacementSourceComparator(candidates))
                .limit(limit)
                .map(DraftUnitDTO::getUnitId)
                .collect(Collectors.toList());
        selection.removeUnitIds.addAll(unitIds);
        selection.removeVolunteerIds.addAll(filterDraftVolunteerIdsByUnitIds(state, candidates, unitIds));
        return selection;
    }

    private static Selection selectProbabilityGapVolunteerReplacementSources(PlanningStateDTO state,
                                                                            List<CandidateItemDTO> candidates,
                                                                            ReviewCheckDTO check,
                                                                            int limit) {
        Selection selection = new Selection();
        if (limit <= 0) {
            return selection;
        }
        Set<String> affectedIds = new LinkedHashSet<String>(defaultList(check == null ? null : check.getAffectedVolunteerIds()));
        selection.removeVolunteerIds.addAll(defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).stream()
                .filter(item -> item != null && affectedIds.contains(item.getVolunteerId()))
                .filter(item -> !Boolean.TRUE.equals(item.getLocked()))
                .sorted(buildProbabilityGapReplacementSourceComparator(candidates, affectedIds))
                .limit(limit)
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toList()));
        if (selection.removeVolunteerIds.isEmpty()) {
            selection.removeVolunteerIds.addAll(defaultDraftItems(state == null || state.getDraftPlanState() == null
                    ? null : state.getDraftPlanState().getItems()).stream()
                    .filter(item -> item != null && affectedIds.contains(item.getVolunteerId()))
                    .filter(item -> !Boolean.TRUE.equals(item.getLocked()))
                    .sorted((left, right) -> buildProbabilityGapReplacementSourceComparator(candidates, affectedIds)
                            .compare(toOrderedItem(left), toOrderedItem(right)))
                    .limit(limit)
                    .map(DraftItemDTO::getVolunteerId)
                    .collect(Collectors.toList()));
        }
        return selection;
    }

    private static Selection selectProbabilityGapUnitReplacementSources(PlanningStateDTO state,
                                                                        List<CandidateItemDTO> candidates,
                                                                        ReviewCheckDTO check,
                                                                        int limit) {
        Selection selection = new Selection();
        if (limit <= 0) {
            return selection;
        }
        Set<String> affectedUnitIds = new LinkedHashSet<String>(defaultList(check == null ? null : check.getAffectedUnitIds()));
        List<String> unitIds = defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits()).stream()
                .filter(unit -> unit != null && affectedUnitIds.contains(unit.getUnitId()))
                .filter(unit -> !Boolean.TRUE.equals(unit.getLocked()))
                .sorted(buildProbabilityGapUnitReplacementSourceComparator(affectedUnitIds, state))
                .limit(limit)
                .map(OrderedUnitDTO::getUnitId)
                .collect(Collectors.toList());
        if (unitIds.isEmpty()) {
            unitIds = defaultDraftUnits(state == null || state.getDraftPlanState() == null
                    ? null : state.getDraftPlanState().getUnits()).stream()
                    .filter(unit -> unit != null && affectedUnitIds.contains(unit.getUnitId()))
                    .filter(unit -> !Boolean.TRUE.equals(unit.getLocked()))
                    .sorted(buildProbabilityGapDraftUnitReplacementSourceComparator(affectedUnitIds, state))
                    .limit(limit)
                    .map(DraftUnitDTO::getUnitId)
                    .collect(Collectors.toList());
        }
        selection.removeUnitIds.addAll(unitIds);
        selection.removeVolunteerIds.addAll(!defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).isEmpty()
                ? filterOrderedVolunteerIdsByUnitIds(state, candidates, unitIds)
                : filterDraftVolunteerIdsByUnitIds(state, candidates, unitIds));
        return selection;
    }

    private static Comparator<OrderedItemDTO> buildOrderedItemReplacementSourceComparator(List<CandidateItemDTO> candidates) {
        return Comparator
                .comparing((OrderedItemDTO item) -> admissionRatioOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> finalScoreOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> intentScoreOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> schoolRankOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(OrderedItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<DraftItemDTO> buildDraftItemReplacementSourceComparator(List<CandidateItemDTO> candidates) {
        return Comparator
                .comparing((DraftItemDTO item) -> admissionRatioOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> finalScoreOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> intentScoreOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> schoolRankOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(DraftItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<OrderedUnitDTO> buildOrderedUnitReplacementSourceComparator(List<CandidateItemDTO> candidates) {
        return Comparator
                .comparing((OrderedUnitDTO unit) -> unit.getAdmissionRatio(), Comparator.nullsLast(Double::compareTo))
                .thenComparing((OrderedUnitDTO unit) -> unit.getFinalScore(), Comparator.nullsLast(Double::compareTo))
                .thenComparing(unit -> averageUnitMetric(candidates, unit == null ? null : unit.getUnitId(), CandidateItemDTO::getIntentScore),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing(unit -> bestUnitSchoolRank(candidates, unit == null ? null : unit.getUnitId()),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(OrderedUnitDTO::getUnitId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<DraftUnitDTO> buildDraftUnitReplacementSourceComparator(List<CandidateItemDTO> candidates) {
        return Comparator
                .comparing((DraftUnitDTO unit) -> averageAdmissionRatio(defaultPlanningUnitMajors(unit.getMajorItems()), candidates),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing(unit -> averageMajorMetric(defaultPlanningUnitMajors(unit.getMajorItems()), candidates, CandidateItemDTO::getFinalScore),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing(unit -> averageMajorMetric(defaultPlanningUnitMajors(unit.getMajorItems()), candidates, CandidateItemDTO::getIntentScore),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing(unit -> bestMajorSchoolRank(defaultPlanningUnitMajors(unit.getMajorItems()), candidates),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(DraftUnitDTO::getUnitId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<OrderedItemDTO> buildProbabilityGapReplacementSourceComparator(List<CandidateItemDTO> candidates,
                                                                                            Set<String> affectedIds) {
        double midpoint = probabilityGapAffectedMidpoint(candidates, affectedIds);
        return Comparator
                .comparingDouble((OrderedItemDTO item) -> -Math.abs(defaultDouble(admissionRatioOf(candidates, item.getVolunteerId())) - midpoint))
                .thenComparing(item -> admissionRatioOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> finalScoreOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> intentScoreOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> schoolRankOf(candidates, item.getVolunteerId()), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(OrderedItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<OrderedUnitDTO> buildProbabilityGapUnitReplacementSourceComparator(Set<String> affectedUnitIds,
                                                                                                 PlanningStateDTO state) {
        double midpoint = probabilityGapAffectedUnitMidpoint(state, affectedUnitIds);
        return Comparator
                .comparingDouble((OrderedUnitDTO unit) -> -Math.abs(defaultDouble(unit.getAdmissionRatio()) - midpoint))
                .thenComparing(OrderedUnitDTO::getAdmissionRatio, Comparator.nullsLast(Double::compareTo))
                .thenComparing(OrderedUnitDTO::getFinalScore, Comparator.nullsLast(Double::compareTo))
                .thenComparing(unit -> averageUnitMetric(defaultCandidates(state == null || state.getCandidatePoolState() == null
                                ? null : state.getCandidatePoolState().getItems()), unit == null ? null : unit.getUnitId(),
                        CandidateItemDTO::getIntentScore), Comparator.nullsLast(Double::compareTo))
                .thenComparing(OrderedUnitDTO::getUnitId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<DraftUnitDTO> buildProbabilityGapDraftUnitReplacementSourceComparator(Set<String> affectedUnitIds,
                                                                                                    PlanningStateDTO state) {
        List<CandidateItemDTO> candidates = defaultCandidates(state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getItems());
        double midpoint = probabilityGapAffectedUnitMidpoint(state, affectedUnitIds);
        return Comparator
                .comparingDouble((DraftUnitDTO unit) -> -Math.abs(defaultDouble(averageAdmissionRatio(
                        defaultPlanningUnitMajors(unit.getMajorItems()), candidates)) - midpoint))
                .thenComparing(unit -> averageMajorMetric(defaultPlanningUnitMajors(unit.getMajorItems()), candidates, CandidateItemDTO::getFinalScore),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing(unit -> averageMajorMetric(defaultPlanningUnitMajors(unit.getMajorItems()), candidates, CandidateItemDTO::getIntentScore),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing(DraftUnitDTO::getUnitId, Comparator.nullsLast(String::compareTo));
    }

    private static OrderedItemDTO toOrderedItem(DraftItemDTO item) {
        OrderedItemDTO orderedItem = new OrderedItemDTO();
        if (item == null) {
            return orderedItem;
        }
        orderedItem.setVolunteerId(item.getVolunteerId());
        orderedItem.setTier(item.getTier());
        orderedItem.setSchoolName(item.getSchoolName());
        orderedItem.setMajorName(item.getMajorName());
        orderedItem.setLocked(item.getLocked());
        return orderedItem;
    }

    private static int currentOrderedOrDraftItemCount(PlanningStateDTO state) {
        List<OrderedItemDTO> orderedItems = defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems());
        if (!orderedItems.isEmpty()) {
            return orderedItems.size();
        }
        return defaultDraftItems(state == null || state.getDraftPlanState() == null
                ? null : state.getDraftPlanState().getItems()).size();
    }

    private static int currentOrderedOrDraftUnitCount(PlanningStateDTO state) {
        List<OrderedUnitDTO> orderedUnits = defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits());
        if (!orderedUnits.isEmpty()) {
            return orderedUnits.size();
        }
        return defaultDraftUnits(state == null || state.getDraftPlanState() == null
                ? null : state.getDraftPlanState().getUnits()).size();
    }

    private static int currentOrderedOrDraftTierCount(PlanningStateDTO state, String tier) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null
                && state.getOrderedPlanState().getItems() != null
                && !state.getOrderedPlanState().getItems().isEmpty()) {
            return (int) state.getOrderedPlanState().getItems().stream()
                    .filter(item -> tier.equals(item.getTier()))
                    .count();
        }
        return (int) defaultDraftItems(state.getDraftPlanState() == null ? null : state.getDraftPlanState().getItems()).stream()
                .filter(item -> tier.equals(item.getTier()))
                .count();
    }

    private static int currentOrderedOrDraftUnitTierCount(PlanningStateDTO state, String tier) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null
                && !defaultOrderedUnits(state.getOrderedPlanState().getUnits()).isEmpty()) {
            return (int) defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                    .filter(unit -> tier.equals(unit.getTier()))
                    .count();
        }
        return (int) defaultDraftUnits(state.getDraftPlanState() == null ? null : state.getDraftPlanState().getUnits()).stream()
                .filter(unit -> tier.equals(unit.getTier()))
                .count();
    }

    private static Comparator<CandidateItemDTO> buildTotalCountCandidateComparator(PlanningStateDTO state,
                                                                                   String shortageTier) {
        String sourceProvinceName = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getSourceProvinceName();
        return Comparator
                .comparingInt((CandidateItemDTO item) -> tierShortagePriority(item == null ? null : item.getTier(), shortageTier))
                .thenComparingInt((CandidateItemDTO item) -> "保".equals(shortageTier)
                        ? localProtectCandidatePriority(item, sourceProvinceName) : 1)
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getRankInTier(), Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<PlanningUnitDTO> buildTotalCountUnitComparator(PlanningStateDTO state) {
        String shortageTier = resolveCompensationShortageTier(state, true);
        String sourceProvinceName = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getSourceProvinceName();
        return Comparator
                .comparingInt((PlanningUnitDTO unit) -> tierShortagePriority(unit == null ? null : unit.getTier(), shortageTier))
                .thenComparingInt((PlanningUnitDTO unit) -> "保".equals(shortageTier)
                        ? localProtectUnitPriority(unit, sourceProvinceName) : 1)
                .thenComparing((PlanningUnitDTO unit) -> unit.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitDTO unit) -> unit.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitDTO unit) -> unit.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(PlanningUnitDTO::getUnitId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<CandidateItemDTO> buildProtectCandidateComparator(String sourceProvinceName) {
        return Comparator
                .comparingInt((CandidateItemDTO item) -> localProtectCandidatePriority(item, sourceProvinceName))
                .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getSchoolRank(), Comparator.nullsLast(Integer::compareTo))
                .thenComparing((CandidateItemDTO item) -> item.getRankInTier(), Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<PlanningUnitDTO> buildProtectUnitComparator(String sourceProvinceName) {
        return Comparator
                .comparingInt((PlanningUnitDTO unit) -> localProtectUnitPriority(unit, sourceProvinceName))
                .thenComparing((PlanningUnitDTO unit) -> unit.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitDTO unit) -> unit.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitDTO unit) -> unit.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(PlanningUnitDTO::getUnitId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<CandidateItemDTO> buildProbabilityGapCandidateComparator(double midpoint) {
        return Comparator
                .comparingDouble((CandidateItemDTO item) -> Math.abs(defaultDouble(item == null ? null : item.getAdmissionRatio()) - midpoint))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getSchoolRank(), Comparator.nullsLast(Integer::compareTo))
                .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<PlanningUnitDTO> buildProbabilityGapUnitCandidateComparator(double midpoint) {
        return Comparator
                .comparingDouble((PlanningUnitDTO unit) -> Math.abs(defaultDouble(unit == null ? null : unit.getAdmissionRatio()) - midpoint))
                .thenComparing((PlanningUnitDTO unit) -> unit.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitDTO unit) -> unit.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitDTO unit) -> unit.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(PlanningUnitDTO::getUnitId, Comparator.nullsLast(String::compareTo));
    }

    static List<String> orderStructuralReplacementCandidateVolunteerIds(List<String> removeVolunteerIds,
                                                                        List<String> candidateVolunteerIds,
                                                                        List<CandidateItemDTO> candidates) {
        return orderStructuralReplacementIds(removeVolunteerIds, candidateVolunteerIds, candidates, false);
    }

    static List<String> orderStructuralReplacementCandidateUnitIds(List<String> removeUnitIds,
                                                                   List<String> candidateUnitIds,
                                                                   List<CandidateItemDTO> candidates) {
        return orderStructuralReplacementIds(removeUnitIds, candidateUnitIds, candidates, true);
    }

    private static List<String> orderStructuralReplacementIds(List<String> removeIds,
                                                             List<String> candidateIds,
                                                             List<CandidateItemDTO> candidates,
                                                             boolean unitScope) {
        List<String> remainingCandidates = defaultList(candidateIds).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toCollection(Lists::newArrayList));
        List<String> orderedCandidates = Lists.newArrayList();
        for (String removeId : defaultList(removeIds)) {
            if (remainingCandidates.isEmpty()) {
                break;
            }
            CandidateItemDTO source = unitScope
                    ? representativeCandidateForUnit(candidates, removeId)
                    : findCandidate(candidates, removeId);
            String bestCandidateId = remainingCandidates.stream()
                    .min(buildStructuralReplacementIdComparator(source, candidates, unitScope))
                    .orElse(null);
            if (!Strings.isNullOrEmpty(bestCandidateId)) {
                orderedCandidates.add(bestCandidateId);
                remainingCandidates.remove(bestCandidateId);
            }
        }
        orderedCandidates.addAll(remainingCandidates);
        return orderedCandidates;
    }

    private static Comparator<String> buildStructuralReplacementIdComparator(CandidateItemDTO source,
                                                                            List<CandidateItemDTO> candidates,
                                                                            boolean unitScope) {
        return Comparator
                .comparingInt((String candidateId) -> RepairReplacementTradeoffSupport.majorSimilarityLevel(source, unitScope
                        ? representativeCandidateForUnit(candidates, candidateId) : findCandidate(candidates, candidateId)))
                .thenComparingInt(candidateId -> RepairReplacementTradeoffSupport.schoolRankDowngradePenalty(source, unitScope
                        ? representativeCandidateForUnit(candidates, candidateId) : findCandidate(candidates, candidateId)))
                .thenComparingDouble(candidateId -> RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getFinalScore(),
                        metricOf(candidates, candidateId, CandidateItemDTO::getFinalScore, unitScope)))
                .thenComparingDouble(candidateId -> RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getIntentScore(),
                        metricOf(candidates, candidateId, CandidateItemDTO::getIntentScore, unitScope)))
                .thenComparing(candidateId -> metricOf(candidates, candidateId, CandidateItemDTO::getFinalScore, unitScope),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(candidateId -> metricOf(candidates, candidateId, CandidateItemDTO::getAdmissionRatio, unitScope),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(candidateId -> metricOf(candidates, candidateId, CandidateItemDTO::getIntentScore, unitScope),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(candidateId -> bestRankOf(candidates, candidateId, unitScope), Comparator.nullsLast(Integer::compareTo))
                .thenComparing(candidateId -> candidateId, Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<CandidateItemDTO> buildRiskReplacementCandidateComparator(CandidateItemDTO source) {
        return Comparator
                .comparingInt((CandidateItemDTO candidate) -> RepairReplacementTradeoffSupport.majorSimilarityLevel(source, candidate))
                .thenComparingInt(candidate -> RepairReplacementTradeoffSupport.schoolRankDowngradePenalty(source, candidate))
                .thenComparing((CandidateItemDTO candidate) -> candidate.getFinalScore() == null ? 0D : candidate.getFinalScore(),
                        Comparator.reverseOrder())
                .thenComparing(candidate -> candidate.getAdmissionRatio() == null ? -1D : candidate.getAdmissionRatio(),
                        Comparator.reverseOrder())
                .thenComparing(candidate -> candidate.getIntentScore() == null ? 0D : candidate.getIntentScore(),
                        Comparator.reverseOrder());
    }

    private static boolean isRiskReplacementQualityAcceptable(CandidateItemDTO source, CandidateItemDTO candidate) {
        if (source == null || candidate == null) {
            return false;
        }
        if (RepairReplacementTradeoffSupport.majorSimilarityLevel(source, candidate) > 2) {
            return false;
        }
        return !hasSevereSchoolRankDowngrade(source, candidate);
    }

    private static boolean hasSevereSchoolRankDowngrade(CandidateItemDTO source, CandidateItemDTO candidate) {
        Integer sourceRank = source == null ? null : source.getSchoolRank();
        Integer candidateRank = candidate == null ? null : candidate.getSchoolRank();
        if (sourceRank == null || sourceRank <= 0 || candidateRank == null || candidateRank <= 0) {
            return false;
        }
        int downgrade = candidateRank - sourceRank;
        int tolerance = Math.max(120, sourceRank);
        return downgrade > tolerance;
    }

    private static boolean sameTierValue(String left, String right) {
        if (Strings.isNullOrEmpty(left) || Strings.isNullOrEmpty(right)) {
            return false;
        }
        return left.equals(right);
    }

    static boolean isCompensationSafeCandidate(CandidateItemDTO item) {
        if (item == null) {
            return false;
        }
        if (item.getTuitionPerYear() != null && item.getTuitionPerYear() > 20000) {
            return false;
        }
        if (containsAny(item.getSchoolName(), "中外合作") || containsAny(item.getMajorName(), "中外合作")) {
            return false;
        }
        if (defaultList(item.getReasonCodes()).stream().anyMatch(tag -> containsAny(tag, "中外合作", "专项", "公费", "定向", "强基", "高校专项", "地方专项"))) {
            return false;
        }
        if (defaultList(item.getMustSubjects()).stream().anyMatch(tag -> containsAny(tag, "单科", "语种", "性别"))) {
            return false;
        }
        return defaultList(item.getRiskFlags()).stream().noneMatch(RepairCandidateSelector::isBlockingRiskFlag);
    }

    static boolean isBlockingRiskFlag(String tag) {
        if (Strings.isNullOrEmpty(tag)) {
            return false;
        }
        String normalized = tag.trim().toLowerCase();
        int separatorIndex = normalized.indexOf(':');
        String key = separatorIndex >= 0 ? normalized.substring(0, separatorIndex).trim() : normalized;
        String value = separatorIndex >= 0 ? normalized.substring(separatorIndex + 1).trim() : "";
        if (key.endsWith("_score")
                || key.endsWith("_index")
                || key.endsWith("_ratio")
                || key.endsWith("_remark")
                || "city_level".equals(key)
                || "level_score".equals(key)
                || "volunteer_score".equals(key)) {
            return false;
        }
        if ("risk".equals(key) || "risk_flag".equals(key) || "risk_flags".equals(key)) {
            return containsAny(value, "special", "foreign", "limited", "limit", "中外合作");
        }
        return "special".equals(key)
                || "foreign".equals(key)
                || "limited".equals(key)
                || "limit".equals(key)
                || key.startsWith("special_limit")
                || key.startsWith("foreign_")
                || key.startsWith("limited_")
                || key.startsWith("limit_")
                || containsAny(tag, "中外合作");
    }

    static boolean isCurrentPlanAtOrAboveTargetCount(PlanningStateDTO state) {
        Integer requiredCount = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        if (requiredCount == null || requiredCount <= 0) {
            return false;
        }
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        int currentCount = majorGroupMode ? currentOrderedOrDraftUnitCount(state) : currentOrderedOrDraftItemCount(state);
        return currentCount >= requiredCount;
    }

    private static boolean containsAny(String text, String... keywords) {
        if (Strings.isNullOrEmpty(text)) {
            return false;
        }
        for (String keyword : keywords) {
            if (containsIgnoreCase(text, keyword)) {
                return true;
            }
        }
        return false;
    }

    private static String resolveCompensationShortageTier(PlanningStateDTO state, boolean majorGroupMode) {
        if (state == null || state.getCandidatePoolState() == null
                || state.getCandidatePoolState().getRequiredTierCounts() == null
                || state.getCandidatePoolState().getRequiredTierCounts().isEmpty()) {
            return null;
        }
        String shortageTier = null;
        int maxDeficit = 0;
        for (String tier : Lists.newArrayList("保", "稳", "冲")) {
            int target = positiveCount(state.getCandidatePoolState().getRequiredTierCounts().get(tier));
            int current = majorGroupMode
                    ? currentOrderedOrDraftUnitTierCount(state, tier)
                    : currentOrderedOrDraftTierCount(state, tier);
            int deficit = target - current;
            if (deficit > maxDeficit) {
                maxDeficit = deficit;
                shortageTier = tier;
            }
        }
        return shortageTier;
    }

    private static int tierShortagePriority(String tier, String shortageTier) {
        if (Strings.isNullOrEmpty(shortageTier)) {
            return 1;
        }
        return shortageTier.equals(tier) ? 0 : 1;
    }

    private static int resolveCompensationTierTargetCount(PlanningStateDTO state, String tier, int total) {
        Integer expected = state == null ? null : expectedTierCount(state.getCandidatePoolState(), tier);
        if (expected != null && expected > 0) {
            return expected;
        }
        if ("保".equals(tier)) {
            return Math.max(1, (int) Math.ceil(total * 0.2D));
        }
        return 0;
    }

    private static Integer expectedTierCount(CandidatePoolStateDTO candidatePoolState, String tier) {
        if (candidatePoolState == null || candidatePoolState.getRequiredTierCounts() == null) {
            return null;
        }
        Integer count = candidatePoolState.getRequiredTierCounts().get(tier);
        return count == null || count <= 0 ? null : count;
    }

    private static int localProtectCandidatePriority(CandidateItemDTO item, String sourceProvinceName) {
        if (item == null || Strings.isNullOrEmpty(sourceProvinceName)) {
            return 1;
        }
        return containsIgnoreCase(item.getProvinceName(), sourceProvinceName) ? 0 : 1;
    }

    private static int localProtectUnitPriority(PlanningUnitDTO unit, String sourceProvinceName) {
        if (unit == null || Strings.isNullOrEmpty(sourceProvinceName)) {
            return 1;
        }
        return containsIgnoreCase(unit.getProvinceName(), sourceProvinceName) ? 0 : 1;
    }

    private static boolean containsIgnoreCase(String text, String keyword) {
        if (Strings.isNullOrEmpty(text) || Strings.isNullOrEmpty(keyword)) {
            return false;
        }
        return text.toLowerCase().contains(keyword.toLowerCase());
    }

    private static void addSelectedUnits(Selection selection, List<PlanningUnitDTO> selectedUnits) {
        for (PlanningUnitDTO unit : defaultPlanningUnits(selectedUnits)) {
            if (unit == null) {
                continue;
            }
            if (!Strings.isNullOrEmpty(unit.getUnitId())) {
                selection.candidateUnitIds.add(unit.getUnitId());
            }
            selection.candidateVolunteerIds.addAll(defaultPlanningUnitMajors(unit.getSelectedMajors()).stream()
                    .map(PlanningUnitMajorDTO::getVolunteerId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList()));
        }
    }

    private static void applySelectionDiagnostics(PlanningStateDTO state,
                                                  Selection selection,
                                                  int requiredCount,
                                                  String targetTier,
                                                  int selectedCount,
                                                  int availableCount,
                                                  int availableCountWithoutHardConstraints) {
        if (selection == null) {
            return;
        }
        selection.requiredCount = requiredCount > 0 ? requiredCount : null;
        selection.selectedCount = selectedCount;
        selection.shortageCount = requiredCount > selectedCount ? requiredCount - selectedCount : null;
        selection.availableCount = availableCount;
        selection.availableCountWithoutHardConstraints = availableCountWithoutHardConstraints;
        selection.targetTier = targetTier;
        selection.shortageCausedByConfirmedHardConstraints =
                selection.shortageCount != null
                        && selection.shortageCount > 0
                        && RepairCandidateEligibility.hasConfirmedHardConstraints(state)
                        && availableCount < requiredCount
                        && availableCountWithoutHardConstraints >= requiredCount;
    }

    private static List<String> filterOrderedVolunteerIdsByUnitIds(PlanningStateDTO state,
                                                                   List<CandidateItemDTO> candidates,
                                                                   List<String> unitIds) {
        Set<String> unitIdSet = new LinkedHashSet<String>(defaultList(unitIds));
        return defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).stream()
                .filter(item -> unitIdSet.contains(resolveUnitId(item.getVolunteerId(), candidates)))
                .map(OrderedItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
    }

    private static List<String> filterDraftVolunteerIdsByUnitIds(PlanningStateDTO state,
                                                                 List<CandidateItemDTO> candidates,
                                                                 List<String> unitIds) {
        Set<String> unitIdSet = new LinkedHashSet<String>(defaultList(unitIds));
        return defaultDraftItems(state == null || state.getDraftPlanState() == null
                ? null : state.getDraftPlanState().getItems()).stream()
                .filter(item -> unitIdSet.contains(resolveUnitId(item.getVolunteerId(), candidates)))
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
    }

    static List<String> filterVolunteerIdsByUnitIds(List<String> volunteerIds,
                                                    List<CandidateItemDTO> candidates,
                                                    List<String> unitIds) {
        Set<String> unitIdSet = new LinkedHashSet<String>(defaultList(unitIds));
        return defaultList(volunteerIds).stream()
                .filter(volunteerId -> unitIdSet.contains(resolveUnitId(volunteerId, candidates)))
                .collect(Collectors.toList());
    }

    static String firstVolunteerIdForUnit(List<String> volunteerIds,
                                          List<CandidateItemDTO> candidates,
                                          String unitId) {
        return defaultList(volunteerIds).stream()
                .filter(volunteerId -> unitId.equals(resolveUnitId(volunteerId, candidates)))
                .findFirst()
                .orElse(null);
    }

    static List<String> resolveUnitIdsFromVolunteerIds(List<String> volunteerIds,
                                                       List<CandidateItemDTO> candidates) {
        return defaultList(volunteerIds).stream()
                .map(volunteerId -> resolveUnitId(volunteerId, candidates))
                .filter(id -> !Strings.isNullOrEmpty(id))
                .distinct()
                .collect(Collectors.toList());
    }

    static String resolveCandidateTier(List<String> volunteerIds, List<CandidateItemDTO> candidates) {
        for (String volunteerId : defaultList(volunteerIds)) {
            CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getTier())) {
                return candidate.getTier();
            }
        }
        return null;
    }

    static String resolveUnitId(String volunteerId, List<CandidateItemDTO> candidates) {
        CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
        if (candidate != null) {
            return resolveInitialRecommendationUnitId(candidate);
        }
        return null;
    }

    static String resolveInitialRecommendationUnitId(CandidateItemDTO item) {
        if (item == null) {
            return null;
        }
        if (!Strings.isNullOrEmpty(item.getPlanSchoolDataId())) {
            return item.getPlanSchoolDataId();
        }
        if (!Strings.isNullOrEmpty(item.getSchoolId())) {
            return item.getSchoolId();
        }
        return item.getSchoolName();
    }

    static CandidateItemDTO findCandidate(List<CandidateItemDTO> items, String volunteerId) {
        return new CandidateLookup(items).resolve(volunteerId);
    }

    private static Double admissionRatioOf(List<CandidateItemDTO> candidates, String volunteerId) {
        CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
        return candidate == null ? null : candidate.getAdmissionRatio();
    }

    private static Double finalScoreOf(List<CandidateItemDTO> candidates, String volunteerId) {
        CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
        return candidate == null ? null : candidate.getFinalScore();
    }

    private static Double intentScoreOf(List<CandidateItemDTO> candidates, String volunteerId) {
        CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
        return candidate == null ? null : candidate.getIntentScore();
    }

    private static double defaultDouble(Double value) {
        return value == null ? 0D : value;
    }

    private static double probabilityGapAffectedMidpoint(List<CandidateItemDTO> candidates, Set<String> affectedIds) {
        List<Double> ratios = defaultList(Lists.newArrayList(affectedIds)).stream()
                .map(volunteerId -> admissionRatioOf(candidates, volunteerId))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        if (ratios.isEmpty()) {
            return 0D;
        }
        return (ratios.stream().min(Double::compareTo).orElse(0D)
                + ratios.stream().max(Double::compareTo).orElse(0D)) / 2D;
    }

    private static double probabilityGapAffectedUnitMidpoint(PlanningStateDTO state, Set<String> affectedUnitIds) {
        List<Double> ratios = defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits()).stream()
                .filter(unit -> affectedUnitIds.contains(unit.getUnitId()))
                .map(OrderedUnitDTO::getAdmissionRatio)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        if (ratios.isEmpty()) {
            List<CandidateItemDTO> candidates = defaultCandidates(state == null || state.getCandidatePoolState() == null
                    ? null : state.getCandidatePoolState().getItems());
            ratios = defaultDraftUnits(state == null || state.getDraftPlanState() == null
                    ? null : state.getDraftPlanState().getUnits()).stream()
                    .filter(unit -> affectedUnitIds.contains(unit.getUnitId()))
                    .map(unit -> averageAdmissionRatio(defaultPlanningUnitMajors(unit.getMajorItems()), candidates))
                    .filter(Objects::nonNull)
                    .collect(Collectors.toList());
        }
        if (ratios.isEmpty()) {
            return 0D;
        }
        return (ratios.stream().min(Double::compareTo).orElse(0D)
                + ratios.stream().max(Double::compareTo).orElse(0D)) / 2D;
    }

    private static Double averageAdmissionRatio(List<PlanningUnitMajorDTO> majors, List<CandidateItemDTO> candidates) {
        List<Double> ratios = defaultPlanningUnitMajors(majors).stream()
                .map(PlanningUnitMajorDTO::getVolunteerId)
                .map(volunteerId -> admissionRatioOf(candidates, volunteerId))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        if (ratios.isEmpty()) {
            return null;
        }
        return ratios.stream().mapToDouble(Double::doubleValue).average().orElse(0D);
    }

    private static Double averageMajorMetric(List<PlanningUnitMajorDTO> majors,
                                             List<CandidateItemDTO> candidates,
                                             Function<CandidateItemDTO, Double> metricGetter) {
        List<Double> values = defaultPlanningUnitMajors(majors).stream()
                .map(PlanningUnitMajorDTO::getVolunteerId)
                .map(volunteerId -> metricOfCandidate(candidates, volunteerId, metricGetter))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        if (values.isEmpty()) {
            return null;
        }
        return values.stream().mapToDouble(Double::doubleValue).average().orElse(0D);
    }

    private static Double averageUnitMetric(List<CandidateItemDTO> candidates,
                                            String unitId,
                                            Function<CandidateItemDTO, Double> metricGetter) {
        List<Double> values = defaultCandidates(candidates).stream()
                .filter(candidate -> unitIdMatches(candidate, unitId))
                .map(metricGetter)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        if (values.isEmpty()) {
            return null;
        }
        return values.stream().mapToDouble(Double::doubleValue).average().orElse(0D);
    }

    private static Double metricOf(List<CandidateItemDTO> candidates,
                                   String id,
                                   Function<CandidateItemDTO, Double> metricGetter,
                                   boolean unitScope) {
        return unitScope ? averageUnitMetric(candidates, id, metricGetter) : metricOfCandidate(candidates, id, metricGetter);
    }

    private static Double metricOfCandidate(List<CandidateItemDTO> candidates,
                                            String volunteerId,
                                            Function<CandidateItemDTO, Double> metricGetter) {
        CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
        return candidate == null ? null : metricGetter.apply(candidate);
    }

    private static Integer schoolRankOf(List<CandidateItemDTO> candidates, String volunteerId) {
        CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
        return candidate == null ? null : candidate.getSchoolRank();
    }

    private static Integer bestMajorSchoolRank(List<PlanningUnitMajorDTO> majors, List<CandidateItemDTO> candidates) {
        return defaultPlanningUnitMajors(majors).stream()
                .map(PlanningUnitMajorDTO::getVolunteerId)
                .map(volunteerId -> schoolRankOf(candidates, volunteerId))
                .filter(rank -> rank != null && rank > 0)
                .min(Integer::compareTo)
                .orElse(null);
    }

    private static Integer bestUnitSchoolRank(List<CandidateItemDTO> candidates, String unitId) {
        return defaultCandidates(candidates).stream()
                .filter(candidate -> unitIdMatches(candidate, unitId))
                .map(CandidateItemDTO::getSchoolRank)
                .filter(rank -> rank != null && rank > 0)
                .min(Integer::compareTo)
                .orElse(null);
    }

    private static Integer bestRankOf(List<CandidateItemDTO> candidates, String id, boolean unitScope) {
        return unitScope ? bestUnitSchoolRank(candidates, id) : schoolRankOf(candidates, id);
    }

    private static CandidateItemDTO representativeCandidateForUnit(List<CandidateItemDTO> candidates, String unitId) {
        return defaultCandidates(candidates).stream()
                .filter(candidate -> unitIdMatches(candidate, unitId))
                .sorted(Comparator
                        .comparing((CandidateItemDTO candidate) -> candidate.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(candidate -> candidate.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(candidate -> candidate.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo)))
                .findFirst()
                .orElse(null);
    }

    private static boolean unitIdMatches(CandidateItemDTO candidate, String unitId) {
        return candidate != null && !Strings.isNullOrEmpty(unitId)
                && unitId.equals(resolveInitialRecommendationUnitId(candidate));
    }

    private static int positiveCount(Integer value) {
        return value == null || value <= 0 ? 0 : value;
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<CandidateItemDTO> defaultCandidates(List<CandidateItemDTO> candidates) {
        return candidates == null ? Lists.newArrayList() : candidates;
    }

    private static List<DraftItemDTO> defaultDraftItems(List<DraftItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private static List<OrderedItemDTO> defaultOrderedItems(List<OrderedItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private static List<OrderedUnitDTO> defaultOrderedUnits(List<OrderedUnitDTO> units) {
        return units == null ? Lists.newArrayList() : units;
    }

    private static List<DraftUnitDTO> defaultDraftUnits(List<DraftUnitDTO> units) {
        return units == null ? Lists.newArrayList() : units;
    }

    private static List<PlanningUnitMajorDTO> defaultPlanningUnitMajors(List<PlanningUnitMajorDTO> majors) {
        return majors == null ? Lists.newArrayList() : majors;
    }

    private static List<PlanningUnitDTO> defaultPlanningUnits(List<PlanningUnitDTO> units) {
        return units == null ? Lists.newArrayList() : units;
    }

    static final class Selection {
        private String removeTier;
        private String targetTier;
        private Double rangeMin;
        private Double rangeMax;
        private Integer requiredCount;
        private Integer selectedCount;
        private Integer shortageCount;
        private Integer availableCount;
        private Integer availableCountWithoutHardConstraints;
        private Boolean shortageCausedByConfirmedHardConstraints;
        private final List<String> candidateUnitIds = Lists.newArrayList();
        private final List<String> candidateVolunteerIds = Lists.newArrayList();
        private final List<String> removeUnitIds = Lists.newArrayList();
        private final List<String> removeVolunteerIds = Lists.newArrayList();

        String getRemoveTier() {
            return removeTier;
        }

        List<String> getRemoveUnitIds() {
            return removeUnitIds;
        }

        List<String> getRemoveVolunteerIds() {
            return removeVolunteerIds;
        }

        List<String> getCandidateUnitIds() {
            return candidateUnitIds;
        }

        List<String> getCandidateVolunteerIds() {
            return candidateVolunteerIds;
        }

        Double getRangeMin() {
            return rangeMin;
        }

        Double getRangeMax() {
            return rangeMax;
        }

        String getTargetTier() {
            return targetTier;
        }

        Integer getRequiredCount() {
            return requiredCount;
        }

        Integer getSelectedCount() {
            return selectedCount;
        }

        Integer getShortageCount() {
            return shortageCount;
        }

        Integer getAvailableCount() {
            return availableCount;
        }

        Integer getAvailableCountWithoutHardConstraints() {
            return availableCountWithoutHardConstraints;
        }

        Boolean getShortageCausedByConfirmedHardConstraints() {
            return shortageCausedByConfirmedHardConstraints;
        }
    }

    static final class RiskReplacementSelection {
        private final List<RiskReplacementPair> pairs = Lists.newArrayList();
        private int missingSourceCount;
        private int noReplacementCount;

        List<RiskReplacementPair> getPairs() {
            return pairs;
        }

        int getMissingSourceCount() {
            return missingSourceCount;
        }

        int getNoReplacementCount() {
            return noReplacementCount;
        }
    }

    static final class RiskReplacementPair {
        private final CandidateItemDTO source;
        private final CandidateItemDTO replacement;

        RiskReplacementPair(CandidateItemDTO source, CandidateItemDTO replacement) {
            this.source = source;
            this.replacement = replacement;
        }

        CandidateItemDTO getSource() {
            return source;
        }

        CandidateItemDTO getReplacement() {
            return replacement;
        }
    }

    private static final class CandidateLookup {
        private final Map<String, CandidateItemDTO> byVolunteerId = new LinkedHashMap<String, CandidateItemDTO>();
        private final Map<String, CandidateItemDTO> byLegacyVolunteerPrefix = new LinkedHashMap<String, CandidateItemDTO>();
        private final Set<String> duplicatedLegacyVolunteerPrefixes = new HashSet<String>();

        private CandidateLookup(List<CandidateItemDTO> candidates) {
            for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
                if (candidate == null) {
                    continue;
                }
                putUnique(byVolunteerId, null, candidate.getVolunteerId(), candidate);
                putUnique(byLegacyVolunteerPrefix, duplicatedLegacyVolunteerPrefixes,
                        legacyVolunteerPrefix(candidate.getVolunteerId()), candidate);
            }
        }

        private CandidateItemDTO resolve(String volunteerId) {
            if (Strings.isNullOrEmpty(volunteerId)) {
                return null;
            }
            CandidateItemDTO candidate = byVolunteerId.get(volunteerId);
            if (candidate != null) {
                return candidate;
            }
            String legacyPrefix = legacyVolunteerPrefix(volunteerId);
            if (!Strings.isNullOrEmpty(legacyPrefix) && !duplicatedLegacyVolunteerPrefixes.contains(legacyPrefix)) {
                return byLegacyVolunteerPrefix.get(legacyPrefix);
            }
            return null;
        }

        private static void putUnique(Map<String, CandidateItemDTO> target,
                                      Set<String> duplicates,
                                      String key,
                                      CandidateItemDTO candidate) {
            if (Strings.isNullOrEmpty(key)) {
                return;
            }
            if (target.containsKey(key)) {
                if (duplicates != null) {
                    duplicates.add(key);
                }
                return;
            }
            target.put(key, candidate);
        }

        private static String legacyVolunteerPrefix(String volunteerId) {
            if (Strings.isNullOrEmpty(volunteerId)) {
                return null;
            }
            String[] parts = volunteerId.split("_", -1);
            if (parts.length < 2 || Strings.isNullOrEmpty(parts[0]) || Strings.isNullOrEmpty(parts[1])) {
                return null;
            }
            return parts[0] + "_" + parts[1];
        }
    }
}
