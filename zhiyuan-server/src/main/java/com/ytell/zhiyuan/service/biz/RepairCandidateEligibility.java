package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;

import java.util.List;
import java.util.Locale;

final class RepairCandidateEligibility {

    private RepairCandidateEligibility() {
    }

    static boolean hasConfirmedHardConstraints(PlanningStateDTO state) {
        return confirmedHardConstraints(state) != null;
    }

    static boolean isEligibleForConfirmedHardConstraints(CandidateItemDTO item, PlanningStateDTO state) {
        return isEligibleForHardConstraints(item, confirmedHardConstraints(state));
    }

    static boolean isEligibleForHardConstraints(CandidateItemDTO item, HardConstraintsDTO hard) {
        if (item == null) {
            return false;
        }
        if (hard == null) {
            return true;
        }
        if (matchesAnyRegion(item, hard.getMustExcludeRegions())
                || matchesAnySchool(item, hard.getMustExcludeSchools())
                || matchesAnyMajor(item, hard.getMustExcludeMajors())) {
            return false;
        }
        return matchesRequiredRegion(item, hard.getMustIncludeRegions())
                && matchesRequiredSchool(item, hard.getMustIncludeSchools())
                && matchesRequiredMajor(item, hard.getMustIncludeMajors());
    }

    static boolean isEligibleForConfirmedHardConstraints(PlanningUnitDTO unit, PlanningStateDTO state) {
        return isEligibleForHardConstraints(unit, confirmedHardConstraints(state));
    }

    static boolean isEligibleForHardConstraints(PlanningUnitDTO unit, HardConstraintsDTO hard) {
        if (unit == null) {
            return false;
        }
        if (hard == null) {
            return true;
        }
        if (matchesAnyRegionScope(hard.getMustExcludeRegions(), unit.getProvinceName(), unit.getCityName())
                || matchesAnyPlanningUnitSchool(unit, hard.getMustExcludeSchools())
                || matchesAnyPlanningUnitMajor(unit, hard.getMustExcludeMajors())) {
            return false;
        }
        return (defaultList(hard.getMustIncludeRegions()).isEmpty()
                || matchesAnyRegionScope(hard.getMustIncludeRegions(), unit.getProvinceName(), unit.getCityName()))
                && (defaultList(hard.getMustIncludeSchools()).isEmpty()
                || matchesAnyPlanningUnitSchool(unit, hard.getMustIncludeSchools()))
                && (defaultList(hard.getMustIncludeMajors()).isEmpty()
                || matchesAnyPlanningUnitMajor(unit, hard.getMustIncludeMajors()));
    }

    private static HardConstraintsDTO confirmedHardConstraints(PlanningStateDTO state) {
        ConstraintStateDTO constraintState = state == null ? null : state.getConstraintState();
        HardConstraintsDTO hard = constraintState == null ? null : constraintState.getHardConstraints();
        if (hard == null) {
            return null;
        }
        if (defaultList(hard.getMustIncludeRegions()).isEmpty()
                && defaultList(hard.getMustExcludeRegions()).isEmpty()
                && defaultList(hard.getMustIncludeSchools()).isEmpty()
                && defaultList(hard.getMustExcludeSchools()).isEmpty()
                && defaultList(hard.getMustIncludeMajors()).isEmpty()
                && defaultList(hard.getMustExcludeMajors()).isEmpty()) {
            return null;
        }
        return hard;
    }

    private static boolean matchesRequiredRegion(CandidateItemDTO item, List<String> values) {
        return defaultList(values).isEmpty() || matchesAnyRegion(item, values);
    }

    private static boolean matchesRequiredSchool(CandidateItemDTO item, List<String> values) {
        return defaultList(values).isEmpty() || matchesAnySchool(item, values);
    }

    private static boolean matchesRequiredMajor(CandidateItemDTO item, List<String> values) {
        return defaultList(values).isEmpty() || matchesAnyMajor(item, values);
    }

    private static boolean matchesAnyRegion(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnyRegionScope(values, item.getProvinceName(), item.getCityName());
    }

