package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.ExcelUtil;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

@Component
public class PlanningExcelExportBuilder {

    public PlanningExportData build(PlanningStateDTO state, CreateSessionReq userScoreDetail) {
        if (state == null || state.getOrderedPlanState() == null) {
            throw new BusinessException(400, "当前方案不存在，无法导出");
        }
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        if (orderedPlanState.getItems() == null || orderedPlanState.getItems().isEmpty()) {
            throw new BusinessException(400, "当前方案为空，无法导出，请先生成方案");
        }

        CandidateExportResolver candidateResolver = new CandidateExportResolver(state.getCandidatePoolState().getItems());
        boolean majorGroupMode = isMajorGroupMode(state);
        List<ExcelUtil.VolunteerExcelData> mainList = majorGroupMode
                ? buildMajorGroupExcelRows(orderedPlanState, candidateResolver)
                : buildMajorSchoolExcelRows(orderedPlanState, candidateResolver);

        if (mainList.isEmpty()) {
            throw new BusinessException(400, "当前方案缺少可导出的志愿明细");
        }
        renumberMainRows(mainList);
        return new PlanningExportData(mainList, majorGroupMode);
    }

    private void renumberMainRows(List<ExcelUtil.VolunteerExcelData> mainList) {
        for (int index = 0; index < mainList.size(); index++) {
            mainList.get(index).setIndex(index + 1);
        }
    }

    private boolean isMajorGroupMode(PlanningStateDTO state) {
        return state != null
                && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
    }

