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
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
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

        Map<String, CandidateItemDTO> candidateMap = buildCandidateMap(state);
        boolean majorGroupMode = isMajorGroupMode(state);
        List<ExcelUtil.VolunteerExcelData> mainList = majorGroupMode
                ? buildMajorGroupExcelRows(orderedPlanState, candidateMap)
                : buildMajorSchoolExcelRows(orderedPlanState, candidateMap);

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

    private Map<String, CandidateItemDTO> buildCandidateMap(PlanningStateDTO state) {
        if (state == null || state.getCandidatePoolState() == null || state.getCandidatePoolState().getItems() == null) {
            return Collections.emptyMap();
        }
        return state.getCandidatePoolState().getItems().stream()
                .filter(Objects::nonNull)
                .filter(item -> !Strings.isNullOrEmpty(item.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, item -> item, (left, right) -> left, LinkedHashMap::new));
    }

    private boolean isMajorGroupMode(PlanningStateDTO state) {
        return state != null
                && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
    }

    private List<ExcelUtil.VolunteerExcelData> buildMajorSchoolExcelRows(OrderedPlanStateDTO orderedPlanState,
                                                                         Map<String, CandidateItemDTO> candidateMap) {
        Map<String, MajorSchoolExportGroup> grouped = new LinkedHashMap<String, MajorSchoolExportGroup>();
        for (OrderedItemDTO orderedItem : defaultOrderedItems(orderedPlanState.getItems())) {
            CandidateItemDTO candidate = candidateMap.get(orderedItem.getVolunteerId());
            String groupKey = resolveMajorSchoolGroupKey(orderedItem, candidate);
            MajorSchoolExportGroup group = grouped.computeIfAbsent(groupKey, key -> new MajorSchoolExportGroup());
            if (group.representative == null) {
                group.representative = candidate;
                group.fallbackOrderedItem = orderedItem;
                group.position = orderedItem.getPosition();
            }
            if (orderedItem.getPosition() != null && (group.position == null || orderedItem.getPosition() < group.position)) {
                group.position = orderedItem.getPosition();
            }
            group.entries.add(new MajorSchoolExportEntry(orderedItem, candidate));
        }
        return grouped.values().stream()
                .sorted(Comparator.comparing(group -> group.position == null ? Integer.MAX_VALUE : group.position))
                .map(this::toMajorSchoolExcelData)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private String resolveMajorSchoolGroupKey(OrderedItemDTO orderedItem, CandidateItemDTO candidate) {
        if (candidate != null) {
            if (!Strings.isNullOrEmpty(candidate.getSchoolId())) {
                return candidate.getSchoolId();
            }
            if (!Strings.isNullOrEmpty(candidate.getPlanSchoolDataId())) {
                return candidate.getPlanSchoolDataId();
            }
            if (!Strings.isNullOrEmpty(candidate.getSchoolName())) {
                return candidate.getSchoolName();
            }
        }
        return Strings.isNullOrEmpty(orderedItem.getSchoolName()) ? String.valueOf(System.identityHashCode(orderedItem)) : orderedItem.getSchoolName();
    }

    private ExcelUtil.VolunteerExcelData toMajorSchoolExcelData(MajorSchoolExportGroup group) {
        if (group == null || group.entries.isEmpty()) {
            return null;
        }
        CandidateItemDTO representative = group.representative;
        ExcelUtil.VolunteerExcelData excelData = new ExcelUtil.VolunteerExcelData();
        excelData.setIndex(group.position);
        excelData.setEnrollRatio(formatRatio(representative == null ? null : representative.getAdmissionRatio()));
        excelData.setSchoolCode(representative == null ? "" : safeString(representative.getSchoolUnitCode()));
        excelData.setSchoolName(resolveSchoolName(group.fallbackOrderedItem, representative));
        excelData.setSchoolLevel(representative == null ? "" : safeString(representative.getSchoolLevel()));
        excelData.setSchoolPosition(joinArea(representative == null ? null : representative.getProvinceName(),
                representative == null ? null : representative.getCityName()));
        excelData.setSchoolType(representative == null ? "" : safeString(representative.getSchoolCategory()));
        excelData.setSchoolNature(representative == null ? "" : safeString(representative.getSchoolNature()));
        excelData.setSchoolRank(representative == null || representative.getSchoolRank() == null ? "" : String.valueOf(representative.getSchoolRank()));
        excelData.setMajorList(group.entries.stream()
                .map(entry -> toMajorExcelData(entry.candidate, false))
                .filter(Objects::nonNull)
                .collect(Collectors.toList()));
        return excelData;
    }

    private List<ExcelUtil.VolunteerExcelData> buildMajorGroupExcelRows(OrderedPlanStateDTO orderedPlanState,
                                                                        Map<String, CandidateItemDTO> candidateMap) {
        List<OrderedUnitDTO> units = orderedPlanState.getUnits() == null ? Lists.newArrayList() : orderedPlanState.getUnits();
        if (units.isEmpty()) {
            return buildMajorGroupExcelRowsFromItems(orderedPlanState, candidateMap);
        }
        return units.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(unit -> unit.getPosition() == null ? Integer.MAX_VALUE : unit.getPosition()))
                .map(unit -> toMajorGroupExcelData(unit, candidateMap))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private List<ExcelUtil.VolunteerExcelData> buildMajorGroupExcelRowsFromItems(OrderedPlanStateDTO orderedPlanState,
                                                                                 Map<String, CandidateItemDTO> candidateMap) {
        Map<String, OrderedUnitDTO> unitMap = new LinkedHashMap<String, OrderedUnitDTO>();
        for (OrderedItemDTO item : defaultOrderedItems(orderedPlanState.getItems())) {
            CandidateItemDTO candidate = candidateMap.get(item.getVolunteerId());
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
                .map(unit -> toMajorGroupExcelData(unit, candidateMap))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private ExcelUtil.VolunteerExcelData toMajorGroupExcelData(OrderedUnitDTO unit,
                                                               Map<String, CandidateItemDTO> candidateMap) {
        if (unit == null || unit.getMajorItems() == null || unit.getMajorItems().isEmpty()) {
            return null;
        }
        CandidateItemDTO representative = findRepresentativeCandidate(unit, candidateMap);
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
        excelData.setMajorList(unit.getMajorItems().stream()
                .map(major -> {
                    CandidateItemDTO candidate = candidateMap.get(major.getVolunteerId());
                    return toMajorExcelData(candidate, true);
                })
                .filter(Objects::nonNull)
                .collect(Collectors.toList()));
        return excelData;
    }

    private CandidateItemDTO findRepresentativeCandidate(OrderedUnitDTO unit,
                                                         Map<String, CandidateItemDTO> candidateMap) {
        for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
            CandidateItemDTO candidate = candidateMap.get(major.getVolunteerId());
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

    private static class MajorSchoolExportGroup {
        private Integer position;
        private CandidateItemDTO representative;
        private OrderedItemDTO fallbackOrderedItem;
        private final List<MajorSchoolExportEntry> entries = new ArrayList<MajorSchoolExportEntry>();
    }

    private static class MajorSchoolExportEntry {
        private final OrderedItemDTO orderedItem;
        private final CandidateItemDTO candidate;

        private MajorSchoolExportEntry(OrderedItemDTO orderedItem, CandidateItemDTO candidate) {
            this.orderedItem = orderedItem;
            this.candidate = candidate;
        }
    }
}
