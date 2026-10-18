package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureVectorDTO;

import java.util.List;
import java.util.Map;

/**
 * J5.4 S1：方案结构向量的唯一生产位置。
 *
 * <p>先做纯搬移，保持 {@link ReviewEvaluationMapper} 既有输出逐字不变；
 * 后续 tier/coverage 统一时只改这里，review/postcondition 都委托。</p>
 */
final class PlanStructureEvaluator {

    private PlanStructureEvaluator() {
    }

    static StructureVectorDTO build(EvaluationContextDTO context) {
        StructureVectorDTO structure = new StructureVectorDTO();
        Map<String, Integer> tierCounts = Maps.newLinkedHashMap();
        Map<String, Integer> unitTierCounts = Maps.newLinkedHashMap();
        int unitCount = 0;
        int itemCount = 0;
        int localSafety = 0;
        int highTuition = 0;
        int cooperative = 0;
        int special = 0;
        int admissionLimit = 0;
        double maxDelta = 0D;
        Double previousRatio = null;
        for (EvaluationEntryRefDTO entry : safeList(context == null ? null : context.getEntries())) {
            if (entry == null) {
                continue;
            }
            boolean unit = "unit".equals(entry.getLevel());
            if (unit) {
                unitCount++;
                unitTierCounts.merge(valueOrUnknown(entry.getPathTier()), 1, Integer::sum);
            } else {
                itemCount++;
                tierCounts.merge(valueOrUnknown(entry.getPathTier()), 1, Integer::sum);
            }
            if ("保".equals(entry.getPathTier())
                    && !Strings.isNullOrEmpty(context.getSourceProvince())
                    && context.getSourceProvince().equals(entry.getProvinceName())
                    && unit) {
                localSafety++;
            }
            if (entry.getTuitionPerYear() != null
                    && entry.getTuitionPerYear() > TuitionThresholds.HIGH_TUITION_RISK_PER_YEAR) {
                highTuition++;
            }
            List<String> flags = safeList(entry.getRiskFlags());
            if (flags.contains("cooperative_program")) {
                cooperative++;
            }
            if (flags.contains("special_enrollment")) {
                special++;
            }
            if (flags.contains("admission_limit")) {
                admissionLimit++;
            }
            Double ratio = entry.getMajorRatio() != null ? entry.getMajorRatio() : entry.getSchoolRatio();
            if (ratio != null) {
                if (previousRatio != null) {
                    maxDelta = Math.max(maxDelta, ratio - previousRatio);
                }
                previousRatio = ratio;
            }
        }
        structure.setUnitCount(unitCount);
        structure.setItemCount(itemCount);
        structure.setTierCounts(tierCounts);
        structure.setUnitTierCounts(unitTierCounts);
        structure.setLocalSafetyUnitCount(localSafety);
        structure.setHighTuitionCount(highTuition);
        structure.setCooperativeCount(cooperative);
        structure.setSpecialEnrollmentCount(special);
        structure.setAdmissionLimitCount(admissionLimit);
        structure.setAdjacentRatioDeltaMax(maxDelta);
        return structure;
    }

    private static <T> List<T> safeList(List<T> value) {
        return value == null ? Lists.newArrayList() : value;
    }

    private static String valueOrUnknown(String value) {
        return Strings.isNullOrEmpty(value) ? "unknown" : value;
    }
}