    private List<ExcelUtil.VolunteerExcelData> buildMajorSchoolExcelRows(OrderedPlanStateDTO orderedPlanState,
                                                                         CandidateExportResolver candidateResolver) {
        return defaultOrderedItems(orderedPlanState.getItems()).stream()
                .sorted(Comparator.comparing(item -> item.getPosition() == null ? Integer.MAX_VALUE : item.getPosition()))
                .map(orderedItem -> toMajorSchoolExcelData(orderedItem, candidateResolver.resolve(orderedItem)))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private ExcelUtil.VolunteerExcelData toMajorSchoolExcelData(OrderedItemDTO orderedItem, CandidateItemDTO candidate) {
        if (orderedItem == null || candidate == null) {
            return null;
        }
        ExcelUtil.VolunteerExcelData excelData = new ExcelUtil.VolunteerExcelData();
        excelData.setIndex(orderedItem.getPosition());
        excelData.setEnrollRatio(formatRatio(candidate.getAdmissionRatio()));
        excelData.setSchoolCode(safeString(candidate.getSchoolUnitCode()));
        excelData.setSchoolName(resolveSchoolName(orderedItem, candidate));
        excelData.setSchoolLevel(safeString(candidate.getSchoolLevel()));
        excelData.setSchoolPosition(joinArea(candidate.getProvinceName(), candidate.getCityName()));
        excelData.setSchoolType(safeString(candidate.getSchoolCategory()));
        excelData.setSchoolNature(safeString(candidate.getSchoolNature()));
        excelData.setSchoolRank(candidate.getSchoolRank() == null ? "" : String.valueOf(candidate.getSchoolRank()));
        excelData.setMajorList(Lists.newArrayList(candidate).stream()
                .map(item -> toMajorExcelData(item, false))
                .filter(Objects::nonNull)
                .collect(Collectors.toList()));
        return excelData;
    }

    private List<ExcelUtil.VolunteerExcelData> buildMajorGroupExcelRows(OrderedPlanStateDTO orderedPlanState,
                                                                        CandidateExportResolver candidateResolver) {
        List<OrderedUnitDTO> units = orderedPlanState.getUnits() == null ? Lists.newArrayList() : orderedPlanState.getUnits();
        if (units.isEmpty()) {
            return buildMajorGroupExcelRowsFromItems(orderedPlanState, candidateResolver);
        }
        return units.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(unit -> unit.getPosition() == null ? Integer.MAX_VALUE : unit.getPosition()))
                .map(unit -> toMajorGroupExcelData(unit, candidateResolver))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private List<ExcelUtil.VolunteerExcelData> buildMajorGroupExcelRowsFromItems(OrderedPlanStateDTO orderedPlanState,
                                                                                 CandidateExportResolver candidateResolver) {
        Map<String, OrderedUnitDTO> unitMap = new LinkedHashMap<String, OrderedUnitDTO>();
        for (OrderedItemDTO item : defaultOrderedItems(orderedPlanState.getItems())) {
            CandidateItemDTO candidate = candidateResolver.resolve(item);
            String unitId = candidate != null && !Strings.isNullOrEmpty(candidate.getPlanSchoolDataId())
                    ? candidate.getPlanSchoolDataId()
                    : (Strings.isNullOrEmpty(item.getSchoolName()) ? item.getVolunteerId() : item.getSchoolName());
            OrderedUnitDTO unit = unitMap.computeIfAbsent(unitId, key -> {
                OrderedUnitDTO dto = new OrderedUnitDTO();
                dto.setUnitId(key);
                dto.setPosition(item.getPosition());
                dto.setTier(item.getTier());
                dto.setSchoolName(item.getSchoolName());
                dto.setProvinceName(candidate == null ? null : candidate.getProvinceName());
                dto.setCityName(candidate == null ? null : candidate.getCityName());
                dto.setAdmissionRatio(candidate == null ? null : candidate.getSchoolEnrollRatio());
                dto.setSchoolEnrollRatio(candidate == null ? null : candidate.getSchoolEnrollRatio());
                dto.setFinalScore(candidate == null ? null : candidate.getFinalScore());
                return dto;
            });
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(item.getVolunteerId());
            major.setMajorName(item.getMajorName());
            if (candidate != null) {
                major.setMajorCode(candidate.getMajorCode());
                major.setAdmissionRatio(candidate.getAdmissionRatio());
                major.setTuitionPerYear(candidate.getTuitionPerYear());
            }
            unit.getMajorItems().add(major);
        }
        return unitMap.values().stream()
                .sorted(Comparator.comparing(unit -> unit.getPosition() == null ? Integer.MAX_VALUE : unit.getPosition()))
                .map(unit -> toMajorGroupExcelData(unit, candidateResolver))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private ExcelUtil.VolunteerExcelData toMajorGroupExcelData(OrderedUnitDTO unit,
                                                               CandidateExportResolver candidateResolver) {
        if (unit == null || unit.getMajorItems() == null || unit.getMajorItems().isEmpty()) {
            return null;
        }
        CandidateItemDTO representative = findRepresentativeCandidate(unit, candidateResolver);
        ExcelUtil.VolunteerExcelData excelData = new ExcelUtil.VolunteerExcelData();
        excelData.setIndex(unit.getPosition());
        excelData.setEnrollRatio(formatRatio(unit.getSchoolEnrollRatio() == null ? unit.getAdmissionRatio() : unit.getSchoolEnrollRatio()));
        excelData.setSchoolCode(representative == null ? "" : safeString(representative.getSchoolUnitCode()));
        excelData.setSchoolName(!Strings.isNullOrEmpty(unit.getSchoolName()) ? unit.getSchoolName() : resolveSchoolName(null, representative));
        excelData.setSchoolLevel(representative == null ? "" : safeString(representative.getSchoolLevel()));
        excelData.setSchoolPosition(joinArea(
                !Strings.isNullOrEmpty(unit.getProvinceName()) ? unit.getProvinceName() : representative == null ? null : representative.getProvinceName(),
                !Strings.isNullOrEmpty(unit.getCityName()) ? unit.getCityName() : representative == null ? null : representative.getCityName()));
        excelData.setSchoolType(representative == null ? "" : safeString(representative.getSchoolCategory()));
        excelData.setSchoolNature(representative == null ? "" : safeString(representative.getSchoolNature()));
        excelData.setSchoolRank(representative == null || representative.getSchoolRank() == null ? "" : String.valueOf(representative.getSchoolRank()));
        excelData.setMajorList(sortMajorItemsForExport(unit, candidateResolver).stream()
                .map(major -> toMajorExcelData(candidateResolver.resolve(unit, major), true))
                .filter(Objects::nonNull)
                .collect(Collectors.toList()));
        return excelData;
    }

    private CandidateItemDTO findRepresentativeCandidate(OrderedUnitDTO unit,
                                                         CandidateExportResolver candidateResolver) {
        for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
            CandidateItemDTO candidate = candidateResolver.resolve(unit, major);
            if (candidate != null) {
                return candidate;
            }
        }
        return null;
    }

    private ExcelUtil.VolunteerMajorExcelData toMajorExcelData(CandidateItemDTO candidate,
                                                               boolean majorGroupMode) {
        if (candidate == null) {
            return null;
        }
        ExcelUtil.VolunteerMajorExcelData majorData = new ExcelUtil.VolunteerMajorExcelData();
        if (majorGroupMode) {
            majorData.setMajorEnrollRatio(formatPercent(candidate.getAdmissionRatio()));
        }
        majorData.setMajorCode(candidate.getMajorCode());
        majorData.setMajorName(candidate.getMajorName());
        majorData.setMajorPlan(candidate.getPlanNum() == null ? null : String.valueOf(candidate.getPlanNum()));
        majorData.setMajorTuition(candidate.getTuitionPerYear() == null ? null : String.valueOf(candidate.getTuitionPerYear()));
        majorData.setMajorDuration(candidate.getDuration());
        majorData.setMajorSelectInfo(joinMustSubjects(candidate.getMustSubjects()));
        fillMajorHistoryScores(majorData, candidate.getMajorHistoryScores());
        return majorData;
    }

    private void fillMajorHistoryScores(ExcelUtil.VolunteerMajorExcelData majorData,
                                        List<CandidateItemDTO.HistoryScoreItem> historyScores) {
        List<CandidateItemDTO.HistoryScoreItem> scores = historyScores == null ? Lists.newArrayList() : historyScores;
        setHistoryScore(majorData, scores, 0, true);
        setHistoryScore(majorData, scores, 1, false);
        setHistoryScore(majorData, scores, 2, null);
    }

    private void setHistoryScore(ExcelUtil.VolunteerMajorExcelData majorData,
                                 List<CandidateItemDTO.HistoryScoreItem> scores,
                                 int index,
                                 Boolean lastYear) {
        CandidateItemDTO.HistoryScoreItem item = scores.size() > index ? scores.get(index) : null;
        String enrollNum = emptyNumValue(item == null || item.getEnrollNum() == null ? "-1" : String.valueOf(item.getEnrollNum()));
        String score = emptyNumValue(item == null || item.getScore() == null ? "-1" : String.valueOf(item.getScore()));
        String pos = emptyNumValue(item == null || item.getPos() == null ? "-1" : String.valueOf(item.getPos()));
        if (Boolean.TRUE.equals(lastYear)) {
            majorData.setMajorEnrollNumLastYear(enrollNum);
            majorData.setMajorMinScoreLastYear(score);
            majorData.setMajorMinPosLastYear(pos);
            return;
        }
        if (Boolean.FALSE.equals(lastYear)) {
            majorData.setMajorEnrollNumYearBefore(enrollNum);
            majorData.setMajorMinScoreYearBefore(score);
            majorData.setMajorMinPosYearBefore(pos);
            return;
        }
        majorData.setMajorEnrollNumYearBeforeLast(enrollNum);
        majorData.setMajorMinScoreYearBeforeLast(score);
        majorData.setMajorMinPosYearBeforeLast(pos);
    }

    private List<OrderedItemDTO> defaultOrderedItems(List<OrderedItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private List<PlanningUnitMajorDTO> defaultPlanningUnitMajors(List<PlanningUnitMajorDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private List<PlanningUnitMajorDTO> sortMajorItemsForExport(OrderedUnitDTO unit,
                                                               CandidateExportResolver candidateResolver) {
        return defaultPlanningUnitMajors(unit == null ? null : unit.getMajorItems()).stream()
                .filter(Objects::nonNull)
                .sorted(Comparator
                        .comparing((PlanningUnitMajorDTO major) -> resolveMajorAdmissionRatio(unit, major, candidateResolver),
                                Comparator.nullsLast(Double::compareTo))
                        .thenComparing((PlanningUnitMajorDTO major) -> resolveMajorIntentScore(unit, major, candidateResolver),
                                Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing((PlanningUnitMajorDTO major) -> resolveMajorFinalScore(unit, major, candidateResolver),
                                Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(PlanningUnitMajorDTO::getVolunteerId, Comparator.nullsLast(String::compareTo)))
                .collect(Collectors.toList());
    }

    private Double resolveMajorAdmissionRatio(OrderedUnitDTO unit,
                                              PlanningUnitMajorDTO major,
                                              CandidateExportResolver candidateResolver) {
        if (major == null) {
            return null;
        }
        if (major.getAdmissionRatio() != null) {
            return major.getAdmissionRatio();
        }
        CandidateItemDTO candidate = candidateResolver.resolve(unit, major);
        return candidate == null ? null : candidate.getAdmissionRatio();
    }

    private Double resolveMajorIntentScore(OrderedUnitDTO unit,
                                           PlanningUnitMajorDTO major,
                                           CandidateExportResolver candidateResolver) {
        if (major == null) {
            return null;
        }
        if (major.getIntentScore() != null) {
            return major.getIntentScore();
        }
        CandidateItemDTO candidate = candidateResolver.resolve(unit, major);
        return candidate == null ? null : candidate.getIntentScore();
    }

    private Double resolveMajorFinalScore(OrderedUnitDTO unit,
                                          PlanningUnitMajorDTO major,
                                          CandidateExportResolver candidateResolver) {
        if (major == null) {
            return null;
        }
        if (major.getFinalScore() != null) {
            return major.getFinalScore();
        }
        CandidateItemDTO candidate = candidateResolver.resolve(unit, major);
        return candidate == null ? null : candidate.getFinalScore();
    }

    private String formatRatio(Double ratio) {
        if (ratio == null) {
            return "";
        }
        if (Math.abs(ratio - Math.rint(ratio)) < 0.000001d) {
            return String.valueOf(ratio.intValue());
        }
        return String.format(java.util.Locale.ROOT, "%.1f", ratio);
    }

    private String formatPercent(Double ratio) {
        String raw = formatRatio(ratio);
        return Strings.isNullOrEmpty(raw) ? "" : raw + "%";
    }

    private String joinArea(String province, String city) {
        String joined = java.util.stream.Stream.of(province, city)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining());
        return joined == null ? "" : joined;
    }

    private String joinMustSubjects(List<String> mustSubjects) {
        if (mustSubjects == null || mustSubjects.isEmpty()) {
            return "";
        }
        return mustSubjects.stream().filter(value -> !Strings.isNullOrEmpty(value)).collect(Collectors.joining(","));
    }

    private String safeString(String value) {
        return value == null ? "" : value;
    }

    private String resolveSchoolName(OrderedItemDTO orderedItem, CandidateItemDTO candidate) {
        if (candidate != null && !Strings.isNullOrEmpty(candidate.getSchoolName())) {
            return candidate.getSchoolName();
        }
        return orderedItem == null ? "" : safeString(orderedItem.getSchoolName());
    }

    private String emptyNumValue(String val) {
        if ("-1".equals(val)) {
            return "-";
        }
        return val;
    }

    public static class PlanningExportData {
        private final List<ExcelUtil.VolunteerExcelData> mainList;
        private final boolean majorGroupMode;

        public PlanningExportData(List<ExcelUtil.VolunteerExcelData> mainList, boolean majorGroupMode) {
            this.mainList = mainList == null ? new ArrayList<ExcelUtil.VolunteerExcelData>() : mainList;
            this.majorGroupMode = majorGroupMode;
        }

        public List<ExcelUtil.VolunteerExcelData> getMainList() {
            return mainList;
        }

        public boolean isMajorGroupMode() {
            return majorGroupMode;
        }
    }

    private static class CandidateExportResolver {
        private final Map<String, CandidateItemDTO> byVolunteerId = new LinkedHashMap<String, CandidateItemDTO>();
        private final Map<String, CandidateItemDTO> byLegacyVolunteerPrefix = new LinkedHashMap<String, CandidateItemDTO>();
        private final Set<String> duplicatedLegacyVolunteerPrefixes = new HashSet<String>();
        private final Map<String, CandidateItemDTO> bySchoolAndMajor = new LinkedHashMap<String, CandidateItemDTO>();
        private final Set<String> duplicatedSchoolAndMajors = new HashSet<String>();

        private CandidateExportResolver(List<CandidateItemDTO> candidates) {
            for (CandidateItemDTO candidate : candidates == null ? Lists.<CandidateItemDTO>newArrayList() : candidates) {
                if (candidate == null) {
                    continue;
                }
                putUnique(byVolunteerId, null, candidate.getVolunteerId(), candidate);
                putUnique(byLegacyVolunteerPrefix, duplicatedLegacyVolunteerPrefixes,
                        legacyVolunteerPrefix(candidate.getVolunteerId()), candidate);
                putUnique(bySchoolAndMajor, duplicatedSchoolAndMajors,
                        schoolAndMajorKey(candidate.getSchoolName(), candidate.getMajorName()), candidate);
            }
        }

        private CandidateItemDTO resolve(OrderedItemDTO item) {
            if (item == null) {
                return null;
            }
            CandidateItemDTO candidate = resolve(item.getVolunteerId());
            if (candidate != null) {
                return candidate;
            }
            return resolveBySchoolAndMajor(item.getSchoolName(), item.getMajorName());
        }

        private CandidateItemDTO resolve(OrderedUnitDTO unit, PlanningUnitMajorDTO major) {
            if (major == null) {
                return null;
            }
            CandidateItemDTO candidate = resolve(major.getVolunteerId());
            if (candidate != null) {
                return candidate;
            }
            return resolveBySchoolAndMajor(unit == null ? null : unit.getSchoolName(), major.getMajorName());
        }

        private CandidateItemDTO resolve(PlanningUnitMajorDTO major) {
            if (major == null) {
                return null;
            }
            CandidateItemDTO candidate = resolve(major.getVolunteerId());
            if (candidate != null) {
                return candidate;
            }
            return resolveBySchoolAndMajor(null, major.getMajorName());
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

        private CandidateItemDTO resolveBySchoolAndMajor(String schoolName, String majorName) {
            if (Strings.isNullOrEmpty(majorName)) {
                return null;
            }
            if (!Strings.isNullOrEmpty(schoolName)) {
                String key = schoolAndMajorKey(schoolName, majorName);
                if (!Strings.isNullOrEmpty(key) && !duplicatedSchoolAndMajors.contains(key)) {
                    return bySchoolAndMajor.get(key);
                }
            }
            List<CandidateItemDTO> matched = bySchoolAndMajor.entrySet().stream()
                    .filter(entry -> entry.getKey().endsWith("\n" + majorName.trim()))
                    .map(Map.Entry::getValue)
                    .collect(Collectors.toList());
            return matched.size() == 1 ? matched.get(0) : null;
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

        private static String schoolAndMajorKey(String schoolName, String majorName) {
            if (Strings.isNullOrEmpty(schoolName) || Strings.isNullOrEmpty(majorName)) {
                return null;
            }
            return schoolName.trim() + "\n" + majorName.trim();
        }
    }
}
