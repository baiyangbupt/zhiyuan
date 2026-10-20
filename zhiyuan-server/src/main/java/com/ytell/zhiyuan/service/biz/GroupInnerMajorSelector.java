package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 专业组组内专业选择：与初始推荐 buildPlanningUnit 的口径一致。
 *
 * <p>优先保留一个 safety major（admissionRatio ≥ 组 enrollRatio），再按
 * preferred / 未来发展 / 意向 / 录取率 / 分数排序补足到 requiredMajorCount。
 * 返回顺序保持原始候选顺序，避免影响组内展示/落盘顺序。</p>
 */
final class GroupInnerMajorSelector {

    private GroupInnerMajorSelector() {
    }

    static List<CandidateItemDTO> select(List<CandidateItemDTO> unitCandidates,
                                         Integer requiredMajorCount,
                                         Double unitEnrollRatio) {
        List<CandidateItemDTO> candidates = unitCandidates == null
                ? new ArrayList<CandidateItemDTO>() : unitCandidates;
        if (candidates.isEmpty() || requiredMajorCount == null
                || requiredMajorCount <= 0 || candidates.size() <= requiredMajorCount) {
            return candidates;
        }
        List<CandidateItemDTO> sorted = new ArrayList<CandidateItemDTO>(candidates);
        sorted.sort(innerComparator());
        Set<String> selected = new LinkedHashSet<String>();
        for (CandidateItemDTO candidate : sorted) {
            if (candidate != null && candidate.getAdmissionRatio() != null
                    && unitEnrollRatio != null
                    && candidate.getAdmissionRatio() >= unitEnrollRatio) {
                selected.add(candidate.getVolunteerId());
                break;
            }
        }
        for (CandidateItemDTO candidate : sorted) {
            if (selected.size() >= requiredMajorCount) {
                break;
            }
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                selected.add(candidate.getVolunteerId());
            }
        }
        List<CandidateItemDTO> result = new ArrayList<CandidateItemDTO>();
        for (CandidateItemDTO candidate : candidates) {
            if (candidate != null && selected.contains(candidate.getVolunteerId())) {
                result.add(candidate);
            }
        }
        return result;
    }

    private static Comparator<CandidateItemDTO> innerComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> Boolean.TRUE.equals(item.getPreferred()) ? 0 : 1)
                .thenComparing(CandidateItemDTO::getFutureDevelopmentScore,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getIntentScore,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getAdmissionRatio,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getFinalScore,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getVolunteerId,
                        Comparator.nullsLast(String::compareTo));
    }
}
