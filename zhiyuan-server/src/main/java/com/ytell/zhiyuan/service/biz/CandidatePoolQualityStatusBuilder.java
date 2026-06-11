package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PhysicalConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

import java.util.List;
import java.util.Map;

final class CandidatePoolQualityStatusBuilder {

    private CandidatePoolQualityStatusBuilder() {
    }

    static void apply(PlanningStateDTO state, CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return;
        }
        String statusCode = CandidatePoolStatusResolver.resolveStatus(candidatePoolState);
        candidatePoolState.setStatusCode(statusCode);
        candidatePoolState.setRiskHints(Lists.newArrayList());
        if ("empty".equals(statusCode)) {
            candidatePoolState.setStatusMessage("当前可用于规划的候选池暂无可用志愿，请核验专项资格、批次、分数线、选科或身体限报等条件");
            candidatePoolState.getRiskHints().addAll(buildRiskHints(state, candidatePoolState, true));
        } else if ("low_count".equals(statusCode)) {
            candidatePoolState.setStatusMessage("当前可用于规划的候选偏少，方案选择空间有限");
            candidatePoolState.getRiskHints().addAll(buildRiskHints(state, candidatePoolState, false));
        } else {
            candidatePoolState.setStatusCode("ready");
            candidatePoolState.setStatusMessage("候选池已生成");
        }
    }

    static List<String> buildRiskHints(PlanningStateDTO state,
                                       CandidatePoolStateDTO candidatePoolState,
                                       boolean emptyPool) {
        List<String> hints = Lists.newArrayList();
        int required = CandidatePoolStatusResolver.resolveRequiredCandidateCount(candidatePoolState);
        int available = isMajorGroupMode(candidatePoolState)
                ? valueOrZero(candidatePoolState.getSummary() == null ? null : candidatePoolState.getSummary().getUnitTotal())
                : valueOrZero(candidatePoolState.getSummary() == null ? null : candidatePoolState.getSummary().getTotal());
        if (required > 0) {
            hints.add(String.format("当前可用候选 %d 个，目标需要 %d 个", available, required));
        }
        appendTierShortageHints(hints, candidatePoolState);
        appendScoreBoundaryHint(hints, candidatePoolState);
        appendHardConstraintHints(hints, state);
        if (hints.isEmpty()) {
            hints.add(emptyPool
                    ? "当前批次、分数线、选科、专项资格或身体限报等硬条件可能导致无可用候选"
                    : "候选不足更可能来自批次、分数线、选科、专项资格或身体限报等硬条件");
        }
        return hints;
    }

    private static void appendTierShortageHints(List<String> hints, CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null || candidatePoolState.getRequiredTierCounts() == null || candidatePoolState.getRequiredTierCounts().isEmpty()
                || candidatePoolState.getSummary() == null) {
            return;
        }
        Map<String, Integer> availableTierCounts = isMajorGroupMode(candidatePoolState)
                ? candidatePoolState.getSummary().getUnitTierCounts()
                : candidatePoolState.getSummary().getTierCounts();
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            int required = valueOrZero(candidatePoolState.getRequiredTierCounts().get(tier));
            int available = valueOrZero(availableTierCounts == null ? null : availableTierCounts.get(tier));
            if (required > 0 && available < required) {
                hints.add(String.format("%s区候选不足：当前 %d 个，目标 %d 个", tier, available, required));
            }
        }
    }

    private static void appendScoreBoundaryHint(List<String> hints, CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null || candidatePoolState.getUserScore() == null || candidatePoolState.getBatchScore() == null) {
            return;
        }
        int diff = candidatePoolState.getUserScore() - candidatePoolState.getBatchScore();
        if (diff >= 0 && diff <= 30) {
            hints.add(String.format("当前分数距离批次线 %d 分，可选空间可能偏窄", diff));
        }
    }

    private static void appendHardConstraintHints(List<String> hints, PlanningStateDTO state) {
        PhysicalConstraintsDTO physicalConstraints = state == null || state.getProfileState() == null
                ? null : state.getProfileState().getPhysicalConstraints();
        if (physicalConstraints == null) {
            return;
        }
        if (!defaultList(physicalConstraints.getColorVision()).isEmpty()
                || !Strings.isNullOrEmpty(physicalConstraints.getHeight())
                || physicalConstraints.getVision() != null
                && (!Strings.isNullOrEmpty(physicalConstraints.getVision().getLeft())
                || !Strings.isNullOrEmpty(physicalConstraints.getVision().getRight()))) {
            hints.add("身体条件和限报要求可能会限制可用候选，需要结合招生要求核验");
        }
        if (!defaultList(physicalConstraints.getSpecialLimits()).isEmpty()) {
            hints.add("专项、民族、外方院校等资格条件可能会限制可用候选，需要核验资格条件");
        }
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static List<String> defaultList(List<String> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static int valueOrZero(Integer value) {
        return value == null ? 0 : value;
    }
}
