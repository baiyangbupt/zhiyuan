package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;

import java.util.List;

/**
 * 本省保底口径的唯一来源。
 *
 * <p>Q13：生源省被确认的硬约束明确排除（`mustExcludeRegions` 命中）时，
 * 本省保底没有可达对象，返回 `not_applicable` + `minLocalProtect=0`，
 * 而不是一个必然落空、会被当成“已知可执行目标”的保底数。</p>
 *
 * <p>省名缺失仍按 `unknown` 处理（无法判断是否被排除，不宣称 not_applicable）；
 * 未被排除的低分场景维持原有 `local_protect_floor` 口径。</p>
 */
final class SafetyFloorSupport {

    private SafetyFloorSupport() {
    }

    static StructureTargetDTO build(PlanningStateDTO state) {
        StructureTargetDTO target = new StructureTargetDTO();
        CandidatePoolStateDTO pool = state == null ? null : state.getCandidatePoolState();
        Integer userScore = pool == null ? null : pool.getUserScore();
        String sourceProvince = pool == null ? null : pool.getSourceProvinceName();
        HardConstraintsDTO hard = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardConstraints();
        // 排除是硬事实：命中即 not_applicable，与分数无关（分数只决定未排除时是否需要保底）。
        if (!Strings.isNullOrEmpty(sourceProvince) && excludesProvince(hard, sourceProvince)) {
            target.setMinLocalProtect(0);
            target.setSafetyFloorMode("not_applicable");
            target.setSafetyFloorReasonCode("province_excluded");
            return target;
        }
        if (userScore != null && userScore >= 580) {
            target.setMinLocalProtect(0);
            target.setSafetyFloorMode("applicable");
            target.setSafetyFloorReasonCode("score_ge_580");
            return target;
        }
        if (Strings.isNullOrEmpty(sourceProvince)) {
            target.setMinLocalProtect(0);
            target.setSafetyFloorMode("unknown");
            target.setSafetyFloorReasonCode("province_missing");
            return target;
        }
        target.setMinLocalProtect(2);
        target.setSafetyFloorMode("applicable");
        target.setSafetyFloorReasonCode("local_protect_floor");
        return target;
    }

    /**
     * 与 {@link RepairCandidateEligibility} 的区域判据同源（{@link RegionScopeSupport}）：
     * 大区表 + 规范化身份相等（`"浙江省"`＝`"浙江"`、`"内蒙古自治区"`＝`"内蒙古"`），
     * 不做双向子串放大。
     */
    private static boolean excludesProvince(HardConstraintsDTO hard, String sourceProvince) {
        if (hard == null) {
            return false;
        }
        List<String> excluded = hard.getMustExcludeRegions();
        if (excluded == null) {
            return false;
        }
        for (String value : excluded) {
            if (Strings.isNullOrEmpty(value)) {
                continue;
            }
            if (RegionScopeSupport.matchesRegionScope(value, sourceProvince, null)
                    || RegionScopeSupport.sameRegionName(sourceProvince, value)) {
                return true;
            }
        }
        return false;
    }
}