    private static boolean matchesAnyRegionScope(List<String> values, String provinceName, String cityName) {
        for (String value : defaultList(values)) {
            if (RegionScopeSupport.matchesRegionScope(value, provinceName, cityName)
                    || matchesAnyText(Lists.newArrayList(value), provinceName, cityName)) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesAnySchool(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnySchoolScope(values, item);
    }

    private static boolean matchesAnyMajor(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnyMajorScope(values, item);
    }

    private static boolean matchesAnyPlanningUnitMajor(PlanningUnitDTO unit, List<String> values) {
        if (unit == null || defaultList(values).isEmpty()) {
            return false;
        }
        List<PlanningUnitMajorDTO> majors = !defaultList(unit.getSelectedMajors()).isEmpty()
                ? unit.getSelectedMajors() : unit.getAllMajors();
        for (PlanningUnitMajorDTO major : defaultList(majors)) {
            if (major != null && matchesAnyMajorScope(values, planningUnitMajorAsCandidate(unit, major))) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesAnyPlanningUnitSchool(PlanningUnitDTO unit, List<String> values) {
        if (unit == null) {
            return false;
        }
        if (matchesAnySchoolScope(values, planningUnitAsCandidate(unit))) {
            return true;
        }
        List<PlanningUnitMajorDTO> majors = !defaultList(unit.getSelectedMajors()).isEmpty()
                ? unit.getSelectedMajors() : unit.getAllMajors();
        for (PlanningUnitMajorDTO major : defaultList(majors)) {
            if (major != null && matchesAnySchoolScope(values, planningUnitMajorAsCandidate(unit, major))) {
                return true;
            }
        }
        return false;
    }

    private static CandidateItemDTO planningUnitAsCandidate(PlanningUnitDTO unit) {
        CandidateItemDTO item = new CandidateItemDTO();
        if (unit == null) {
            return item;
        }
        item.setSchoolName(unit.getSchoolName());
        item.setProvinceName(unit.getProvinceName());
        item.setCityName(unit.getCityName());
        item.setSchoolLevel(unit.getSchoolLevel());
        item.setSchoolNature(unit.getSchoolNature());
        item.setSchoolCategory(unit.getSchoolCategory());
        return item;
    }

    private static CandidateItemDTO planningUnitMajorAsCandidate(PlanningUnitDTO unit, PlanningUnitMajorDTO major) {
        CandidateItemDTO item = planningUnitAsCandidate(unit);
        if (major != null) {
            item.setMajorName(major.getMajorName());
            item.setTuitionPerYear(major.getTuitionPerYear());
            item.setReasonCodes(defaultList(major.getReasonCodes()));
            item.setMajorPlanTags(defaultList(major.getMajorPlanTags()));
        }
        return item;
    }

    private static boolean matchesAnyText(List<String> values, String... fields) {
        for (String value : defaultList(values)) {
            for (String field : fields == null ? new String[0] : fields) {
                if (textMatches(field, value)) {
                    return true;
                }
            }
        }
        return false;
    }

    private static boolean matchesAnySchoolScope(List<String> values, CandidateItemDTO item) {
        for (String value : defaultList(values)) {
            if (matchesSchoolScope(value, item)) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesSchoolScope(String value, CandidateItemDTO item) {
        if (item == null || Strings.isNullOrEmpty(value)) {
            return false;
        }
        String scope = value.trim();
        if (textMatches(item.getSchoolName(), scope)) {
            return true;
        }
        int split = scope.indexOf(':');
        if (split < 0) {
            split = scope.indexOf('：');
        }
        if (split < 0) {
            return textMatches(item.getSchoolNature(), scope)
                    || textMatches(item.getSchoolCategory(), scope)
                    || textMatches(item.getSchoolLevel(), scope)
                    || matchesHighTuitionScope(item, scope)
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getSchoolRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getSchoolBasicTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getSchoolPopupTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        String label = scope.substring(0, split).trim();
        String pattern = scope.substring(split + 1).trim();
        if (Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        if (containsAny(label, "性质", "办学")) {
            return textMatches(item.getSchoolNature(), pattern);
        }
        if (containsAny(label, "招生类型", "项目", "限制")) {
            return matchesHighTuitionScope(item, pattern)
                    || textMatches(item.getSchoolName(), pattern)
                    || textMatches(item.getMajorName(), pattern)
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorPlanTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        if (containsAny(label, "院校类型", "学校类型") || "类型".equals(label)) {
            return textMatches(item.getSchoolCategory(), pattern);
        }
        if (containsAny(label, "层次", "级别")) {
            return textMatches(item.getSchoolLevel(), pattern)
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolRankTags()).toArray(new String[0]));
        }
        if (containsAny(label, "标签")) {
            return matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolBasicTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolPopupTags()).toArray(new String[0]));
        }
        return false;
    }

    private static boolean matchesAnyMajorScope(List<String> values, CandidateItemDTO item) {
        for (String value : defaultList(values)) {
            if (matchesMajorScope(value, item)) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesMajorScope(String value, CandidateItemDTO item) {
        if (item == null || Strings.isNullOrEmpty(value)) {
            return false;
        }
        String scope = value.trim();
        if (matchesAnyText(Lists.newArrayList(scope), item.getMajorName(), item.getMajorCategory(), item.getMajorDiscipline())) {
            return true;
        }
        int split = scope.indexOf(':');
        if (split < 0) {
            split = scope.indexOf('：');
        }
        if (split < 0) {
            return matchesAnyText(Lists.newArrayList(scope), defaultList(item.getMajorRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getMajorPlanTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        String label = scope.substring(0, split).trim();
        String pattern = scope.substring(split + 1).trim();
        if (Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        if (containsAny(label, "专业门类", "专业类", "门类")) {
            return matchesAnyText(Lists.newArrayList(pattern), item.getMajorCategory(), item.getMajorDiscipline());
        }
        if (containsAny(label, "专业标签", "标签")) {
            return matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorPlanTags()).toArray(new String[0]));
        }
        if (containsAny(label, "招生类型", "项目", "限制")) {
            return textMatches(item.getMajorName(), pattern)
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorPlanTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        return false;
    }

    private static boolean matchesHighTuitionScope(CandidateItemDTO item, String pattern) {
        if (item == null || !isHighTuitionPattern(pattern)) {
            return false;
        }
        Integer tuition = item.getTuitionPerYear();
        return tuition != null && tuition > 20000;
    }

    private static boolean isHighTuitionPattern(String pattern) {
        if (Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        String normalized = pattern.trim().toLowerCase(Locale.ROOT);
        return normalized.contains("高收费")
                || normalized.contains("高学费")
                || normalized.contains("学费高")
                || normalized.contains("high_tuition");
    }

    private static boolean containsAny(String text, String... needles) {
        if (Strings.isNullOrEmpty(text) || needles == null) {
            return false;
        }
        for (String needle : needles) {
            if (!Strings.isNullOrEmpty(needle) && text.contains(needle)) {
                return true;
            }
        }
        return false;
    }

    private static boolean textMatches(String field, String pattern) {
        if (Strings.isNullOrEmpty(field) || Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        String normalizedField = field.trim().toLowerCase(Locale.ROOT);
        String normalizedPattern = pattern.trim().toLowerCase(Locale.ROOT);
        return normalizedField.contains(normalizedPattern) || normalizedPattern.contains(normalizedField);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }
}
