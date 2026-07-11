package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;

import java.util.List;
import java.util.function.Function;
import java.util.stream.Collectors;

final class RepairRiskActionBuilder {

    private RepairRiskActionBuilder() {
    }

    static void populateRemoveRiskItemActions(FixProposalDTO proposal,
                                              ReviewCheckDTO check,
                                              List<CompensationActionDTO> compensationActions,
                                              Function<List<String>, CompensationActionDTO> fallbackFillActionFactory) {
        if (proposal == null
                || !RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS.equals(
                RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy()))) {
            return;
        }
        List<String> affectedVolunteerIds = defaultList(check == null ? null : check.getAffectedVolunteerIds()).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
        if (affectedVolunteerIds.isEmpty()) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "当前风险缺少可移除的志愿明细。",
                    "risk_item_unresolved");
            return;
        }
        FixProposalActionDTO removeAction = new FixProposalActionDTO();
        removeAction.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
        removeAction.setLevel(check.getLevel());
        removeAction.setSourceCheckCode(check.getCode());
        removeAction.setSummary("移除风险志愿");
        removeAction.setDetail(String.format("将移除 %d 条命中该风险的志愿。", affectedVolunteerIds.size()));
        removeAction.setVolunteerIds(affectedVolunteerIds);
        removeAction.setUnitIds(defaultList(check.getAffectedUnitIds()));
        proposal.getActions().add(0, removeAction);

        if (compensationActions != null && !compensationActions.isEmpty()) {
            return;
        }
        CompensationActionDTO fillAction = fallbackFillActionFactory == null
                ? null : fallbackFillActionFactory.apply(affectedVolunteerIds);
        if (fillAction != null) {
            proposal.getActions().add(toFixProposalAction(fillAction));
        }
    }

    static void populateReplaceRiskItemActions(PlanningStateDTO state,
                                               ReviewCheckDTO check,
                                               FixProposalDTO proposal) {
        if (proposal == null
                || !RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS.equals(
                RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy()))) {
            return;
        }
        List<String> affectedVolunteerIds = defaultList(check == null ? null : check.getAffectedVolunteerIds()).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
        if (affectedVolunteerIds.isEmpty() || state == null || state.getCandidatePoolState() == null) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "当前风险缺少可替换的志愿明细。",
                    "risk_item_unresolved");
            return;
        }
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        RepairCandidateSelector.RiskReplacementSelection selection = RepairCandidateSelector.selectRiskItemReplacements(
                state, candidates, affectedVolunteerIds);
        for (RepairCandidateSelector.RiskReplacementPair pair : selection.getPairs()) {
            proposal.getActions().add(buildReplaceRiskItemAction(check, pair.getSource(), pair.getReplacement()));
        }
        int replacementCount = proposal.getActions().stream()
                .filter(action -> RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(action.getActionType()))
                .mapToInt(action -> action.getReplacementPairs() == null ? 0 : action.getReplacementPairs().size())
                .sum();
        if (selection.getMissingSourceCount() > 0) {
            proposal.getDryRunResult().getWarnings().add(String.format("有 %d 条风险志愿缺少候选明细，暂时无法配对替换。",
                    selection.getMissingSourceCount()));
        }
        if (selection.getNoReplacementCount() > 0) {
            proposal.getDryRunResult().getWarnings().add(String.format("有 %d 条风险志愿暂时没有同时满足同层次、风险更低、专业相近且院校层次代价可接受的替换项。",
                    selection.getNoReplacementCount()));
        }
        if (replacementCount <= 0) {
            RepairProposalStateBuilder.markBlocked(proposal,
                    "当前候选不足，暂时没有同时满足同层次、风险更低、专业相近且院校层次代价可接受的替换项。",
                    "safe_replacement_candidate_insufficient");
        } else if (replacementCount < affectedVolunteerIds.size()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.PREVIEW_ONLY);
            proposal.getDryRunResult().getWarnings().add("当前只找到部分风险志愿的替换预览，未覆盖的条目需要人工调整或放宽候选范围。");
        }
    }

    private static FixProposalActionDTO buildReplaceRiskItemAction(ReviewCheckDTO check,
                                                                   CandidateItemDTO source,
                                                                   CandidateItemDTO replacement) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS);
        action.setLevel(check.getLevel());
        action.setSourceCheckCode(check.getCode());
        action.setSummary("替换风险志愿");
        action.setDetail(String.format("建议用 %s-%s 替换 %s-%s。",
                Strings.nullToEmpty(replacement.getSchoolName()),
                Strings.nullToEmpty(replacement.getMajorName()),
                Strings.nullToEmpty(source.getSchoolName()),
                Strings.nullToEmpty(source.getMajorName())));
        action.setRemoveVolunteerIds(Lists.newArrayList(source.getVolunteerId()));
        action.setCandidateVolunteerIds(Lists.newArrayList(replacement.getVolunteerId()));
        String sourceUnitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(source);
        String replacementUnitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(replacement);
        if (!Strings.isNullOrEmpty(sourceUnitId)) {
            action.setRemoveUnitIds(Lists.newArrayList(sourceUnitId));
        }
        if (!Strings.isNullOrEmpty(replacementUnitId)) {
            action.setCandidateUnitIds(Lists.newArrayList(replacementUnitId));
        }
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromUnitId(sourceUnitId);
        pair.setFromVolunteerId(source.getVolunteerId());
        pair.setToUnitId(replacementUnitId);
        pair.setToVolunteerId(replacement.getVolunteerId());
        pair.setReasonCodes(Lists.newArrayList(check.getCode(), "same_tier_safe_replacement"));
        action.getReplacementPairs().add(pair);
        populateActionTotals(action);
        return action;
    }

    private static FixProposalActionDTO toFixProposalAction(CompensationActionDTO action) {
        FixProposalActionDTO target = new FixProposalActionDTO();
        target.setActionType(action.getType());
        target.setLevel(action.getLevel());
        target.setSourceCheckCode(action.getSourceCheckCode());
        target.setSummary(action.getSummary());
        target.setDetail(action.getDetail());
        target.setUnitIds(defaultList(action.getUnitIds()));
        target.setVolunteerIds(defaultList(action.getVolunteerIds()));
        populateActionTotals(target);
        return target;
    }

    private static void populateActionTotals(FixProposalActionDTO action) {
        if (action == null) {
            return;
        }
        action.setTotalUnitCount(Math.max(defaultList(action.getRemoveUnitIds()).size(),
                Math.max(defaultList(action.getCandidateUnitIds()).size(), defaultList(action.getUnitIds()).size())));
        action.setTotalVolunteerCount(Math.max(defaultList(action.getRemoveVolunteerIds()).size(),
                Math.max(defaultList(action.getCandidateVolunteerIds()).size(), defaultList(action.getVolunteerIds()).size())));
        action.setTotalReplacementPairCount(defaultList(action.getReplacementPairs()).size());
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<CandidateItemDTO> defaultCandidates(List<CandidateItemDTO> candidates) {
        return candidates == null ? Lists.newArrayList() : candidates;
    }
}
