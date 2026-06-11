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
        if (item == null) {
            return false;
        }
        HardConstraintsDTO hard = confirmedHardConstraints(state);
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
        if (unit == null) {
            return false;
        }
        HardConstraintsDTO hard = confirmedHardConstraints(state);
        if (hard == null) {
            return true;
        }
        if (matchesAnyText(defaultList(hard.getMustExcludeRegions()), unit.getProvinceName(), unit.getCityName())
                || matchesAnyText(defaultList(hard.getMustExcludeSchools()), unit.getSchoolName())
                || matchesAnyPlanningUnitMajor(unit, hard.getMustExcludeMajors())) {
            return false;
        }
        return (defaultList(hard.getMustIncludeRegions()).isEmpty()
                || matchesAnyText(hard.getMustIncludeRegions(), unit.getProvinceName(), unit.getCityName()))
                && (defaultList(hard.getMustIncludeSchools()).isEmpty()
                || matchesAnyText(hard.getMustIncludeSchools(), unit.getSchoolName()))
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
        return item != null && matchesAnyText(values, item.getProvinceName(), item.getCityName());
    }

    private static boolean matchesAnySchool(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnyText(values, item.getSchoolName());
    }

    private static boolean matchesAnyMajor(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnyText(values, item.getMajorName(), item.getMajorCategory(), item.getMajorDiscipline());
    }

    private static boolean matchesAnyPlanningUnitMajor(PlanningUnitDTO unit, List<String> values) {
        if (unit == null || defaultList(values).isEmpty()) {
            return false;
        }
        List<PlanningUnitMajorDTO> majors = !defaultList(unit.getSelectedMajors()).isEmpty()
                ? unit.getSelectedMajors() : unit.getAllMajors();
        for (PlanningUnitMajorDTO major : defaultList(majors)) {
            if (major != null && matchesAnyText(values, major.getMajorName())) {
                return true;
            }
        }
        return false;
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
