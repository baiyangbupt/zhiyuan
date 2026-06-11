package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;

import java.util.List;
import java.util.Locale;
import java.util.stream.Collectors;

final class RepairReplacementActionBuilder {

    private RepairReplacementActionBuilder() {
    }

    static void populateStructuralReplacementActions(PlanningStateDTO state,
                                                     ReviewCheckDTO check,
                                                     FixProposalDTO proposal,
                                                     List<CompensationActionDTO> compensationActions) {
        if (proposal == null
                || (!"rebalance_tier_ratio".equals(proposal.getStrategy())
                && !"fill_probability_gap".equals(proposal.getStrategy()))) {
            return;
        }
        if (state == null || state.getCandidatePoolState() == null
                || !RepairCandidateSelector.isCurrentPlanAtOrAboveTargetCount(state)) {
            return;
        }
        String compensationActionType = "rebalance_tier_ratio".equals(proposal.getStrategy())
                ? "rebalance_protect_ratio" : "fill_probability_gap";
        CompensationActionDTO compensationAction = defaultList(compensationActions).stream()
                .filter(action -> action != null && compensationActionType.equals(action.getType()))
                .findFirst()
                .orElse(null);
        if (compensationAction == null) {
            return;
        }
        FixProposalActionDTO replacementAction = "rebalance_tier_ratio".equals(proposal.getStrategy())
                ? buildTierRatioReplacementAction(state, check, compensationAction)
                : buildProbabilityGapReplacementAction(state, check, compensationAction);
        proposal.getActions().removeIf(action -> action != null && compensationActionType.equals(action.getActionType()));
        if (replacementAction == null || replacementAction.getReplacementPairs().isEmpty()) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "当前方案已满，但暂时找不到可解释的替换配对，不能只追加候选。",
                    "replacement_pair_missing");
            return;
        }
        proposal.getActions().add(replacementAction);
    }

    static FixProposalActionDTO buildTierRatioReplacementAction(PlanningStateDTO state,
                                                                ReviewCheckDTO check,
                                                                CompensationActionDTO compensationAction) {
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        List<String> candidateVolunteerIds = distinctNonEmpty(defaultList(compensationAction.getVolunteerIds()));
        if (candidateVolunteerIds.isEmpty()) {
            return null;
        }
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        List<String> candidateUnitIds = majorGroupMode
                ? resolveCandidateUnitIdsForCompensationAction(compensationAction, candidates)
                : Lists.newArrayList();
        int targetCount = majorGroupMode && !candidateUnitIds.isEmpty() ? candidateUnitIds.size() : candidateVolunteerIds.size();
        String targetTier = RepairCandidateSelector.resolveCandidateTier(
                compensationAction.getVolunteerIds(), candidates);
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTierRatioReplacementSources(
                state, candidates, targetTier, targetCount);
        String removeTier = selection.getRemoveTier();
        if (selection.getRemoveVolunteerIds().isEmpty()) {
            return null;
        }
        if (majorGroupMode && candidateUnitIds.isEmpty()) {
            candidateUnitIds = RepairCandidateSelector.resolveUnitIdsFromVolunteerIds(candidateVolunteerIds, candidates);
        }
        if (majorGroupMode) {
            candidateUnitIds = RepairCandidateSelector.orderStructuralReplacementCandidateUnitIds(
                    selection.getRemoveUnitIds(), candidateUnitIds, candidates);
        } else {
            candidateVolunteerIds = RepairCandidateSelector.orderStructuralReplacementCandidateVolunteerIds(
                    selection.getRemoveVolunteerIds(), candidateVolunteerIds, candidates);
        }
        int pairCount = majorGroupMode
                ? Math.min(selection.getRemoveUnitIds().size(), candidateUnitIds.size())
                : Math.min(selection.getRemoveVolunteerIds().size(), candidateVolunteerIds.size());
        if (pairCount <= 0) {
            return null;
        }

        FixProposalActionDTO action = newBaseReplacementAction(check);
        action.setSummary("替换以平衡冲稳保配比");
        String baseDetail = String.format("当前方案已满，该策略只是结构调整预览，不会自动应用；建议用%s候选替换%s中相对低性价比的志愿。",
                Strings.isNullOrEmpty(targetTier) ? "目标区间" : targetTier + "区",
                Strings.isNullOrEmpty(removeTier) ? "当前方案" : removeTier + "区");
        populateReplacementPairs(action, candidates, selection, candidateVolunteerIds, candidateUnitIds,
                pairCount, majorGroupMode, check.getCode(), "rebalance_protect_ratio");
        action.setDetail(buildReplacementPreviewDetail(action, candidates, baseDetail));
        return action;
    }

    static FixProposalActionDTO buildProbabilityGapReplacementAction(PlanningStateDTO state,
                                                                     ReviewCheckDTO check,
                                                                     CompensationActionDTO compensationAction) {
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        List<String> candidateVolunteerIds = distinctNonEmpty(defaultList(compensationAction.getVolunteerIds()));
        if (candidateVolunteerIds.isEmpty()) {
            return null;
        }
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        List<String> candidateUnitIds = majorGroupMode
                ? resolveCandidateUnitIdsForCompensationAction(compensationAction, candidates)
                : Lists.newArrayList();
        int targetCount = majorGroupMode && !candidateUnitIds.isEmpty() ? candidateUnitIds.size() : candidateVolunteerIds.size();
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProbabilityGapReplacementSources(
                state, candidates, check, targetCount);
        if (selection.getRemoveVolunteerIds().isEmpty()) {
            return null;
        }
        if (majorGroupMode && candidateUnitIds.isEmpty()) {
            candidateUnitIds = RepairCandidateSelector.resolveUnitIdsFromVolunteerIds(candidateVolunteerIds, candidates);
        }
        if (majorGroupMode) {
            candidateUnitIds = RepairCandidateSelector.orderStructuralReplacementCandidateUnitIds(
                    selection.getRemoveUnitIds(), candidateUnitIds, candidates);
        } else {
            candidateVolunteerIds = RepairCandidateSelector.orderStructuralReplacementCandidateVolunteerIds(
                    selection.getRemoveVolunteerIds(), candidateVolunteerIds, candidates);
        }
        int pairCount = majorGroupMode
                ? Math.min(selection.getRemoveUnitIds().size(), candidateUnitIds.size())
                : Math.min(selection.getRemoveVolunteerIds().size(), candidateVolunteerIds.size());
        if (pairCount <= 0) {
            return null;
        }

        FixProposalActionDTO action = newBaseReplacementAction(check);
        action.setSummary("替换断层边界志愿");
        String baseDetail = "当前方案已满，该策略只是结构调整预览，不会自动应用；建议用中间录取率候选替换断层边界中相对低性价比的志愿。";
        populateReplacementPairs(action, candidates, selection, candidateVolunteerIds, candidateUnitIds,
                pairCount, majorGroupMode, check.getCode(), "fill_probability_gap");
        action.setDetail(buildReplacementPreviewDetail(action, candidates, baseDetail));
        return action;
    }

    private static FixProposalActionDTO newBaseReplacementAction(ReviewCheckDTO check) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setLevel(check.getLevel());
        action.setSourceCheckCode(check.getCode());
        return action;
    }

    private static void populateReplacementPairs(FixProposalActionDTO action,
                                                 List<CandidateItemDTO> candidates,
                                                 RepairCandidateSelector.Selection selection,
                                                 List<String> candidateVolunteerIds,
                                                 List<String> candidateUnitIds,
                                                 int pairCount,
                                                 boolean majorGroupMode,
                                                 String checkCode,
                                                 String reasonCode) {
        if (majorGroupMode) {
            List<String> keptRemoveUnitIds = selection.getRemoveUnitIds().subList(0, pairCount);
            List<String> keptCandidateUnitIds = candidateUnitIds.subList(0, pairCount);
            action.setRemoveUnitIds(Lists.newArrayList(keptRemoveUnitIds));
            action.setCandidateUnitIds(Lists.newArrayList(keptCandidateUnitIds));
            action.setRemoveVolunteerIds(RepairCandidateSelector.filterVolunteerIdsByUnitIds(
                    selection.getRemoveVolunteerIds(), candidates, keptRemoveUnitIds));
            action.setCandidateVolunteerIds(RepairCandidateSelector.filterVolunteerIdsByUnitIds(
                    candidateVolunteerIds, candidates, keptCandidateUnitIds));
            for (int i = 0; i < pairCount; i++) {
                action.getReplacementPairs().add(buildReplacementPair(
                        keptRemoveUnitIds.get(i),
                        RepairCandidateSelector.firstVolunteerIdForUnit(
                                action.getRemoveVolunteerIds(), candidates, keptRemoveUnitIds.get(i)),
                        keptCandidateUnitIds.get(i),
                        RepairCandidateSelector.firstVolunteerIdForUnit(
                                action.getCandidateVolunteerIds(), candidates, keptCandidateUnitIds.get(i)),
                        checkCode,
                        reasonCode));
            }
            return;
        }

        List<String> keptRemoveVolunteerIds = selection.getRemoveVolunteerIds().subList(0, pairCount);
        List<String> keptCandidateVolunteerIds = candidateVolunteerIds.subList(0, pairCount);
        action.setRemoveVolunteerIds(Lists.newArrayList(keptRemoveVolunteerIds));
        action.setCandidateVolunteerIds(Lists.newArrayList(keptCandidateVolunteerIds));
        for (int i = 0; i < pairCount; i++) {
            action.getReplacementPairs().add(buildReplacementPair(
                    null,
                    keptRemoveVolunteerIds.get(i),
                    null,
                    keptCandidateVolunteerIds.get(i),
                    checkCode,
                    reasonCode));
        }
    }

    private static ReplacementPairDTO buildReplacementPair(String fromUnitId,
                                                           String fromVolunteerId,
                                                           String toUnitId,
                                                           String toVolunteerId,
                                                           String checkCode,
                                                           String reasonCode) {
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromUnitId(fromUnitId);
        pair.setFromVolunteerId(fromVolunteerId);
        pair.setToUnitId(toUnitId);
        pair.setToVolunteerId(toVolunteerId);
        pair.setReasonCodes(Lists.newArrayList(checkCode, reasonCode));
        return pair;
    }

    private static String buildReplacementPreviewDetail(FixProposalActionDTO action,
                                                        List<CandidateItemDTO> candidates,
                                                        String baseDetail) {
        List<String> pairDetails = defaultList(action == null ? null : action.getReplacementPairs()).stream()
                .limit(3)
                .map(pair -> formatReplacementPairDetail(pair, candidates))
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        if (pairDetails.isEmpty()) {
            return baseDetail;
        }
        int remainingCount = defaultList(action.getReplacementPairs()).size() - pairDetails.size();
        String suffix = remainingCount > 0 ? String.format("；另有 %d 组配对未展开", remainingCount) : "";
        return baseDetail + " 具体预览：" + String.join("；", pairDetails) + suffix + "。";
    }

    private static String formatReplacementPairDetail(ReplacementPairDTO pair, List<CandidateItemDTO> candidates) {
        if (pair == null) {
            return "";
        }
        CandidateItemDTO from = findCandidate(candidates, pair.getFromVolunteerId());
        CandidateItemDTO to = findCandidate(candidates, pair.getToVolunteerId());
        String fromText = formatCandidateBrief(from, pair.getFromUnitId(), pair.getFromVolunteerId());
        String toText = formatCandidateBrief(to, pair.getToUnitId(), pair.getToVolunteerId());
        if (Strings.isNullOrEmpty(fromText) && Strings.isNullOrEmpty(toText)) {
            return "";
        }
        String changeText = formatChangeSummary(from, to);
        return fromText + " -> " + toText + (Strings.isNullOrEmpty(changeText) ? "" : "（" + changeText + "）");
    }

    private static CandidateItemDTO findCandidate(List<CandidateItemDTO> candidates, String volunteerId) {
        if (Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
            if (candidate != null && volunteerId.equals(candidate.getVolunteerId())) {
                return candidate;
            }
        }
        return null;
    }

    private static String formatCandidateBrief(CandidateItemDTO candidate, String unitId, String volunteerId) {
        if (candidate == null) {
            return firstNonBlank(
                    Strings.isNullOrEmpty(unitId) ? "" : "专业组 " + unitId,
                    Strings.isNullOrEmpty(volunteerId) ? "" : "志愿 " + volunteerId);
        }
        String label = (Strings.nullToEmpty(candidate.getSchoolName()) + "-" + Strings.nullToEmpty(candidate.getMajorName()))
                .replaceAll("^-|-$", "");
        if (Strings.isNullOrEmpty(label)) {
            label = firstNonBlank(
                    Strings.isNullOrEmpty(unitId) ? "" : "专业组 " + unitId,
                    Strings.isNullOrEmpty(volunteerId) ? "" : "志愿 " + volunteerId);
        }
        List<String> tags = Lists.newArrayList(
                candidate.getTier(),
                candidate.getAdmissionRatio() == null ? "" : "录取率" + formatNumber(candidate.getAdmissionRatio()) + "%",
                candidate.getFinalScore() == null ? "" : "推荐" + formatNumber(candidate.getFinalScore()),
                candidate.getSchoolRank() == null ? "" : "院校排名" + candidate.getSchoolRank());
        String tagText = tags.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining("/"));
        return Strings.isNullOrEmpty(tagText) ? label : label + "（" + tagText + "）";
    }

    private static String formatChangeSummary(CandidateItemDTO from, CandidateItemDTO to) {
        if (from == null || to == null) {
            return "";
        }
        List<String> changes = Lists.newArrayList(
                formatDelta("录取率", from.getAdmissionRatio(), to.getAdmissionRatio(), false),
                formatDelta("推荐", from.getFinalScore(), to.getFinalScore(), false),
                formatRankDelta(from.getSchoolRank(), to.getSchoolRank()));
        return changes.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining("，"));
    }

    private static String formatDelta(String label, Double from, Double to, boolean smallerIsBetter) {
        if (from == null || to == null) {
            return "";
        }
        double delta = to - from;
        if (Math.abs(delta) < 0.05D) {
            return "";
        }
        double displayDelta = smallerIsBetter ? -delta : delta;
        return label + (displayDelta > 0 ? "+" : "") + formatNumber(displayDelta);
    }

    private static String formatRankDelta(Integer from, Integer to) {
        if (from == null || from <= 0 || to == null || to <= 0 || from.equals(to)) {
            return "";
        }
        int delta = to - from;
        return delta > 0 ? "院校排名下降" + delta : "院校排名提升" + Math.abs(delta);
    }

    private static String formatNumber(Double value) {
        if (value == null) {
            return "";
        }
        return String.format(Locale.ROOT, "%.1f", value);
    }

    private static String firstNonBlank(String... values) {
        if (values == null) {
            return "";
        }
        for (String value : values) {
            if (!Strings.isNullOrEmpty(value)) {
                return value;
            }
        }
        return "";
    }

    private static List<String> resolveCandidateUnitIdsForCompensationAction(CompensationActionDTO action,
                                                                             List<CandidateItemDTO> candidates) {
        List<String> unitIds = distinctNonEmpty(defaultList(action.getUnitIds()));
        if (!unitIds.isEmpty()) {
            return unitIds;
        }
        return RepairCandidateSelector.resolveUnitIdsFromVolunteerIds(defaultList(action.getVolunteerIds()), candidates);
    }

    private static List<String> distinctNonEmpty(List<String> values) {
        return defaultList(values).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<CandidateItemDTO> defaultCandidates(List<CandidateItemDTO> candidates) {
        return candidates == null ? Lists.newArrayList() : candidates;
    }
}
