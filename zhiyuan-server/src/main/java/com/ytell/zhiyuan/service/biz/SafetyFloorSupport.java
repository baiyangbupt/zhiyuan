package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;

import java.util.List;
import java.util.Locale;

/**
 * 本省保底口径的唯一来源。
 *
 * <p>J5.3 先只服务 solver shadow；J5.4 再把 review 的 safety_guard 切到
 * 同一实现。当前默认 `safetyFloorNotApplicableEnabled=false`，所以即使
 * 命中“明确排除本省”，也只记录 reason，不改变 review 的旧行为。</p>
 */
final class SafetyFloorSupport {

    private SafetyFloorSupport() {
    }

    static StructureTargetDTO build(PlanningStateDTO state) {
        StructureTargetDTO target = new StructureTargetDTO();
        CandidatePoolStateDTO pool = state == null ? null : state.getCandidatePoolState();
        Integer userScore = pool == null ? null : pool.getUserScore();
        String sourceProvince = pool == null ? null : pool.getSourceProvinceName();
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
        HardConstraintsDTO hard = state.getConstraintState() == null
                ? null : state.getConstraintState().getHardConstraints();
        if (excludesProvince(hard, sourceProvince)) {
            // J5.4 前只记录，不真正返回 not_applicable。
            target.setMinLocalProtect(2);
            target.setSafetyFloorMode("applicable");
            target.setSafetyFloorReasonCode("province_excluded_pending_j54");
            target.getDiagnostics().add("safety_floor_not_applicable_pending_j54");
            return target;
        }
        target.setMinLocalProtect(2);
        target.setSafetyFloorMode("applicable");
        target.setSafetyFloorReasonCode("local_protect_floor");
        return target;
    }

    private static boolean excludesProvince(HardConstraintsDTO hard, String sourceProvince) {
        if (hard == null) {
            return false;
        }
        String source = sourceProvince.trim().toLowerCase(Locale.ROOT);
        List<String> excluded = hard.getMustExcludeRegions();
        if (excluded == null) {
            return false;
        }
        for (String value : excluded) {
            if (value == null) {
                continue;
            }
            String candidate = value.trim().toLowerCase(Locale.ROOT);
            if (!candidate.isEmpty()
                    && (candidate.equals(source) || source.contains(candidate)
                    || candidate.contains(source))) {
                return true;
            }
        }
        return false;
    }
}
