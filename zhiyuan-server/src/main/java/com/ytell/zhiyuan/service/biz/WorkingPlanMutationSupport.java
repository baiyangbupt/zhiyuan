package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;

import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

final class WorkingPlanMutationSupport {

    private WorkingPlanMutationSupport() {
    }

    static boolean containsWorkingPlanItem(DraftPlanStateDTO draft, String volunteerId) {
        return defaultDraftItems(draft == null ? null : draft.getItems()).stream()
                .anyMatch(item -> sameVolunteerIdentity(volunteerId, item.getVolunteerId()));
    }

    static boolean containsVolunteerId(List<String> volunteerIds, String volunteerId) {
        return defaultList(volunteerIds).stream()
                .anyMatch(item -> sameVolunteerIdentity(volunteerId, item));
    }

    static CandidateItemDTO findCandidate(List<CandidateItemDTO> candidates, String volunteerId) {
        if (Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        CandidateIndex index = new CandidateIndex(candidates);
        return index.resolve(volunteerId);
    }

    static DraftItemDTO buildWorkingPlanItem(CandidateItemDTO candidate, String source) {
        return buildWorkingPlanItem(candidate, source, false);
    }

    static DraftItemDTO buildWorkingPlanItem(CandidateItemDTO candidate, String source, boolean locked) {
        if (candidate == null) {
            return null;
        }
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(candidate.getVolunteerId());
        item.setTier(candidate.getTier());
        item.setSchoolName(candidate.getSchoolName());
        item.setMajorName(candidate.getMajorName());
        item.setSource(source);
        item.setLocked(locked);
        return item;
    }

    static boolean addWorkingPlanItemIfAllowed(DraftPlanStateDTO draft, CandidateItemDTO candidate, String source) {
        return addWorkingPlanItemIfAllowed(draft, candidate, source, false);
    }

    static boolean addWorkingPlanItemIfAllowed(DraftPlanStateDTO draft,
                                               CandidateItemDTO candidate,
                                               String source,
                                               boolean locked) {
        if (draft == null || candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
            return false;
        }
        if (containsWorkingPlanItem(draft, candidate.getVolunteerId())
                || containsVolunteerId(draft.getBannedVolunteerIds(), candidate.getVolunteerId())) {
            return false;
        }
        DraftItemDTO item = buildWorkingPlanItem(candidate, source, locked);
        if (item == null) {
            return false;
        }
        draft.getItems().add(item);
        return true;
    }

    static void syncWorkingPlanUnitsWithItems(DraftPlanStateDTO draft,
                                              List<CandidateItemDTO> candidates,
                                              CandidatePoolStateDTO candidatePoolState) {
        if (draft == null) {
            return;
        }
        if (!isMajorGroupMode(candidatePoolState)) {
            draft.setUnits(Lists.newArrayList());
            return;
        }
        Map<String, CandidateItemDTO> candidateMap = candidates == null
                ? new LinkedHashMap<String, CandidateItemDTO>()
                : candidates.stream()
                .filter(candidate -> !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate, (left, right) -> left, LinkedHashMap::new));
        Map<String, DraftUnitDTO> unitMap = new LinkedHashMap<String, DraftUnitDTO>();
        for (DraftItemDTO item : defaultDraftItems(draft.getItems())) {
            CandidateItemDTO candidate = candidateMap.get(item.getVolunteerId());
            String unitId = candidate == null ? resolveWorkingPlanUnitId(item) : RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            DraftUnitDTO unit = unitMap.computeIfAbsent(unitId, key -> {
                DraftUnitDTO dto = new DraftUnitDTO();
                dto.setUnitId(key);
                dto.setTier(candidate == null ? item.getTier() : candidate.getTier());
                dto.setSchoolName(candidate == null ? item.getSchoolName() : candidate.getSchoolName());
                dto.setSource(item.getSource());
                dto.setLocked(item.getLocked());
                return dto;
            });
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(item.getVolunteerId());
            major.setMajorName(item.getMajorName());
            major.setTier(item.getTier());
            major.setSelected(true);
            if (candidate != null) {
                major.setMajorId(candidate.getMajorId());
                major.setMajorCode(candidate.getMajorCode());
                major.setMajorCategoryId(candidate.getMajorCategoryId());
                major.setMajorSubCategoryId(candidate.getMajorSubCategoryId());
                // 分类名随候选带上 ✓：单元侧的专业筛选（`RepairCandidateEligibility`）要用 ✓。
                major.setMajorCategory(candidate.getMajorCategory());
                major.setMajorDiscipline(candidate.getMajorDiscipline());
                major.setAdmissionRatio(candidate.getAdmissionRatio());
                major.setFinalScore(candidate.getFinalScore());
                major.setIntentScore(candidate.getIntentScore());
                major.setPreferred(candidate.getPreferred());
                major.setSafetyMajor(isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio()));
                major.setTuitionPerYear(candidate.getTuitionPerYear());
                major.setRankInTier(candidate.getRankInTier());
            }
            unit.getMajorItems().add(major);
            unit.setLocked(Boolean.TRUE.equals(unit.getLocked()) || Boolean.TRUE.equals(item.getLocked()));
        }
        for (DraftUnitDTO unit : unitMap.values()) {
            unit.setMajorItems(sortSelectedMajorsForDisplay(unit.getMajorItems()));
        }
        draft.setUnits(Lists.newArrayList(unitMap.values()));
    }

    static void recalculateWorkingPlanSummary(DraftPlanStateDTO draft, CandidatePoolStateDTO candidatePoolState) {
        if (draft == null) {
            return;
        }
        boolean majorGroupMode = isMajorGroupMode(candidatePoolState);
        int unitTotal = countWorkingPlanSummaryTotal(draft.getItems(), majorGroupMode);
        int targetUnitCount = candidatePoolState != null && candidatePoolState.getRequiredCount() != null
                ? candidatePoolState.getRequiredCount() : 0;
        int sprintUnits = countWorkingPlanTier(draft.getItems(), "冲", majorGroupMode);
        int safeUnits = countWorkingPlanTier(draft.getItems(), "稳", majorGroupMode);
        int protectUnits = countWorkingPlanTier(draft.getItems(), "保", majorGroupMode);
        draft.getSummary().setUnitTotal(unitTotal);
        draft.getSummary().setTargetUnitCount(targetUnitCount);
        draft.getSummary().setTotal(unitTotal);
        draft.getSummary().setTargetCount(targetUnitCount);
        draft.getSummary().getUnitTierCounts().put("冲", sprintUnits);
        draft.getSummary().getUnitTierCounts().put("稳", safeUnits);
        draft.getSummary().getUnitTierCounts().put("保", protectUnits);
        draft.getSummary().getTierCounts().put("冲", sprintUnits);
        draft.getSummary().getTierCounts().put("稳", safeUnits);
        draft.getSummary().getTierCounts().put("保", protectUnits);
    }

    private static List<PlanningUnitMajorDTO> sortSelectedMajorsForDisplay(List<PlanningUnitMajorDTO> majors) {
        return defaultPlanningUnitMajors(majors).stream()
                .filter(Objects::nonNull)
                .sorted(buildSelectedMajorDisplayComparator())
                .collect(Collectors.toList());
    }

    private static Comparator<PlanningUnitMajorDTO> buildSelectedMajorDisplayComparator() {
        return Comparator
                .comparing((PlanningUnitMajorDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Double::compareTo))
                .thenComparing((PlanningUnitMajorDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitMajorDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(PlanningUnitMajorDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static int countWorkingPlanSummaryTotal(List<DraftItemDTO> items, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return items == null ? 0 : items.size();
        }
        return (int) defaultDraftItems(items).stream()
                .map(WorkingPlanMutationSupport::resolveWorkingPlanUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private static int countWorkingPlanTier(List<DraftItemDTO> items, String tier, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return (int) defaultDraftItems(items).stream().filter(item -> tier.equals(item.getTier())).count();
        }
        return (int) defaultDraftItems(items).stream()
                .filter(item -> tier.equals(item.getTier()))
                .map(WorkingPlanMutationSupport::resolveWorkingPlanUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private static boolean sameVolunteerIdentity(String left, String right) {
        if (Strings.isNullOrEmpty(left) || Strings.isNullOrEmpty(right)) {
            return false;
        }
        if (left.equals(right)) {
            return true;
        }
        String leftLegacyPrefix = legacyVolunteerPrefix(left);
        String rightLegacyPrefix = legacyVolunteerPrefix(right);
        return !Strings.isNullOrEmpty(leftLegacyPrefix)
                && leftLegacyPrefix.equals(rightLegacyPrefix);
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

    private static String resolveWorkingPlanUnitId(DraftItemDTO item) {
        if (item == null) {
            return null;
        }
        return resolveWorkingPlanUnitId(item.getVolunteerId(), item.getSchoolName());
    }

    private static String resolveWorkingPlanUnitId(String volunteerId, String schoolName) {
        if (!Strings.isNullOrEmpty(volunteerId)) {
            int index = volunteerId.indexOf('_');
            if (index > 0) {
                return volunteerId.substring(0, index);
            }
            return volunteerId;
        }
        return schoolName;
    }

    private static class CandidateIndex {
        private final Map<String, CandidateItemDTO> byVolunteerId = new LinkedHashMap<String, CandidateItemDTO>();
        private final Map<String, CandidateItemDTO> byLegacyVolunteerPrefix = new LinkedHashMap<String, CandidateItemDTO>();
        private final Set<String> duplicatedLegacyVolunteerPrefixes = new HashSet<String>();

        CandidateIndex(List<CandidateItemDTO> candidates) {
            for (CandidateItemDTO candidate : defaultList(candidates)) {
                if (candidate == null) {
                    continue;
                }
                putUnique(byVolunteerId, null, candidate.getVolunteerId(), candidate);
                putUnique(byLegacyVolunteerPrefix, duplicatedLegacyVolunteerPrefixes,
                        legacyVolunteerPrefix(candidate.getVolunteerId()), candidate);
            }
        }

        CandidateItemDTO resolve(String volunteerId) {
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
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static boolean isSafetyMajorRatio(Double majorAdmissionRatio, Double unitEnrollRatio) {
        return majorAdmissionRatio != null
                && unitEnrollRatio != null
                && majorAdmissionRatio >= unitEnrollRatio;
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<DraftItemDTO> defaultDraftItems(List<DraftItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private static List<PlanningUnitMajorDTO> defaultPlanningUnitMajors(List<PlanningUnitMajorDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }
}
