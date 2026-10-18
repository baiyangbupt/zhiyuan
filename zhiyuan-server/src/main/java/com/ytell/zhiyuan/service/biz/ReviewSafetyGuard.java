package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;

import java.util.List;

/**
 * J5.4：review 的 safety_guard 与 solver 共用 {@link SafetyFloorSupport}。
 *
 * <p>以前 review 自己算一套：分数阈值、本省包含匹配、固定 2 条，且不识别
 * “生源省已被硬约束排除”。Q13 之后 solver 会返回 `not_applicable`，两边
 * 必须同源，否则会出现“solver 放行、review 硬拦”。</p>
 */
final class ReviewSafetyGuard {

    private ReviewSafetyGuard() {
    }

    static ReviewCheckDTO evaluate(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("safety_guard");
        check.setLevel("info");
        check.setPassed(true);

        StructureTargetDTO floor = SafetyFloorSupport.build(state);
        String mode = floor.getSafetyFloorMode();
        if ("not_applicable".equals(mode)) {
            check.setSummary("生源省已被明确排除，本省保底不适用");
            check.setDetail("本省已从硬约束中排除，不再要求本省保底志愿。");
            return check;
        }
        if ("unknown".equals(mode)) {
            check.setLevel("warn");
            check.setSummary("缺少生源省份信息，无法完成本省保底校验");
            check.setDetail("candidatePoolState.sourceProvinceName 为空。");
            check.setSuggestedAction("建议补充用户高考省份后重新执行审查。");
            return check;
        }
        int required = floor.getMinLocalProtect() == null ? 0 : floor.getMinLocalProtect();
        if (required <= 0) {
            check.setSummary("当前兜底方案相对安全");
            check.setDetail("用户分数不低于580，按照当前经验规则视为相对安全。");
            return check;
        }

        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        String sourceProvinceName = pool.getSourceProvinceName();
        int localProtectCount = 0;
        if (isMajorGroupMode(pool)) {
            for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
                if (!SafetyFloorSupport.isLocalProtect(
                        unit.getTier(), unit.getProvinceName(), sourceProvinceName)) {
                    continue;
                }
                localProtectCount++;
                check.getAffectedUnitIds().add(unit.getUnitId());
                defaultList(unit.getMajorItems()).stream()
                        .map(PlanningUnitMajorDTO::getVolunteerId)
                        .forEach(check.getAffectedVolunteerIds()::add);
            }
        } else {
            for (OrderedItemDTO orderedItem : defaultList(state.getOrderedPlanState().getItems())) {
                CandidateItemDTO candidateItem = findCandidate(candidates, orderedItem.getVolunteerId());
                String tier = Strings.isNullOrEmpty(orderedItem.getTier())
                        ? (candidateItem == null ? null : candidateItem.getTier())
                        : orderedItem.getTier();
                String province = candidateItem == null ? null : candidateItem.getProvinceName();
                if (SafetyFloorSupport.isLocalProtect(tier, province, sourceProvinceName)) {
                    localProtectCount++;
                    check.getAffectedVolunteerIds().add(orderedItem.getVolunteerId());
                }
            }
        }
        if (localProtectCount >= required) {
            check.setSummary("当前兜底方案相对安全");
            check.setDetail("保区间中本省院校数量不少于" + required + "所。");
            return check;
        }

        check.setPassed(false);
        check.setLevel("risk");
        check.setSummary("本省保底志愿数量不足");
        check.setDetail("当前保区间中本省院校数量少于" + required + "所。");
        check.setSuggestedAction("建议优先补充本省保底志愿，降低滑档和退档风险。");
        return check;
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO pool) {
        return pool != null && "majorGroup".equalsIgnoreCase(pool.getVolunteerModel());
    }

    private static CandidateItemDTO findCandidate(List<CandidateItemDTO> candidates, String volunteerId) {
        if (candidates == null || Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        for (CandidateItemDTO candidate : candidates) {
            if (candidate != null && volunteerId.equals(candidate.getVolunteerId())) {
                return candidate;
            }
        }
        return null;
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? java.util.Collections.<T>emptyList() : values;
    }
}
