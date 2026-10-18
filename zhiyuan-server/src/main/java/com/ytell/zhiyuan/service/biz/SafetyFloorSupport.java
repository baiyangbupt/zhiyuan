package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;

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
        // ID 优先：regionPreferenceIds 写入的 mustExcludeRegionIds 只有 ID，没有名字。
        if (!Strings.isNullOrEmpty(sourceProvince)
                && RepairCandidateEligibility.isRegionExcluded(
                hard, sourceProvince, null, sourceProvinceId(pool, sourceProvince), null)) {
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
     * 生源省 ID 未单独存储；从候选池里取同省的候选省份 ID。
     * 池里没有同省候选时返回 null，此时只剩名字判据（不会误判成 not_applicable）。
     */
    private static String sourceProvinceId(CandidatePoolStateDTO pool, String sourceProvince) {
        if (pool == null || pool.getItems() == null) {
            return null;
        }
        for (CandidateItemDTO candidate : pool.getItems()) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getProvinceId())) {
                continue;
            }
            if (RegionScopeSupport.sameRegionName(candidate.getProvinceName(), sourceProvince)) {
                return candidate.getProvinceId();
            }
        }
        return null;
    }
}
