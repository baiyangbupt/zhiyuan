package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 两阶段组内选择第一阶段：为每个 unit fact 预处理“组内计划专业”。
 *
 * <p>计划口径与 GroupInnerMajorSelector 一致：requiredMajorCount 为上限，
 * 组内不足时全保留；safety major 优先。阶段 1 的 unit 选择会使用这份计划
 * 计算 utility/coverage/preferred/risk，阶段 2 再落成 selectedMajorIdsByUnit。</p>
 */
final class InnerMajorPlanBuilder {

    private InnerMajorPlanBuilder() {
    }

    static Map<String, List<String>> build(List<CandidateFactDTO> facts,
                                           Integer requiredMajorCount) {
        Map<String, List<String>> plan = new LinkedHashMap<String, List<String>>();
        for (CandidateFactDTO fact : facts == null
                ? java.util.Collections.<CandidateFactDTO>emptyList() : facts) {
            if (fact == null || Strings.isNullOrEmpty(fact.getEntityId())) {
                continue;
            }
            List<CandidateItemDTO> candidates = fact.getRawCandidates() == null
                    ? new ArrayList<CandidateItemDTO>() : fact.getRawCandidates();
            Double unitEnrollRatio = null;
            for (CandidateItemDTO candidate : candidates) {
                if (candidate != null && candidate.getSchoolEnrollRatio() != null) {
                    unitEnrollRatio = candidate.getSchoolEnrollRatio();
                    break;
                }
            }
            List<CandidateItemDTO> selected = fact.getPlannedCandidates() != null
                    && !fact.getPlannedCandidates().isEmpty()
                    ? fact.getPlannedCandidates()
                    : GroupInnerMajorSelector.select(candidates, requiredMajorCount, unitEnrollRatio);
            List<String> ids = new ArrayList<String>();
            for (CandidateItemDTO candidate : selected) {
                if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                    ids.add(candidate.getVolunteerId());
                }
            }
            plan.put(fact.getEntityId(), ids);
        }
        return plan;
    }
}
