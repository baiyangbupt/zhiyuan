package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 专项资格要求的单一归一器。
 *
 * <p>正式标签/名称只在“该计划要求专项资格”这个方向上使用；名称不能证明用户有资格。
 * 三类明确专项（国家/地方/高校）与泛称“专项计划”才构成明确要求；含糊的“专项/定向/公费”
 * 只记为 unknown，不能拿 false 去猜、也不能当已通过。</p>
 */
final class SpecialPlanRequirementSupport {

    static final String NATIONAL = "national";
    static final String LOCAL = "local";
    static final String SCHOOL = "school";
    static final String GENERIC = "generic";
    static final String UNKNOWN = "unknown";

    private SpecialPlanRequirementSupport() {
    }

    static Requirement requirement(CandidateItemDTO item) {
        Requirement result = new Requirement();
        if (item == null) {
            return result;
        }
        collect(result, item.getMajorName());
        collect(result, item.getDisplaySchoolName());
        collect(result, item.getSchoolName());
        collect(result, item.getMajorPlanTags());
        collect(result, item.getReasonCodes());
        collect(result, item.getRiskFlags());
        collect(result, item.getSchoolPopupTags());
        collect(result, item.getSchoolBasicTags());
        collect(result, item.getMajorRankTags());
        return result;
    }

    static Requirement requirement(PlanningUnitDTO unit) {
        Requirement result = new Requirement();
        if (unit == null) {
            return result;
        }
        collect(result, unit.getSchoolName());
        for (PlanningUnitMajorDTO major : unit.getSelectedMajors() == null
                || unit.getSelectedMajors().isEmpty()
                ? unit.getAllMajors() : unit.getSelectedMajors()) {
            if (major == null) {
                continue;
            }
            collect(result, major.getMajorName());
            collect(result, major.getMajorPlanTags());
            collect(result, major.getReasonCodes());
        }
        return result;
    }

    static Requirement requirement(EvaluationEntryRefDTO entry) {
        Requirement result = new Requirement();
        if (entry != null) {
            collect(result, entry.getSchoolName());
            collect(result, entry.getMajorName());
            collect(result, entry.getSelectedMajorNames());
            collect(result, entry.getRiskTags());
            collect(result, entry.getRiskFlags());
        }
        return result;
    }

    /**
     * 明确“没有任何专项”时，命中任一明确专项要求即为冲突；unknown 不自动放行。
     * true/null 不在这里判冲突（true 的具体类别仍需核验）。
     */
    static boolean conflictsWithNoSpecial(Boolean specialPlan, Requirement requirement) {
        return Boolean.FALSE.equals(specialPlan)
                && requirement != null
                && (requirement.anyExplicit() || requirement.evidenceConflict);
    }

    private static void collect(Requirement result, String text) {
        if (Strings.isNullOrEmpty(text)) {
            return;
        }
        String value = text.trim().toLowerCase(Locale.ROOT);
        result.ordinaryEvidence |= value.contains("普通类") || value.contains("非专项");
        value = value.replace("非国家专项", "")
                .replace("非地方专项", "")
                .replace("非高校专项", "")
                .replace("非专项计划", "")
                .replace("非专项招生", "")
                .replace("非专项", "")
                .replace("非定向", "")
                .replace("非公费", "");
        if (value.contains("国家专项") || value.contains("国家计划")) {
            result.types.add(NATIONAL);
        }
        if (value.contains("地方专项")) {
            result.types.add(LOCAL);
        }
        if (value.contains("高校专项")) {
            result.types.add(SCHOOL);
        }
        if (value.contains("专项计划") || value.contains("专项招生")) {
            result.types.add(GENERIC);
        }
        if ((value.contains("专项") || value.contains("定向") || value.contains("公费")
                || value.contains("楚怡工匠")) && !result.anyExplicit()) {
            result.unknown = true;
        }
        if (result.ordinaryEvidence && result.anyExplicit()) {
            result.evidenceConflict = true;
        }
        if (result.anyExplicit()) {
            // 正式普通类标签 + 名称专项 = 证据冲突，保留冲突而不是降级为 unknown。
            result.evidenceConflict |= result.ordinaryEvidence;
        }
    }

    private static void collect(Requirement result, List<String> values) {
        if (values == null) {
            return;
        }
        for (String value : values) {
            collect(result, value);
        }
    }

    static final class Requirement {
        private final Set<String> types = new LinkedHashSet<String>();
        private boolean unknown;
        private boolean ordinaryEvidence;
        private boolean evidenceConflict;

        boolean anyExplicit() {
            return types.contains(NATIONAL) || types.contains(LOCAL)
                    || types.contains(SCHOOL) || types.contains(GENERIC);
        }

        boolean isUnknown() {
            return unknown && !anyExplicit();
        }

        boolean evidenceConflict() {
            return evidenceConflict;
        }

        Set<String> types() {
            return types;
        }
    }
}
