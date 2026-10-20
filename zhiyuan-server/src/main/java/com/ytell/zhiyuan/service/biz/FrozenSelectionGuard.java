package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * S0b：apply 前用当前状态复核冻结选择引用的实体是否还在、是否仍合格。
 *
 * <p>这是 selection-scoped digest 的先行版：不比较整池版本，只看被选实体；
 * 任一实体缺失/不合格 → 409，要求重新预览。apply 后仍由统一后置校验兜底。</p>
 */
final class FrozenSelectionGuard {

    private FrozenSelectionGuard() {
    }

    static void verify(PlanningStateDTO state,
                       List<CandidateItemDTO> effectiveCandidates,
                       FixProposalDTO proposal,
                       String expectedSelectionDigest) {
        if (proposal == null || proposal.getSolverResult() == null
                || proposal.getSolverResult().getSelectedEntityIds() == null) {
            return;
        }
        List<String> selectedIds = proposal.getSolverResult().getSelectedEntityIds();
        Map<String, List<String>> selectedMajorIdsByUnit =
                proposal.getSolverResult().getSelectedMajorIdsByUnit();
        if (Strings.isNullOrEmpty(expectedSelectionDigest)) {
            throw new BusinessException(409,
                    "user_goal_frozen_digest_missing: 预览缺少选择摘要，请重新生成");
        }
        if (selectedMajorIdsByUnit != null && !selectedMajorIdsByUnit.isEmpty()) {
            Set<String> selectedUnitIds = new LinkedHashSet<String>(selectedIds);
            for (String unitId : selectedMajorIdsByUnit.keySet()) {
                if (!selectedUnitIds.contains(unitId)) {
                    throw new BusinessException(409,
                            "solver_input_stale: 冻结选择中的专业组不在选中实体中：" + unitId);
                }
            }
        }
        String actual = FrozenSelectionDigest.compute(state, effectiveCandidates, proposal);
        if (!expectedSelectionDigest.equals(actual)) {
            throw new BusinessException(409,
                    "solver_input_stale: 冻结选择或当前方案已变化，请重新预览");
        }
        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(state, effectiveCandidates);
        Map<String, CandidateFactDTO> facts = new LinkedHashMap<String, CandidateFactDTO>();
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            if (fact != null && !Strings.isNullOrEmpty(fact.getEntityId())) {
                facts.put(fact.getEntityId(), fact);
            }
        }
        for (String id : selectedIds) {
            CandidateFactDTO fact = facts.get(id);
            if (fact == null) {
                throw new BusinessException(409,
                        "solver_input_stale: 冻结选择中的实体已不可用：" + id);
            }
            if (!Boolean.TRUE.equals(fact.getEligible())) {
                throw new BusinessException(409,
                        "solver_input_stale: 冻结选择中的实体已不满足硬要求：" + id);
            }
            List<String> selectedMajors = selectedMajorIdsByUnit == null
                    ? null : selectedMajorIdsByUnit.get(id);
            if (selectedMajors == null || selectedMajors.isEmpty()) {
                continue;
            }
            Set<String> availableVolunteerIds = new LinkedHashSet<String>();
            if (fact.getRawCandidates() != null) {
                for (CandidateItemDTO raw : fact.getRawCandidates()) {
                    if (raw != null && !Strings.isNullOrEmpty(raw.getVolunteerId())) {
                        availableVolunteerIds.add(raw.getVolunteerId());
                    }
                }
            }
            for (String majorId : selectedMajors) {
                if (!availableVolunteerIds.contains(majorId)) {
                    throw new BusinessException(409,
                            "solver_input_stale: 冻结选择中的专业已不可用："
                                    + id + "/" + majorId);
                }
            }
        }
    }
}
