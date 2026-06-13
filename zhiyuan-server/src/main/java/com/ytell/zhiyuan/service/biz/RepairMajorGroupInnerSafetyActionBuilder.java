package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

final class RepairMajorGroupInnerSafetyActionBuilder {

    private RepairMajorGroupInnerSafetyActionBuilder() {
    }

    static void populateActions(PlanningStateDTO state,
                                ReviewCheckDTO check,
                                FixProposalDTO proposal) {
        if (proposal == null
                || !RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(
                RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy()))) {
            return;
        }
        if (state == null || state.getCandidatePoolState() == null
                || !"majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel())) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "当前不是专业组模式，不能执行组内安全垫修复。",
                    "volunteer_model_mismatch");
            return;
        }
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        Map<String, List<CandidateItemDTO>> candidatesByUnit = groupCandidatesByUnit(candidates);
        Set<String> selectedIds = defaultDraftItems(state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> bannedIds = new LinkedHashSet<String>(defaultList(state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getBannedVolunteerIds()));
        Map<String, List<DraftItemDTO>> selectedByUnit = defaultDraftItems(state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems()).stream()
                .collect(Collectors.groupingBy(item -> resolveWorkingPlanUnitId(item, candidates),
                        LinkedHashMap::new, Collectors.toList()));

        Set<String> targetUnitIds = resolveTargetUnitIds(check, candidates);
        if (targetUnitIds.isEmpty()) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "当前风险缺少可定位的专业组。",
                    "risk_unit_unresolved");
            return;
        }

        int unresolvedCount = 0;
        Integer requiredMajorCount = state.getCandidatePoolState().getRequiredMajorCount();
        for (String unitId : targetUnitIds) {
            List<DraftItemDTO> selectedItems = selectedByUnit.get(unitId);
            List<CandidateItemDTO> unitCandidates = candidatesByUnit.get(unitId);
            CandidateItemDTO safetyCandidate = findSafetyCandidate(unitCandidates, selectedIds, bannedIds, state);
            if (selectedItems == null || selectedItems.isEmpty() || safetyCandidate == null) {
                unresolvedCount++;
                continue;
            }
            DraftItemDTO removeItem = null;
            int selectedCount = selectedItems.size();
            if (requiredMajorCount != null && requiredMajorCount > 0 && selectedCount >= requiredMajorCount) {
                removeItem = selectReplacementSource(selectedItems, candidates);
                if (removeItem == null) {
                    unresolvedCount++;
                    continue;
                }
            }
            proposal.getActions().add(buildAction(unitId, selectedItems, removeItem, safetyCandidate));
        }
        if (proposal.getActions().isEmpty()) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "这些专业组暂时没有可补入的组内安全垫专业。",
                    "major_group_safety_candidate_insufficient");
        } else if (unresolvedCount > 0) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "只有部分专业组找到了安全垫专业，暂不自动应用。",
                    "partial_major_group_safety_candidate_missing");
            proposal.getDryRunResult().getWarnings().add(String.format("仍有 %d 个专业组缺少可执行的组内安全垫修复。", unresolvedCount));
        }
    }

    private static Set<String> resolveTargetUnitIds(ReviewCheckDTO check,
                                                    List<CandidateItemDTO> candidates) {
        Set<String> unitIds = defaultList(check == null ? null : check.getAffectedUnitIds()).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (!unitIds.isEmpty()) {
            return unitIds;
        }
        for (String volunteerId : defaultList(check == null ? null : check.getAffectedVolunteerIds())) {
            CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, volunteerId);
            String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            if (!Strings.isNullOrEmpty(unitId)) {
                unitIds.add(unitId);
            }
        }
        return unitIds;
    }

    private static CandidateItemDTO findSafetyCandidate(List<CandidateItemDTO> unitCandidates,
                                                        Set<String> selectedIds,
                                                        Set<String> bannedIds,
                                                        PlanningStateDTO state) {
        return defaultCandidates(unitCandidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> !bannedIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> candidate.getAdmissionRatio() != null
                        && candidate.getSchoolEnrollRatio() != null
                        && isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio()))
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .sorted(buildSelectedMajorDisplayComparator())
                .findFirst()
                .orElse(null);
    }

    private static DraftItemDTO selectReplacementSource(List<DraftItemDTO> selectedItems,
                                                        List<CandidateItemDTO> candidates) {
        return defaultDraftItems(selectedItems).stream()
                .filter(item -> item != null && !Boolean.TRUE.equals(item.getLocked()))
                .filter(item -> {
                    CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, item.getVolunteerId());
                    return candidate == null
                            || candidate.getAdmissionRatio() == null
                            || candidate.getSchoolEnrollRatio() == null
                            || !isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio());
                })
                .sorted(Comparator
                        .comparing((DraftItemDTO item) -> {
                            CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, item.getVolunteerId());
                            return candidate == null ? 0D : candidate.getIntentScore();
                        }, Comparator.nullsFirst(Double::compareTo))
                        .thenComparing(item -> {
                            CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, item.getVolunteerId());
                            return candidate == null ? 0D : candidate.getFinalScore();
                        }, Comparator.nullsFirst(Double::compareTo))
                        .thenComparing(DraftItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo)))
                .findFirst()
                .orElse(null);
    }

    private static FixProposalActionDTO buildAction(String unitId,
                                                    List<DraftItemDTO> selectedItems,
                                                    DraftItemDTO removeItem,
                                                    CandidateItemDTO safetyCandidate) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY);
        action.setLevel("warn");
        action.setSourceCheckCode("group_inner_safety_guard");
        action.setSummary("补入组内安全垫专业");
        String schoolName = safetyCandidate.getSchoolName();
        if (Strings.isNullOrEmpty(schoolName) && selectedItems != null && !selectedItems.isEmpty()) {
            schoolName = selectedItems.get(0).getSchoolName();
        }
        action.setDetail(String.format("建议为 %s 补入组内安全垫专业 %s。",
                Strings.nullToEmpty(schoolName), Strings.nullToEmpty(safetyCandidate.getMajorName())));
        action.setUnitIds(Lists.newArrayList(unitId));
        action.setCandidateVolunteerIds(Lists.newArrayList(safetyCandidate.getVolunteerId()));
        action.setVolunteerIds(Lists.newArrayList(safetyCandidate.getVolunteerId()));
        if (removeItem != null) {
            action.setSummary("替换组内安全垫专业");
            action.setDetail(String.format("建议在 %s 内用 %s 替换 %s，补足组内安全垫。",
                    Strings.nullToEmpty(schoolName),
                    Strings.nullToEmpty(safetyCandidate.getMajorName()),
                    Strings.nullToEmpty(removeItem.getMajorName())));
            action.setRemoveVolunteerIds(Lists.newArrayList(removeItem.getVolunteerId()));
            ReplacementPairDTO pair = new ReplacementPairDTO();
            pair.setFromUnitId(unitId);
            pair.setFromVolunteerId(removeItem.getVolunteerId());
            pair.setToUnitId(unitId);
            pair.setToVolunteerId(safetyCandidate.getVolunteerId());
            pair.setReasonCodes(Lists.newArrayList("group_inner_safety_guard", "same_unit_safety_major"));
            action.getReplacementPairs().add(pair);
        }
        return action;
    }

    private static Map<String, List<CandidateItemDTO>> groupCandidatesByUnit(List<CandidateItemDTO> candidates) {
        Map<String, List<CandidateItemDTO>> grouped = new LinkedHashMap<String, List<CandidateItemDTO>>();
        for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
            String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            if (Strings.isNullOrEmpty(unitId)) {
                unitId = Strings.isNullOrEmpty(candidate.getVolunteerId()) ? String.valueOf(grouped.size()) : candidate.getVolunteerId();
            }
            grouped.computeIfAbsent(unitId, key -> Lists.newArrayList()).add(candidate);
        }
        return grouped;
    }

    private static String resolveWorkingPlanUnitId(DraftItemDTO item, List<CandidateItemDTO> candidates) {
        if (item == null) {
            return null;
        }
        CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, item.getVolunteerId());
        String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
        if (!Strings.isNullOrEmpty(unitId)) {
            return unitId;
        }
        if (!Strings.isNullOrEmpty(item.getVolunteerId())) {
            int index = item.getVolunteerId().indexOf('_');
            if (index > 0) {
                return item.getVolunteerId().substring(0, index);
            }
            return item.getVolunteerId();
        }
        return item.getSchoolName();
    }

    private static Comparator<CandidateItemDTO> buildSelectedMajorDisplayComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Double::compareTo))
                .thenComparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static boolean isSafetyMajorRatio(Double majorAdmissionRatio, Double unitEnrollRatio) {
        return majorAdmissionRatio != null
                && unitEnrollRatio != null
                && majorAdmissionRatio >= unitEnrollRatio;
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
}
